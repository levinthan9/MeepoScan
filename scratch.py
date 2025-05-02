import os
import subprocess
import tempfile
import time
import queue
import datetime
import cv2
import pytesseract
import re
import numpy as np
import easyocr
from datetime import datetime
from threading import Thread
from queue import Queue
import tkinter as tk
from tkinter import messagebox
from tkinter import simpledialog
from bs4 import BeautifulSoup
from subprocess import run
from collections import Counter

# Prompt user for check type
check_type = messagebox.askquestion("Choose check type", "Do you want to check for iCloud & MDM lock?", icon='question')
is_full_check = (check_type == 'yes')


# Global paths
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PRINTER_NAME = "Arkscan-2054K-LAN"
TEMP_DIR = tempfile.gettempdir()

# Regex patterns
serial_pattern = re.compile(r'\b[A-Z0-9]{10,12}\b')
#serial_pattern = re.compile(r'\bSerial[:\s\-]*([A-Z0-9]{10,12})\b')
amodel_pattern = re.compile(r'\bA\d{4}\b')
emc_pattern = re.compile(r'\bEMC\s(\d{4})\b')

# Script path and log file
SCRIPT_PATH = "/path/to/handle_serial.scpt"
LOG_FILE = "ocr_matches.log"

# Time to wait before allowing the same match again (in seconds)
DUPLICATE_TIMEOUT = 10
recent_matches = {}

# Initialize EasyOCR reader
reader = easyocr.Reader(['en'])

# Frame skip rate
PROCESS_EVERY = 2
frame_count = 0

# ROI bounds (adjust as needed)
roi_x, roi_y, roi_w, roi_h = 600, 100, 800, 300  # crop area

#  queue
frame_queue = Queue()
ui_queue = queue.Queue()

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

def ocr_worker():
    while True:
        texts = []
        start_time = time.time()
        while time.time() - start_time < 5:
            frame = frame_queue.get()
            roi = frame[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
            result = reader.readtext(roi, detail=0)
            texts.extend(result)
        serials, amodels, emcs = extract_matches(texts)
        serial = most_common(serials)
        amodel = most_common(amodels)
        emc = most_common(emcs)

        if serial:
            serial = clean_common_ocr_errors(serial)
            if amodel:
                amodel = clean_common_ocr_errors(amodel)
            if emc:
                emc = clean_common_ocr_errors(emc)
            specs = spec_check(serial)
            if specs:
                cpu, gpu, ram, ssd = specs
                if cpu:
                    if is_full_check:
                        icloudInfo = icloudCheck(serial)
                        if icloudInfo:
                            icloud, mdm, config = icloudInfo
                            log_event(f"iCloud MDM Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd} | iCloud: {icloud} | MDM: {mdm} | Config: {config} ")
                    else:
                        icloud = None
                        mdm = None
                        config = None
                        log_event(f"Spec Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd}")
                    generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud, mdm, config)
                #else:
                    #ui_queue.put(("edit_fields", serial, amodel, emc))
    frame_queue.task_done()

# Start OCR background thread
Thread(target=ocr_worker, daemon=True).start()

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

def preprocess_for_ocr(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharp = sharpen(gray)
    contrast = enhance_contrast(sharp)
    binary = binarize(contrast)
    return binary

def clean_common_ocr_errors(text):
    return (text.replace('I', '1')
                .replace('O', '0'))

def log_match(serial, model, emc):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] Serial: {serial} | Model: {model or 'N/A'} | EMC: {emc or 'N/A'}\n")

######


def runcommand(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

def spec_check(serial):
    url = f"https://macfinder.co.uk/model/macbook-pro-15-inch-2018/?serial={serial}"
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
        messagebox.showerror("Error", f"Could not find info for serial: {serial}")
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
def generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud, mdm, config):
    html = f"""<!DOCTYPE html>
<html><head><style>
  @page {{ margin: 0mm; size: 4in 1in; }}
  body {{ font-size: 12px; }}
</style></head>
<body><div style='text-align: center;'>
{serial} {amodel} {emc}{" iCloud " + icloud + " MDM " + mdm if icloud or mdm else ""}
{"<br>" + config if icloud or mdm else ""}
<br>{cpu} {gpu} {ram} {ssd}
</div></body></html>"""

    html_path = os.path.join(os.path.expanduser("~/Documents"), f"{serial}.html")
    pdf_path = os.path.join(os.path.expanduser("~/Documents"), f"{serial}.pdf")

    with open(html_path, "w") as f:
        f.write(html)

    runcommand(f"'{CHROME}' --headless --disable-gpu --no-pdf-header-footer --print-to-pdf='{pdf_path}' '{html_path}'")
    run(f"lpr -o fit-to-page -o media=Custom.4x1in -p {PRINTER_NAME} '{pdf_path}'", shell=True)


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

def icloudCheck(serial):
    api_url = f"https://sickw.com/api.php?format=json&key=75K-GL0-CWP-WMG-U3M-NXF-CHH-VHS&imei={serial}&service=72"
    try:
        response = runcommand(f"curl -s -k --connect-timeout 60 --max-time 60 '{api_url}'")
        raw_result = runcommand(f"echo {response!r} | /opt/homebrew/bin/jq -r .result")
        config = runcommand(f"echo {raw_result!r} | grep -oE 'Device Configuration: [^<]+' | sed 's/Device Configuration: //'")
        mdm = runcommand(f"echo {raw_result!r} | grep -oE 'MDM Lock: <font[^>]*>[^<]+' | sed -E 's/.*>([^<]+)$/\\1/'")
        icloud = runcommand(f"echo {raw_result!r} | grep -oE 'iCloud Lock: <font[^>]*>[^<]+' | sed -E 's/.*>([^<]+)$/\\1/'")

        log_event(f"Full Check: {serial} | Config: {config}")
        log_event(f"Response: {response}")
        messagebox.showinfo("Device Info", f"Device Configuration: {config}\nMDM Lock: {mdm}\niCloud Lock: {icloud}")

    except subprocess.CalledProcessError:
        log_event(f"IMEI {serial} - API call failed.")
        messagebox.showerror("Error", f"API call failed for {serial}")
    return(icloud,mdm,config)


# MAIN LOGIC
# Start video
cap = cv2.VideoCapture(0)
print("[INFO] Scanning... Press 'q' to quit.")
tempSerial = ""
serial=""
try:
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        frame_count += 1
        if frame_count % PROCESS_EVERY == 0:
            processed = preprocess_for_ocr(frame)
            frame_queue.put(frame.copy())
        # Show ROI for feedback
        roi_frame = frame.copy()
        cv2.rectangle(roi_frame, (roi_x, roi_y), (roi_x + roi_w, roi_y + roi_h), (0, 255, 0), 2)

        #y_offset = 200  # Starting y position

        if is_full_check:
            cv2.putText(roi_frame, f"^^^^^ Checking For iCloud and MDM Lock ^^^^^", (600, 500),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 1, cv2.LINE_AA)
        else:
            cv2.putText(roi_frame, f"^^^^^ Checking Spec Only ^^^^^", (600, 500),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.putText(roi_frame, serial, (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.imshow("Live OCR Scanner", roi_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    cap.release()
    cv2.destroyAllWindows()
    print("[INFO] Camera feed closed.")