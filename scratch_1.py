import os
import subprocess
import tempfile
import time
import datetime
import tkinter as tk
import cv2
import pytesseract
import re
import numpy as np
from datetime import datetime

from tkinter import messagebox
from tkinter import simpledialog
from bs4 import BeautifulSoup

# Prompt user for check type
root = tk.Tk()
root.withdraw()
check_type = messagebox.askquestion("Choose check type", "Do you want a Full Info Check?", icon='question')
is_full_check = (check_type == 'yes')

# Global paths
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PRINTER_NAME = "Arkscan-2054K-LAN"
TEMP_DIR = tempfile.gettempdir()

# Regex patterns
serial_pattern = re.compile(r'\b[A-Z0-9]{10,12}\b')
model_pattern = re.compile(r'\bA\d{4}\b')
emc_pattern = re.compile(r'\bEMC\s(\d{4})\b')

# Script path and log file
SCRIPT_PATH = "/path/to/handle_serial.scpt"
LOG_FILE = "ocr_matches.log"

# Time to wait before allowing the same match again (in seconds)
DUPLICATE_TIMEOUT = 10
recent_matches = {}


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


def is_duplicate(key):
    now = time.time()
    last_time = recent_matches.get(key)
    if last_time and now - last_time < DUPLICATE_TIMEOUT:
        return True
    recent_matches[key] = now
    return False


def log_match(serial, model, emc):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] Serial: {serial} | Model: {model or 'N/A'} | EMC: {emc or 'N/A'}\n")


def handle_match(serial, model, emc):
    key = f"{serial}|{model}|{emc}"
    if is_duplicate(key):
        return
    print(f"[INFO] Serial: {serial} | Model: {model or 'N/A'} | EMC: {emc or 'N/A'}")
    log_match(serial, model, emc)
    args = [arg for arg in [serial, model, emc] if arg]
    subprocess.run(["osascript", SCRIPT_PATH] + args)
    time.sleep(1)  # small buffer to avoid multi-triggers


######

def run(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()


def find_serial():
    while True:
        photo_path = os.path.join(TEMP_DIR, f"photo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        run(f"/usr/local/bin/imagesnap -q {photo_path}")
        time.sleep(3)
        try:
            raw_text = run(f"{TESSERACT} {photo_path} stdout")
            serial = run(
                f"echo {raw_text!r} | tr '[:lower:]' '[:upper:]' | grep -Eo '\\b[A-Z0-9]{{10,12}}\\b' | head -n 1")
            if serial:
                amodel = run(f"echo {raw_text!r} | grep -Eo '\\bA[0-9]{{4}}\\b' | head -n 1")
                emc = run(
                    f"echo {raw_text!r} | tr -d '\\n' | grep -oE 'EMC[^0-9]*([0-9]{{4}})' | grep -oE '[0-9]{{4}}' | head -n 1")
                return serial, amodel, emc
        except subprocess.CalledProcessError:
            continue


def spec_check(serial):
    url = f"https://macfinder.co.uk/model/macbook-pro-15-inch-2018/?serial={serial}"
    temp_html = os.path.join(TEMP_DIR, "mac_info.html")
    try:
        run(f"curl --fail --silent {url!r} -o {temp_html}")
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
        el = block.find("span", text=label)
        return el.find_next("span").text if el else ""

    return (
        extract("Processor:"),
        extract("Graphics Card:"),
        extract("Memory:"),
        extract("Storage:")
    )


def generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud="", mdm="", config=""):
    html = f"""<!DOCTYPE html>
<html><head><style>
  @page {{ margin: 0mm; size: 4in 1in; }}
  body {{ font-size: 12px; }}
</style></head>
<body><div style='text-align: center;'>
{serial} {amodel} {emc}{" iCloud " + icloud + " MDM " + mdm if icloud or mdm else ""}
<br>{config}<br>{cpu} {gpu} {ram} {ssd}
</div></body></html>"""

    html_path = os.path.join(os.path.expanduser("~/Documents"), f"{serial}.html")
    pdf_path = os.path.join(os.path.expanduser("~/Documents"), f"{serial}.pdf")

    with open(html_path, "w") as f:
        f.write(html)

    run(f"'{CHROME}' --headless --disable-gpu --no-pdf-header-footer --print-to-pdf='{pdf_path}' '{html_path}'")
    run(f"sleep 2 && lpr -o fit-to-page -o media=Custom.4x1in '{pdf_path}' -P {PRINTER_NAME}")


def log_event(message):
    log_file = os.path.join(TEMP_DIR, "log.txt")
    timestamp = datetime.datetime.now().strftime("[%a %b %d %H:%M:%S %Y]")
    with open(log_file, "a") as f:
        f.write(f"{timestamp} {message}\n")


def full_check_flow(serial, amodel, emc, cpu, gpu, ram, ssd):
    api_url = f"https://sickw.com/api.php?format=json&key=75K-GL0-CWP-WMG-U3M-NXF-CHH-VHS&imei={serial}&service=72"
    try:
        response = run(f"curl -s -k --connect-timeout 60 --max-time 60 '{api_url}'")
        raw_result = run(f"echo {response!r} | /opt/homebrew/bin/jq -r .result")
        config = run(f"echo {raw_result!r} | grep -oE 'Device Configuration: [^<]+' | sed 's/Device Configuration: //'")
        mdm = run(f"echo {raw_result!r} | grep -oE 'MDM Lock: <font[^>]*>[^<]+' | sed -E 's/.*>([^<]+)$/\\1/'")
        icloud = run(f"echo {raw_result!r} | grep -oE 'iCloud Lock: <font[^>]*>[^<]+' | sed -E 's/.*>([^<]+)$/\\1/'")

        log_event(f"Full Check: {serial} | Config: {config}")
        log_event(f"Response: {response}")
        messagebox.showinfo("Device Info", f"Device Configuration: {config}\nMDM Lock: {mdm}\niCloud Lock: {icloud}")
        generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud, mdm, config)
    except subprocess.CalledProcessError:
        log_event(f"IMEI {serial} - API call failed.")
        messagebox.showerror("Error", f"API call failed for {serial}")


# MAIN LOGIC

# Start video
cap = cv2.VideoCapture(0)
print("[INFO] Scanning... Press 'q' to quit.")

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        processed = preprocess_for_ocr(frame)
        text = pytesseract.image_to_string(processed).upper()

        serials = serial_pattern.findall(text)
        model_match = model_pattern.search(text)
        emc_match = emc_pattern.search(text)

        model = model_match.group(0) if model_match else None
        emc = emc_match.group(1) if emc_match else None

        for serial in serials:
            handle_match(serial, model, emc)

        cv2.imshow("OCR Camera Feed", processed)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
    print("[INFO] Camera feed closed.")

serial, amodel, emc = find_serial()
specs = spec_check(serial)
if specs:
    cpu, gpu, ram, ssd = specs
    messagebox.showinfo("Basic Info",
                        f"Serial: {serial}\nAmodel: {amodel}\nEMC: {emc}\nCPU: {cpu}\nGPU: {gpu}\nRAM: {ram}\nSSD: {ssd}")
    if is_full_check:
        full_check_flow(serial, amodel, emc, cpu, gpu, ram, ssd)
    else:
        log_event(
            f"Basic Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd}")
        generate_label(serial, amodel, emc, cpu, gpu, ram, ssd)