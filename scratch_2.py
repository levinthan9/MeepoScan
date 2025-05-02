import cv2
import datetime
import easyocr
import numpy as np
import os
import pytesseract
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
from queue import Queue
from subprocess import run
from threading import Thread
from threading import Thread, Event
from tkinter import messagebox
from tkinter import simpledialog

stop_event = Event()
thread_running = False
blink_state = False
check_type = False  # False = Basic, True = iCloud-MDM

status_var = None
number_var = None
mode_var = None
current_frame = None  # Shared between threads

# Create a queue to hold processed frames
ocr_queue = queue.Queue()
# Create a flag to toggle between Original and Processed frames
use_processed_frame = False  # Default is original frame

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
    if thread_running:
        stop_event.set()
        start_button.config(text="Start")
    else:
        stop_event.clear()
        Thread(target=background_task, daemon=True).start()
        start_button.config(text="Stop")

def toggle_frame():
    global use_processed_frame
    use_processed_frame = not use_processed_frame
    toggle_button.config(text="Use Processed Frame" if not use_processed_frame else "Use Original Frame")

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
    toggle_thread()


def update_video():
    global current_frame
    if current_frame is not None:
        # Convert to RGB, then ImageTk
        img = cv2.cvtColor(current_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img)
        imgtk = ImageTk.PhotoImage(image=img)

        video_label.imgtk = imgtk
        video_label.config(image=imgtk)

    root.after(10, update_video)


def capture_and_process_frame():
    global use_processed_frame

    # Coordinates for cropping (adjust as necessary for your rectangle)
    x, y, w, h = 100, 100, 300, 200  # Example rectangle

    ret, frame = cap.read()  # Capture frame
    if not ret:
        return

    cropped_frame = frame[y:y+h, x:x+w]  # Crop the rectangle

    # If processed frame is selected, preprocess the frame
    if use_processed_frame:
        processed_frame = preprocess_for_ocr(cropped_frame)
        ocr_queue.put(processed_frame)  # Put the processed frame into the queue
    else:
        ocr_queue.put(cropped_frame)  # Put the original frame into the queue

    # Call this function again after 1 second
    root.after(1000, capture_and_process_frame)


# Call capture_and_process_frames when the process starts

def background_task():
    global thread_running, current_frame
    thread_running = True
    update_status()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        number_var.set("Camera Error")
        status_var.set("🔴 Stopped")
        thread_running = False
        return

    serial = "C02XXXXXXXY0"
    roi_w, roi_h = int(300 * 2.5), int(100 * 2.5)  # Rectangle size scaled 2.5x

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            number_var.set("Camera Read Fail")
            break

        number_var.set(f"Serial: {serial}")
        status_text_core = "Checking For iCloud and MDM Lock" if check_type else "Checking Spec Only"
        status_text = f"^^^^^^  {status_text_core}  ^^^^^^"
        color = (0, 0, 255) if check_type else (0, 255, 0)

        frame_h, frame_w = frame.shape[:2]

        # Centered top rectangle
        roi_x = (frame_w - roi_w) // 2
        roi_y = 50
        cv2.rectangle(frame, (roi_x, roi_y), (roi_x + roi_w, roi_y + roi_h), (0, 255, 0), 2)

        # Helper to center text
        def center_text_x(text, font, scale, thickness):
            size = cv2.getTextSize(text, font, scale, thickness)[0]
            return int((frame_w - size[0]) / 2)

        # Status with arrows (below rectangle)
        status_scale = 1.0
        status_thickness = 2
        status_x = center_text_x(status_text, cv2.FONT_HERSHEY_SIMPLEX, status_scale, status_thickness)
        status_y = roi_y + roi_h + 40
        cv2.putText(frame, status_text, (status_x, status_y), cv2.FONT_HERSHEY_SIMPLEX, status_scale, color,
                    status_thickness, cv2.LINE_AA)

        # Serial number (below status line)
        serial_scale = 1.5
        serial_thickness = 2
        serial_x = center_text_x(serial, cv2.FONT_HERSHEY_SIMPLEX, serial_scale, serial_thickness)
        serial_y = status_y + 50
        cv2.putText(frame, serial, (serial_x, serial_y), cv2.FONT_HERSHEY_SIMPLEX, serial_scale, (255, 255, 0),
                    serial_thickness, cv2.LINE_AA)

        current_frame = frame.copy()
        time.sleep(0.03)

    cap.release()
    thread_running = False
    status_var.set("🔴 Stopped")


# GUI Setup
root = tk.Tk()
root.title("Meepo Auto Serial Number Scan System")
root.geometry("800x600")
root.configure(bg="#2e3b4e")
root.attributes('-topmost', True)
root.after(1, root.lift)

status_var = tk.StringVar(value="🔴 Stopped")
number_var = tk.StringVar(value="Number: ---")
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

# ---- Button Row ----
button_frame = tk.Frame(root, bg="#2e3b4e")
button_frame.pack(pady=10)

mode_button = tk.Button(button_frame, text="Change Mode", width=12, command=toggle_mode,
                        bg="black", fg="green", font=("Helvetica", 12, "bold"))
mode_button.pack(side="left", padx=10)

start_button = tk.Button(button_frame, text="Start", width=10, command=toggle_thread,
                         bg="black", fg="green", font=("Helvetica", 12, "bold"))
start_button.pack(side="left", padx=10)

toggle_button = tk.Button(button_frame, text="Use Processed Frame", command=toggle_frame, bg="black", fg="green", font=("Helvetica", 12, "bold"))
toggle_button.pack(side='left', padx=10, pady=10)  # Align button to the left

# ---- Video Display ----
video_label = tk.Label(root, bg="#2e3b4e")
video_label.pack(pady=10)

# Bind spacebar
root.bind('<space>', on_spacebar)

# Start GUI video update loop
update_video()

root.mainloop()

