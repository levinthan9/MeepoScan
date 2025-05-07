import cv2
import datetime
#import easyocr
import numpy as np
import os
import pytesseract
pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
import queue
import re
import subprocess
import tempfile
import time
import tkinter as tk

from bs4 import BeautifulSoup
from collections import Counter
from datetime import datetime
from PIL import Image, ImageTk
from queue import Queue, Empty
from subprocess import run
from threading import Thread, Event
from tkinter import messagebox, Label, Frame, simpledialog

stop_event = Event()
thread_running = False
blink_state = False
check_type = False  # False = Basic, True = iCloud-MDM

status_var = None
number_var = None
mode_var = None
feed_frame = None  # Shared between threads
manual_window = None
manual_stop = False
serial = ""
processed_frame_count = 0
frame_queue_length = 0
stop_ocr_processing_event = Event()


# Create a queue to hold processed frames
frame_queue = queue.Queue()
# Initialize EasyOCR reader
#reader = easyocr.Reader(['en'])

# Global paths
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PRINTER_NAME = "4BARCODE"
TEMP_DIR = tempfile.gettempdir()

# Time to wait before allowing the same match again (in seconds)
DUPLICATE_TIMEOUT = 20
recent_matches = {}

# =============================== CONFIG ===============================
autostart = True
autocrop = False

# Initialize the flip state
flip_active = False

roi_x, roi_y, roi_w, roi_h = 600, 100, 800, 300  # crop area
scan_interval = 5
use_processed_frame = True  # Default is original frame
ocr_mode = "pytesseract" #easyocr or pytesseract

# Regex patterns
serial_pattern = re.compile(r'\b[A-Z0-9]{10,12}\b')
#serial_pattern = re.compile(r'\bSerial[:\s\-]*([A-Z0-9]{10,12})\b')
amodel_pattern = re.compile(r'\bA\d{4}\b')
emc_pattern = re.compile(r'\bEMC\s(\d{4})\b')






def sharpen(image):
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])
    return cv2.filter2D(image, -1, kernel)

def enhance_contrast(image):
    return cv2.equalizeHist(image)


def binarize(image):
    return cv2.adaptiveThreshold(image, 255,
                                 cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 11, 2)



def denoise(image):
    return cv2.fastNlMeansDenoising(image, None, 30, 7, 21)

def resize_for_ocr(image, factor=2):
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)

def preprocess_for_ocr(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = resize_for_ocr(gray)
    sharpened = sharpen(resized)
    denoised = denoise(sharpened)
    contrast = enhance_contrast(denoised)
    binary = binarize(contrast)
    return binary


def update_status():
    if blink_state:
        status_var.set("🟢 Running")
    else:
        status_var.set("⚪ Running")
    root.after(500, blink_status)


def blink_status():
    global blink_state
    blink_state = not blink_state
    if thread_running:
        update_status()


def toggle_thread():
    #global processed_frame_count
    if thread_running:
        stop_event.set()
        stop_ocr_processing_event.set()
        processed_frame_count = 0
        while not frame_queue.empty():
            try:
                frame_queue.get_nowait()  # Remove each item in a thread-safe way
            except Empty:
                break
        start_button.config(text="Start")
    else:
        stop_event.clear()
        stop_ocr_processing_event.clear()
        Thread(target=background_task, daemon=True).start()
        Thread(target=ocr_processing, daemon=True).start()
        start_button.config(text="Stop")

def toggle_mode():
    global check_type
    if thread_running:
        stop_event.set()
        start_button.config(text="Start")
        status_var.set("🔴 Stopped")
    check_type = not check_type
    mode_var.set("Mode: iCloud-MDM" if check_type else "Mode: Basic")
    mode_label.config(fg="red" if check_type else "green")

def on_spacebar(event=None):
    global manual_stop
    toggle_thread()
    manual_stop = not manual_stop




def runcommand(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

def spec_check(serial_number):
    url = f"https://macfinder.co.uk/model/macbook-pro-15-inch-2018/?serial={serial_number}"
    temp_html = os.path.join(TEMP_DIR, "mac_info.html")
    try:
        runcommand(f"curl --fail --silent {url!r} -o {temp_html}")
    except subprocess.CalledProcessError:
        messagebox.showerror("Error", "Failed to fetch Mac info.")
        return None

    with open(temp_html, "r") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    block = soup.select_one("div.about-your-mac-box")
    if not block:
        #messagebox.showerror("Error", f"Could not find info for serial: {serial}")
        print(f"\033[91mCould not find info (INVALID serial number) for serial: {serial_number}\033[0m")

        return None
    def extract(label):
        el = block.find("span", string=label)
        return el.find_next("span").text if el else ""

    return (
        extract("Processor:"),
        extract("Graphics Card:"),
        extract("Memory:"),
        extract("Storage:")
    )

#def generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud, mdm, config):
def generate_label(serial_number, cpu, gpu, ram, ssd, icloud, mdm, config, model_name):
    html = f"""<!DOCTYPE html>
<html><head><style>
  @page {{ margin: 0mm; size: 4in 1in; }}
  body {{ font-size: 12px; }}
</style></head>
<body><div style='text-align: center;'>
{serial_number} {" iCloud " + icloud if icloud else ""}  {" MDM " + mdm if mdm else ""}
{"<br>" + config if config else ""}
{"<br>" + model_name if model_name else ""}
<br>{cpu} {gpu} {ram} {ssd}
</div></body></html>"""

    html_path = os.path.join(os.path.expanduser("~/Documents"), f"{serial_number}.html")
    pdf_path = os.path.join(os.path.expanduser("~/Documents"), f"{serial_number}.pdf")

    with open(html_path, "w") as f:
        f.write(html)

    runcommand(f"'{CHROME}' --headless --disable-gpu --no-pdf-header-footer --print-to-pdf='{pdf_path}' '{html_path}'")
    run(f"lp -o fit-to-page -o media=Custom.4x1in -p {PRINTER_NAME} '{pdf_path}'", shell=True)
    time.sleep(1)
    #if os.path.exists(pdf_path):
        #os.remove(pdf_path)
    if os.path.exists(html_path):
        os.remove(html_path)

def is_duplicate(key):
    now = time.time()
    last_time = recent_matches.get(key)
    if last_time and now - last_time < DUPLICATE_TIMEOUT:
        return True
    recent_matches[key] = now
    return False

def log_event(message):
    log_file = os.path.join(os.path.expanduser("~/Documents/log.txt"))
    timestamp = datetime.now().strftime("[%a %b %d %H:%M:%S %Y]")
    with open(log_file, "a") as f:
        f.write(f"{timestamp} {message}\n")

def icloudCheck(serial_number):
    import re
    import json

    api_url = f"https://sickw.com/api.php?format=json&key=75K-GL0-CWP-WMG-U3M-NXF-CHH-VHS&imei={serial_number}&service=26"

    # Initialize default values
    icloud = ""
    mdm = ""
    config = ""
    model_name = ""
    response_code = "Unknown"  # Default value for response code

    try:
        # Use curl to fetch the API response and include -w '%{http_code}' to log the status code
        curl_command = f"curl -s -k -w '%{{http_code}}' --connect-timeout 60 --max-time 60 '{api_url}'"
        response = runcommand(curl_command)

        # Separate the HTTP status code from the response content
        response_code = response[-3:]  # Last three characters are the HTTP status code
        response_body = response[:-3]  # All characters before the status code

        # Log the response code
        log_event(f"HTTP Response Code: {response_code}")

        # Parse response JSON
        response_data = json.loads(response_body)

        # Extract raw result HTML from the `result` field
        raw_result = response_data.get("result", "")

        # Extract Model Name using regex search
        model_name_match = re.search(r"Model Name:\s*([^<]+)<br \/>", raw_result)
        if model_name_match:
            model_name = model_name_match.group(1).strip()

        # Extract configurations and other values (if needed)
        config_match = re.search(r"Device Configuration:\s*([^<]+)", raw_result)
        if config_match:
            config = config_match.group(1).strip()

        mdm_match = re.search(r"MDM Lock:\s*<font[^>]*>([^<]+)</font>", raw_result)
        if mdm_match:
            mdm = mdm_match.group(1).strip()

        icloud_match = re.search(r"iCloud Lock:\s*<font[^>]*>([^<]+)</font>", raw_result)
        if icloud_match:
            icloud = icloud_match.group(1).strip()

        # Log the extracted Model Name and other values
        log_event(
            f"Full Check: {serial_number} | Model Name: {model_name} | Config: {config} | Response Code: {response_code}")
        log_event(f"Response: {response_body}")
        messagebox.showinfo("Device Info",
                            f"Model Name: {model_name}\nDevice Configuration: {config}\nMDM Lock: {mdm}\niCloud Lock: {icloud}\nHTTP Response: {response_code}")

    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        log_event(f"IMEI {serial_number} - API call failed with error: {e}")
        messagebox.showerror("Error", f"API call failed for {serial_number}: {e}")

    # Return the extracted information
    return icloud, mdm, config, model_name


def clean_common_ocr_errors(text):
    return (text.replace('I', '1')
                .replace('O', '0'))

def most_common(list):
    return Counter(list).most_common(1)[0][0] if list else None

def extract_matches(texts):
    from re import findall, search
    serials, amodels, emcs = [], [], []
    for t in texts:
        serials.extend(findall(serial_pattern, t))
        if (m := search(amodel_pattern, t)): amodels.append(m.group(0))
        if (e := search(emc_pattern, t)): emcs.append(e.group(1))
    return serials, amodels, emcs

def update_video():
    global feed_frame
    if feed_frame is not None:
        # Convert to RGB, then ImageTk
        img = cv2.cvtColor(feed_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img)
        imgtk = ImageTk.PhotoImage(image=img)

        video_label.imgtk = imgtk
        video_label.config(image=imgtk)
    root.after(80, update_video)


def update_processed_frames():
    global processed_frame_count, frame_queue_length
    # Increment processed frames and get queue size
    frame_queue_length = frame_queue.qsize()
    # Update the UI labels dynamically
    right_label_second_row.config(text=f"Processed Frames: {processed_frame_count}   Frames in Queue: {frame_queue_length}", anchor="e")
    # Schedule the next update (if desired)
    top_frame.after(80, update_processed_frames)  # Update every 100 ms


def main_check(serial_number,bypass):
    global processed_frame_count, serial
    if serial_number:
        if is_duplicate(serial_number):
            return
        serial_number = clean_common_ocr_errors(serial_number)
        print(f"\033[92mFound Serial Number: {serial_number}\033[0m")
        serial = serial_number
        while not frame_queue.empty():
            try:
                frame_queue.get_nowait()  # Remove each item in a thread-safe way
            except Empty:
                break
        processed_frame_count = 0
        right_label_second_row.config(
            text=f"Processed Frames: {processed_frame_count}   Frames in Queue: {frame_queue_length}", anchor="e")
        #if amodel:
        #    amodel = clean_common_ocr_errors(amodel)
        #if emc:
        #    emc = clean_common_ocr_errors(emc)
        print("Checking Spec")
        specs = spec_check(serial_number)
        if specs or bypass:
            cpu, gpu, ram, ssd = specs
            if cpu or bypass:
                print(f"Found CPU: {cpu}")
                if check_type:
                    icloudInfo = icloudCheck(serial_number)
                    if icloudInfo:
                        icloud, mdm, config, model_name = icloudInfo
                        #log_event(f"iCloud MDM Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd} | iCloud: {icloud} | MDM: {mdm} | Config: {config} "
                        log_event(f"iCloud MDM Check: {serial_number} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd} | iCloud: {icloud} | MDM: {mdm} | Config: {config} ")
                else:
                    icloud = None
                    mdm = None
                    config = None
                    model_name = None
                    #log_event(f"Spec Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd}")
                    log_event(f"Spec Check: {serial_number} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd}")
                #generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud, mdm, config)
                generate_label(serial_number, cpu, gpu, ram, ssd, icloud, mdm, config, model_name)
            else:
                print(f"\033[91mCould not find info (VALID serial number) for serial: {serial_number}\033[0m")
                stop_and_review()
        else:
            print(f"\033[91mCould not find info (INVALID serial number) for serial: {serial_number}\033[0m")
            stop_and_review()


def stop_and_review():
    global thread_running
    # Store the previous thread state and stop the thread if it's running
    if thread_running:
        toggle_thread()  # This will stop the thread
    open_manual_window()

def auto_resume_thread():
    global manual_stop
    if stop_event.is_set() and manual_stop is False and (manual_window is None or not manual_window.winfo_exists()):
        stop_ocr_processing_event.clear()
        toggle_thread()
        Thread(target=ocr_processing, daemon=True).start()
        return
    root.after(80, auto_resume_thread)

def ocr_processing():
    print("OCR Processing")
    global thread_running, ocr_mode, serial, processed_frame_count
    while not stop_ocr_processing_event.is_set():
        if stop_event.is_set():
            break
        texts = []
        start_time = time.time()
        frame_queue_length = frame_queue.qsize()
        while time.time() - start_time < scan_interval and frame_queue_length >= 3:
            try:
                processing_frame = frame_queue.get(timeout=1)
                processed_frame_count +=1
            except queue.Empty:
                #print("Queue is empty, exiting loop.")
                break

            #roi = processing_frame[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
            if (ocr_mode == "easyocr"):
                result = reader.readtext(processing_frame, detail=0)
                texts.extend(result)
            else:
                result = pytesseract.image_to_string(processing_frame, lang='eng', config='--psm 1')
                #result = pytesseract.text(processing_frame)
                texts.append(result)

            #print(result)
        if texts:
            print(texts)
        serials, amodels, emcs = extract_matches(texts)
        serial = most_common(serials)
        #serial = "C1MQCSVH0TY3"
        #amodel = most_common(amodels)
        #emc = most_common(emcs)
        #print("checking for serial number")
        if serial:
            main_check(serial,False)
        #time.sleep(0.05)
    #frame_queue.task_done()

def background_task():
    global thread_running, serial, autocrop, feed_frame
    thread_running = True
    update_status()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        number_var.set("Camera Error")
        status_var.set("🔴 Stopped")
        thread_running = False
        return

    roi_w, roi_h = int(300 * 2.5), int(100 * 2.5)  # Rectangle size scaled 2.5x

    while not stop_event.is_set():
        ret, frame = cap.read()
        # Apply flip if the state is active
        if flip_active:
            frame = cv2.flip(frame, -1)
        if not ret:
            number_var.set("Camera Read Fail")
            break
        # Coordinates for cropping (adjust as necessary for your rectangle)
        if autocrop:
            x, y, w, h = 100, 100, 300, 200  # Example rectangle
            final_frame = frame[y:y + h, x:x + w]  # Crop the rectangle
        else:
            final_frame = frame;
        processed_frame = preprocess_for_ocr(final_frame)
        frame_queue.put(processed_frame)  # Put the processed frame into the queue
        feed_frame = frame.copy()
        number_var.set(f"Serial: {serial}")
        status_text_core = "Checking For iCloud and MDM Lock" if check_type else "Checking Spec Only"
        status_text = f"^^^^^^  {status_text_core}  ^^^^^^"
        color = (0, 0, 255) if check_type else (0, 255, 0)

        frame_h, frame_w = feed_frame.shape[:2]

        # Centered top rectangle
        roi_x = (frame_w - roi_w) // 2
        roi_y = 50
        cv2.rectangle(feed_frame, (roi_x, roi_y), (roi_x + roi_w, roi_y + roi_h), (0, 255, 0), 2)

        # Helper to center text
        def center_text_x(text, font, scale, thickness):
            size = cv2.getTextSize(text, font, scale, thickness)[0]
            return int((frame_w - size[0]) / 2)

        # Status with arrows (below rectangle)
        status_scale = 1.0
        status_thickness = 2
        status_x = center_text_x(status_text, cv2.FONT_HERSHEY_SIMPLEX, status_scale, status_thickness)
        status_y = roi_y + roi_h + 40
        cv2.putText(feed_frame, status_text, (status_x, status_y), cv2.FONT_HERSHEY_SIMPLEX, status_scale, color,
                    status_thickness, cv2.LINE_AA)

        time.sleep(0.03)

    cap.release()
    thread_running = False
    status_var.set("🔴 Stopped")


def open_manual_window():
    global serial, manual_window, thread_running
    # If a manual_window already exists, destroy it
    if manual_window is not None and manual_window.winfo_exists():
        manual_window.destroy()

    # Create a new pop-up window
    manual_window = tk.Toplevel(root)
    manual_window.title("Manual Check")

    # Ensure the window appears on top
    manual_window.transient(root)  # Make it a child of the main window
    manual_window.attributes("-topmost", True)  # Always on top

    # Temporarily remove root's topmost setting, so manual_window appears above it
    root.attributes('-topmost', False)

    # Set dimensions and layout
    manual_window.geometry("500x200")
    manual_window.resizable(False, False)

    # Create a label and entry for "Serial" field
    tk.Label(manual_window, text="Serial:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
    serial_entry = tk.Entry(manual_window, width=30)
    serial_entry.grid(row=0, column=1, padx=10, pady=10, sticky="e")
    if serial is not None:
        fill = serial
    else:
        fill = ""
    # Pre-fill the entry field with the current serial
    serial_entry.insert(0, fill)
    # ** Set the focus to serial_entry so the cursor is ready when the window opens **
    serial_entry.focus_set()


    # Function to handle "Check" button click
    def submit_serial():
        global serial
        serial = serial_entry.get()  # Update the global serial value
        main_check(serial,False)  # Call maincheck with the updated serial
        manual_window.destroy()  # Close the window
        root.attributes('-topmost', True)  # Restore root to always be on top
    def submit_serial_bypass():
        global serial
        serial = serial_entry.get()  # Update the global serial value
        main_check(serial,True)  # Call maincheck with the updated serial
        manual_window.destroy()  # Close the window
        root.attributes('-topmost', True)  # Restore root to always be on top
    def on_manual_window_close():
        # Restore root's topmost setting when manual_window is closed
        root.attributes('-topmost', True)
        manual_window.destroy()
    # Bind the close event to ensure root regains topmost
    manual_window.protocol("WM_DELETE_WINDOW", on_manual_window_close)

    # Place the "Check" button
    check_button = tk.Button(manual_window, text="Check", command=submit_serial)
    check_button.grid(row=1, column=1, pady=10, sticky="e")

    # Place the "Bypass Check" button
    check_button_bypass = tk.Button(manual_window, text="Bypass Check", command=submit_serial_bypass)
    check_button_bypass.grid(row=1, column=2, pady=10, sticky="e")

    # Bind the Enter key to the submit_serial function
    manual_window.bind('<Return>', lambda event: submit_serial())


def create_year_window():
    year_window = tk.Toplevel(root)
    year_window.title("Generate Labels by Year")
    year_window.geometry("500x1000")
    year_window.resizable(False, False)

    # Calculate number of years (2010 to 2025)
    years = list(range(2010, 2026))
    total_years = len(years)

    # Create frame for buttons
    button_frame = tk.Frame(year_window)
    button_frame.pack(expand=True, fill='both', padx=20, pady=20)

    # Configure grid with 2 columns
    button_frame.grid_columnconfigure(0, weight=1)
    button_frame.grid_columnconfigure(1, weight=1)

    # Create buttons for each year
    for i, year in enumerate(years):
        row = i // 2  # Integer division to determine row
        col = i % 2  # Remainder to determine column (0 or 1)

        # Create button with specific year model
        btn = tk.Button(
            button_frame,
            text=f"MacBook Pro {year}",
            width=20,
            height=2,
            command=lambda y=year: generate_label(None, None, None, None, None, None, None, None, f"MacBook Pro {y}")
        )
        btn.grid(row=row, column=col, padx=10, pady=5, sticky="nsew")


def toggle_flip():
    global flip_active
    flip_active = not flip_active
    # Update the button text based on the flip state
    flip_button.config(text="FLIP ON" if flip_active else "FLIP OFF")








# GUI Setup
root = tk.Tk()
root.title("Meepo Auto Serial Number Scan System")
root.geometry("800x600")
root.configure(bg="#2e3b4e")
root.attributes('-topmost', True)
root.after(1, root.lift)

status_var = tk.StringVar(value="🔴 Stopped")
number_var = tk.StringVar(value="")
mode_var = tk.StringVar(value="Mode: Basic")

# ---- Top Row ----
top_frame = tk.Frame(root, bg="#2e3b4e")
top_frame.pack(pady=10, fill='x')

mode_label = tk.Label(top_frame, textvariable=mode_var, font=("Helvetica", 16, "bold"), fg="green", bg="#2e3b4e")
mode_label.pack(side="left", padx=(20, 10))

status_label = tk.Label(top_frame, textvariable=status_var, font=("Helvetica", 16), fg="green", bg="#2e3b4e")
status_label.pack(side="left", padx=10)

# ---- Serial Display ----
number_label = tk.Label(root, textvariable=number_var, font=("Helvetica", 28, "bold"), fg="green", bg="#2e3b4e")
number_label.pack(pady=5)

right_label_second_row = Label(top_frame, text=f"Processed Frames: {processed_frame_count}   Frames in Queue: {frame_queue_length}", anchor="e")
right_label_second_row.pack(anchor="e")

# ---- Button Row ----
button_frame = tk.Frame(root, bg="#2e3b4e")
button_frame.pack(pady=10)

mode_button = tk.Button(button_frame, text="Change Mode", width=12, command=toggle_mode,
                        bg="black", fg="green", font=("Helvetica", 12, "bold"))
mode_button.pack(side="left", padx=10)

start_button = tk.Button(button_frame, text="Start", width=10, command=toggle_thread,
                         bg="black", fg="green", font=("Helvetica", 12, "bold"))
start_button.pack(side="left", padx=10)

manual_button = tk.Button(button_frame, text="Manual", command=open_manual_window)
manual_button.pack(side="left", padx=10)


# Create a button for toggling flip
flip_button = tk.Button(button_frame, text="FLIP OFF", command=toggle_flip, width=10)
flip_button.pack(side="left", padx=10)


# ---- Video Display ----
video_label = tk.Label(root, bg="#2e3b4e")
video_label.pack(pady=10)

# Bind spacebar
root.bind('<space>', on_spacebar)
# Bind the Down Arrow key to open the manual window
root.bind('<Down>', lambda event: open_manual_window())

###
update_processed_frames()
#create_year_window()

# Start OCR background thread
stop_ocr_processing_event.clear()
Thread(target=ocr_processing, daemon=True).start()
#autostart
if autostart:
    toggle_thread()

#image_path = "/Users/meeposcan/Desktop/s234.jpg"  # Replace <your-username> with your system username
#image = cv2.imread(image_path)
#if image is not None:
#    time.sleep(1)
#    print(f"Image loaded successfully: {image_path}")
#    frame_queue.put(image)  # Add the image to the frame queue


# Start GUI video update loop
auto_resume_thread()
update_video()
root.mainloop()


