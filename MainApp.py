# =============================================
# Standard Library Imports
# =============================================

# Date and time handling utilities
import datetime
from datetime import datetime  # Direct datetime class import for easier access

# File system and OS operations
import os  # Operating system interface for file/path operations
import tempfile  # For creating temporary files and directories
import sys

# Threading and Queue management
import threading  # Base threading module
from threading import Thread, Event  # Specific threading components
import queue  # Base queue module
from queue import Queue, Empty  # Queue implementation for thread-safe data exchange

# String and process handling
import re  # Regular expression operations
import subprocess  # Spawn and manage subprocesses
from subprocess import run  # Direct subprocess.run import
import logging

# System and debugging
import gc  # Garbage collector interface
import time  # Time-related functions
import traceback  # Stack trace management
import tracemalloc  # Memory allocation tracking
import csv  # CSV file reading and writing

# =============================================
# GUI and Image Processing
# =============================================

# Tkinter GUI framework
import tkinter as tk  # Main tkinter module
from tkinter import (
    messagebox,  # Popup message boxes
    Label,       # Label widget
    Frame,       # Frame container widget
    simpledialog # Simple dialog windows
)

# Image processing libraries
from PIL import Image, ImageTk  # Python Imaging Library for image processing
import cv2  # OpenCV for computer vision and image processing

# =============================================
# MacOS Specific Imports
# =============================================

# Core MacOS frameworks
import Cocoa  # macOS Cocoa framework for native UI
  # Core Graphics and QuartzCore frameworks
from Foundation import NSData  # Foundation framework for data handling

# Quartz specific components for image processing
from Quartz import *  # Import all from the Quartz framework.

#from pyobjc_framework import Quartz  # Import Quartz
#import Quartz

# Vision framework for text recognition
import Vision  # Main Vision framework
from Vision import (
    VNImageRequestHandler,          # Handles image analysis requests
    VNRecognizeTextRequest,         # Text recognition request
    VNRecognizeTextRequestRevision3 # Latest text recognition revision
)
import io
from PIL import Image


# =============================================
# Web and Data Processing
# =============================================

# Web requests and parsing
import requests  # HTTP library for making requests
from bs4 import BeautifulSoup  # HTML/XML parsing library

# Data structures and analysis
from collections import Counter  # Container for counting hashable objects

# =============================================
# Performance Monitoring
# =============================================

# System and memory monitoring
import psutil  # Process and system utilities
from memory_profiler import profile  # Memory usage profiling decorator

#import CoreVideo
import ctypes
import numpy as np


# Note: The order of imports can affect functionality in some cases.
# System-level imports are listed first, followed by third-party packages,
# and finally application-specific imports.


############
##MAIN APP##
############
class MainApp:
    def __init__(self):
        try:
            # Configure logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler('app.log'),
                    logging.StreamHandler(sys.stdout)
                ]
            )

            # Initialize main window
            self.tk = tk.Tk()
            self.tk.title("Meepo Auto Serial Number Scan System BETA")
            self.tk.protocol("WM_DELETE_WINDOW", self.on_closing)
            self.tk.geometry("1600x1100")
            self.tk.configure(bg="#2e3b4e")
            self.tk.attributes('-topmost', True)
            self.tk.after(100, self.tk.lift)

            # Initialize variables
            self.setup_variables()

            # Start memory tracking
            tracemalloc.start()
            self.last_memory_snapshot = tracemalloc.take_snapshot()

            # Add memory monitoring method
            self.start_monitoring()

            # Create UI elements
            self.create_ui()

            # autostart
            if self.autostart:
                self.toggle_thread()

            self.update_processed_frames()


            # Start GUI video update loop
            self.auto_resume_thread()
            self.update_video()




        except Exception as e:
            logging.error(f"Initialization error: {str(e)}")
            logging.error(traceback.format_exc())
            messagebox.showerror("Initialization Error",
                                 f"Failed to initialize application: {str(e)}\n"
                                 "Check app.log for details")
            sys.exit(1)

    def setup_variables(self):
        """Initialize all instance variables"""

        # Initialize counters and queues
        self.processed_frame_count = 0
        self.stop_ocr_processing_event = threading.Event()
        self.frame_queue = Queue(maxsize=10)  # Limit queue size

        # Initialize data structures
        self.recent_matches = {}
        self.last4 = set()
        self.main_check_lock = threading.Lock()
        self.duplicate_timeout = 120  # seconds
        self.feed_frame_zoom_in = None
        self.feed_frame_zoom_out = None
        self.serial = None
        self.total_serials_processing_limit = 5

        # Initialize configuration
        self.autostart = True
        self.autocrop = False
        self.zoom_in_factor = 1
        self.zoom_out_factor = 0.5
        self.flip_active = True
        self.manual_stop = False
        self.manual_window = None


        # Initialize Regex patterns
        self.serial_pattern = re.compile(r'\b[A-Z0-9]{10,12}\b')
        # self.serial_pattern = re.compile(r'\bSerial[:\s\-]*([A-Z0-9]{10,12})\b')
        self.amodel_pattern = re.compile(r'\bA\d{4}\b')
        self.emc_pattern = re.compile(r'\bEMC\s(\d{4})\b')

        # ---- Video Display ----
        # Create a frame to hold both video labels
        bottom_frame = tk.Frame(self.tk, bg="#2e3b4e")
        bottom_frame.pack(side='bottom', fill='x', pady=5)

        # Configure the zoom_in_video_label (placed on the left of the bottom row)
        self.zoom_in_video_label = tk.Label(bottom_frame, bg="#2e3b4e", text="Zoom In Video")
        self.zoom_in_video_label.pack(side='left', padx=5)

        # Configure the zoom_out_video_label (placed on the right of the bottom row)
        self.zoom_out_video_label = tk.Label(bottom_frame, bg="#2e3b4e", text="Zoom Out Video")
        self.zoom_out_video_label.pack(side='right', padx=5)

        # Initialize thread control variables
        self.stop_event = threading.Event()
        self.thread_running = False
        self.stop_ocr_processing_event = threading.Event()

        # Initialize state variables
        self.blink_state = False
        self.check_type = False
        self.flip_active = True

        # Initialize UI variables
        self.status_var = tk.StringVar(value="Ready")
        self.number_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="Mode: Basic")
        self.start_button = None
        self.flip_button = None
        self.right_label_second_row = None

        #Printing and path
        self.chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        self.printer_name = "4BARCODE"
        # Define a default output directory
        default_output_dir = "~/Documents"
        # Use default or context-specific output_dir
        output_dir = default_output_dir  # Could be overridden dynamically if needed
        self.output_dir = os.path.expanduser(output_dir)  # Resolve '~' to full path
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.temp_dir = tempfile.gettempdir()
        self.csv_filepath="last4.csv"

    def log_memory_usage(self,stage):
        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss / (1024 * 1024)  # Convert to MB
        print(f"[{stage}] Memory usage: {mem:.2f} MB")

    def start_monitoring(self):
        def monitor_resources():
            while not self.stop_event.is_set():
                # Get process info
                process = psutil.Process(os.getpid())

                # Memory usage
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024

                # CPU usage
                cpu_percent = process.cpu_percent()

                # Current memory snapshot and comparison
                current_snapshot = tracemalloc.take_snapshot()
                stats = current_snapshot.compare_to(self.last_memory_snapshot, 'lineno')

                # Log significant memory changes
                if memory_mb > 500:  # Alert if using more than 500MB
                    #print(f"\nHIGH MEMORY USAGE ALERT:")
                    #print(f"Memory Usage: {memory_mb:.2f} MB")
                    #print(f"CPU Usage: {cpu_percent}%")
                    #print("\nTop 1 memory changes:")
                    #for stat in stats[:1]:
                        #print(stat)

                    # Force garbage collection
                    gc.collect()

                self.last_memory_snapshot = current_snapshot
                time.sleep(10)  # Check every 5 seconds

        # Start monitoring in a separate thread
        import threading
        self.monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
        self.monitor_thread.start()

    def create_ui(self):
        """Create all UI elements"""
        try:
            # Bind spacebar
            self.tk.bind('<space>', self.on_spacebar)
            # Bind the Down Arrow key to open the Manual Window
            self.tk.bind('<Down>', lambda event: self.open_manual_window())

            # Manual Window
            self.manual_window = None
            self.manual_stop = False

            # ---- Top Row ----
            top_frame = tk.Frame(self.tk, bg="#2e3b4e")
            top_frame.pack(side='top', pady=10, fill='x')

            self.mode_label = tk.Label(
                top_frame,
                textvariable=self.mode_var,
                font=("Helvetica", 16, "bold"),
                fg="green",
                bg="#2e3b4e"
            )
            self.mode_label.pack(side="left", padx=(20, 10))

            self.status_label = tk.Label(
                top_frame,
                textvariable=self.status_var,
                font=("Helvetica", 16),
                fg="green",
                bg="#2e3b4e"
            )
            self.status_label.pack(side="left", padx=10)

            # ---- Serial Display ----
            self.number_label = tk.Label(
                self.tk,
                textvariable=self.number_var,
                font=("Helvetica", 28, "bold"),
                fg="green",
                bg="#2e3b4e"
            )
            self.number_label.pack(pady=5)

            self.right_label_second_row = tk.Label(
                top_frame,
                text=(
                    f"Processed Frames: {self.processed_frame_count}   "
                    f"Frames in Queue: {self.frame_queue.qsize()}"
                ),
                anchor="e"
            )
            self.right_label_second_row.pack(anchor="e")

            # ---- Button Row ----
            button_frame = tk.Frame(self.tk, bg="#2e3b4e")
            button_frame.pack(pady=10)

            self.mode_button = tk.Button(
                button_frame,
                text="Change Mode",
                width=12,
                command=self.toggle_mode,
                bg="black",
                fg="green",
                font=("Helvetica", 12, "bold")
            )
            self.mode_button.pack(side="left", padx=10)

            self.start_button = tk.Button(
                button_frame,
                text="Start",
                width=10,
                command=self.toggle_thread,
                bg="black",
                fg="green",
                font=("Helvetica", 12, "bold")
            )
            self.start_button.pack(side="left", padx=10)

            self.manual_button = tk.Button(
                button_frame,
                text="Manual",
                command=self.open_manual_window
            )
            self.manual_button.pack(side="left", padx=10)

            self.flip_button = tk.Button(
                button_frame,
                text="FLIP OFF",
                command=self.toggle_flip,
                width=10
            )
            self.flip_button.pack(side="left", padx=10)


        except Exception as e:
            logging.error(f"UI creation error: {str(e)}")
            logging.error(traceback.format_exc())
            raise

    def resize_for_ocr(self, image, factor):
        """
        Resize the given image for OCR processing using a preset factor.

        Parameters:
        - image: Input image to resize
        Returns:
        - Resized image
        """
        try:
            return cv2.resize(
                image,
                None,
                fx=factor,
                fy=factor,
                interpolation=cv2.INTER_CUBIC
            )
        except Exception as e:
            logging.error(f"Failed to resize image for OCR: {e}")
            raise


    def print_frame_queue(self):
        """Prints the contents of the frame_queue without modifying its state."""
        #print(f"Debug: Frame queue size: {self.frame_queue.qsize()}")
        contents = []
        try:
            # Transfer all items temporarily to a list for inspection
            while not self.frame_queue.empty():
                item = self.frame_queue.get()
                contents.append(item)
                print(f"Debug: Frame in queue - {type(item)}, Shape: {item.shape if hasattr(item, 'shape') else 'N/A'}")

            # Re-add items back to the Queue to maintain its state
            for item in contents:
                self.frame_queue.put(item)

        except Exception as e:
            logging.error(f"Error during queue debugging: {str(e)}")
            print(f"Error during queue debugging: {str(e)}")


    def update_status(self):
        """
        Update the status text in the UI with a blinking effect based on blink_state.

        This method changes the `status_var` text and schedules the `blink_status`
        method to run every 500 milliseconds.
        """
        try:
            if self.blink_state:
                self.status_var.set("🟢 Running")
            else:
                self.status_var.set("⚪ Running")

            # Schedule the blink_status to be called after 500 milliseconds
            self.tk.after(500, self.blink_status)
        except Exception as e:
            logging.error(f"Error while updating status: {e}")
            raise

    def blink_status(self):
        """
        Toggle the blink state and update the status if the thread is running.
        """
        try:
            # Toggle the blink_state
            self.blink_state = not self.blink_state

            # If the thread is running, update the status
            if self.thread_running:
                self.update_status()
        except Exception as e:
            logging.error(f"Error while toggling blink status: {e}")
            raise

    def toggle_thread(self):
        """
        Toggle the background thread(s) for OCR processing and related tasks.
        Starts the threads if they are not running and stops them if they are active.
        """
        try:
            if self.thread_running:
                # Stop the threads
                self.stop_event.set()
                self.stop_ocr_processing_event.set()

                # Reset processed frame count
                self.processed_frame_count = 0

                # Clear the frame queue
                while not self.frame_queue.empty():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        break

                # Update UI
                self.start_button.config(text="Start")
                self.thread_running = False  # Mark thread as stopped
            else:
                # Start the threads
                self.stop_event.clear()
                self.stop_ocr_processing_event.clear()

                # Mark threads as running
                self.thread_running = True
                # Start background threads
                print("Thread starting")
                Thread(target=self.background_task, daemon=True).start()
                Thread(target=self.ocr_processing, daemon=True).start()

                # Update UI
                self.start_button.config(text="Stop")
        except Exception as e:
            logging.error(f"Error while toggling thread: {e}")
            raise

    def toggle_mode(self):
        """
        Toggles the application mode (e.g., iCloud-MDM vs. Basic mode).
        Stops running threads if necessary and updates UI elements accordingly.
        """
        try:
            if self.thread_running:
                # Stop any running threads
                self.stop_event.set()
                self.start_button.config(text="Start")
                self.status_var.set("🔴 Stopped")

                # Mark threads as stopped
                self.thread_running = False

            # Toggle the mode
            self.check_type = not self.check_type

            # Update mode label and other UI elements
            self.mode_var.set("Mode: iCloud-MDM" if self.check_type else "Mode: Basic")
            self.mode_label.config(fg="red" if self.check_type else "green")

        except Exception as e:
            logging.error(f"Error while toggling mode: {e}")
            raise

    def on_spacebar(self, event=None):
        """
        Toggles the `manual_stop` state on spacebar press and controls thread execution.
        Provides debug feedback in the console.

        :param event: (Optional) Event object passed by the key binding (default: None)
        """
        try:
            # Toggle manual_stop state
            self.manual_stop = not self.manual_stop

            # Toggle thread execution
            self.toggle_thread()

            # Debug print for feedback
            print(f"Manual stop {'enabled' if self.manual_stop else 'disabled'}")
        except Exception as e:
            logging.error(f"Error in on_spacebar: {e}")
            raise

    def run_command(self, cmd):
        """
        Executes a shell command and returns its output as a stripped string.

        :param cmd: Command to execute as a string
        :return: Stripped output of the command (stdout)
        :raises: subprocess.CalledProcessError if the command fails
        """
        try:
            # Execute the command and capture its output
            output = subprocess.check_output(cmd, shell=True, text=True).strip()
            return output
        except subprocess.CalledProcessError as e:
            # Log the error details
            logging.error(f"Command failed: {cmd}")
            logging.error(f"Return code: {e.returncode}")
            logging.error(f"Error output: {e.output}")
            raise
        except Exception as e:
            # Handle other unforeseen errors
            logging.error(f"An unexpected error occurred: {e}")
            raise

    def get_model_name(self, last4):
        """
        Fetches the data from Apple's API and extracts the model name.

        Args:
            last4 (str): The last 4 characters of the serial number.

        Returns:
            str: The extracted model name or None if not found.
        """
        url = f"https://support-sp.apple.com/sp/product?cc={last4}"

        try:
            # Make the API request
            response = requests.get(url, timeout=10)

            # Check for a successful response
            if response.status_code == 200:
                # Fetch the API response as text
                apple_check_data = response.text

                # Extract model name using regex
                match = re.search(r'<configCode>(.*?)</configCode>', apple_check_data)

                if match:
                    model_name = match.group(1)
                    logging.info(f"Model name found: {model_name}")
                    return model_name
                else:
                    logging.warning("Model name not found in API response.")
                    return None
            else:
                logging.error(f"Failed to fetch data. HTTP Status Code: {response.status_code}")
                return None
        except requests.RequestException as e:
            # Handle exceptions related to the requests module
            logging.error(f"Error occurred while fetching data from URL: {e}")
            return None

    def spec_check(self, serial_number):
        """
        Fetch and parse MacBook system specifications based on the serial number.

        Args:
            serial_number (str): The serial number of the Mac.

        Returns:
            tuple: A tuple containing Processor, Graphics Card, Memory, and Storage information,
                   or None if data cannot be fetched or parsed properly.
        """
        url = f"https://macfinder.co.uk/model/macbook-pro-15-inch-2018/?serial={serial_number}"
        temp_html = os.path.join(self.temp_dir, "mac_info.html")

        try:
            # Use `requests` to fetch HTML content instead of subprocess/curl
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                logging.error(f"Failed to fetch Mac info. HTTP Status Code: {response.status_code}")
                return None

            # Write the fetched content to a temporary file
            with open(temp_html, "w") as file:
                file.write(response.text)

        except requests.RequestException as e:
            logging.error(f"Error occurred while fetching data from URL: {e}")
            return None

        # Parse the HTML content
        try:
            with open(temp_html, "r") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            # Locate the info block
            block = soup.select_one("div.about-your-mac-box")
            if not block:
                logging.warning(f"Could not find information block for serial: {serial_number}")
                return None

            # Helper function to extract specific details
            def extract(label):
                el = block.find("span", string=label)
                return el.find_next("span").text.strip() if el else ""

            # Extract relevant specifications
            return (
                extract("Processor:"),
                extract("Graphics Card:"),
                extract("Memory:"),
                extract("Storage:")
            )

        except Exception as e:
            logging.error(f"Error occurred while parsing data: {e}")
            return None

    def add_to_frame_queue(self,frame):
        try:
            # Limit queue size to prevent memory buildup
            if self.frame_queue.qsize() > 5:  # Adjust this number based on your needs
                try:
                    # Remove old frames
                    self.frame_queue.get_nowait()
                except Empty:
                    pass
            self.frame_queue.put_nowait(frame)
        except Exception as e:
            print("\033[93mWarning: Could not add frame to queue\033[0m")
            logging.error(f"Warning: Could not add frame to queue: {e}")
            return False


    def write_last4_to_csv(self, last4, model_name):
        """
        Appends the last 4 characters of a serial number and model name to the CSV file.

        Args:
            last4 (str): The last 4 characters of a serial number.
            model_name (str): The corresponding model name.

        Returns:
            bool: True if the data was written successfully, False otherwise.
        """
        try:
            # Open the CSV file in append mode and add the row
            with open(self.csv_filepath, mode="a", newline="") as file:
                writer = csv.writer(file)
                writer.writerow([last4, model_name])  # Append the row with last4 and model_name

            logging.info(f"Successfully added {last4}, {model_name} to {self.csv_filepath}")
            return True
        except Exception as e:
            logging.error(f"An error occurred while writing to {self.csv_filepath}: {e}")
            return False

    def generate_label(self, serial_number, model_name, cpu, gpu, ram, ssd, icloud, mdm, config, model_name_sickw):
            """
            Generates a label, saves it as PDF, and sends it to the printer.

            Args:
                serial_number (str): Device's serial number.
                model_name (str): Device's model name.
                cpu (str): CPU specifications.
                gpu (str): GPU specifications.
                ram (str): RAM capacity.
                ssd (str): Storage capacity.
                icloud (str): iCloud status.
                mdm (str): MDM status.
                config (str): Configuration information.
                model_name_sickw (str): An alternative model name, if available.

            Returns:
                bool: True if the label was successfully created and printed, False otherwise.
            """
            html_path = os.path.join(self.output_dir, f"{serial_number}.html")
            pdf_path = os.path.join(self.output_dir, f"{serial_number}.pdf")

            try:
                # Generate the HTML content for the label
                html_content = f"""<!DOCTYPE html>
                <html><head><style>
                    @page {{ margin: 0mm; size: 4in 1in; }}
                    body {{ font-size: 14px; }}
                    .bold {{ font-weight: bold; }}
                    .model-name {{ font-size: 26px; font-weight: bold; }}
                </style></head>
                <body><div style='text-align: center;' class='bold'>
                    <span class="model-name">{model_name + "<br>" if model_name else ""}</span>
                    {"<br>" + serial_number if serial_number else ""} {" iCloud " + icloud if icloud else ""} {" MDM " + mdm if mdm else ""}
                    {"<br>" + config if config else ""} {model_name_sickw if model_name_sickw else ""}
                    {"<br>" + cpu if cpu else ""} {" " + gpu if gpu else ""} {" " + ram if ram else ""} {" " + ssd if ssd else ""}
                </div></body></html>"""

                # Write the HTML content to an HTML file
                with open(html_path, "w") as html_file:
                    html_file.write(html_content)
                logging.info(f"Generated HTML file: {html_path}")

                # Convert the HTML to a PDF using headless Chrome
                chrome_command = (
                    f"'{self.chrome_path}' --headless --disable-gpu --no-pdf-header-footer "
                    f"--print-to-pdf='{pdf_path}' '{html_path}'"
                )
                run(chrome_command, shell=True, check=True)
                logging.info(f"Generated PDF file: {pdf_path}")

                # Print the PDF file using the lp (line printer) command
                #run(f"lp -o fit-to-page -o media=Custom.4x1in -p {PRINTER_NAME} '{pdf_path}'", shell=True)
                print_command = f"lp -o fit-to-page -o media=Custom.4x1in -p {self.printer_name} '{pdf_path}'"
                run(print_command, shell=True, check=True)
                logging.info(f"Sent PDF to printer: {self.printer_name}")

                # Cleanup: remove the temporary HTML file
                if os.path.exists(html_path):
                    os.remove(html_path)
                    logging.info(f"Removed temporary HTML file: {html_path}")

                return True  # Successfully generated and printed
            except CalledProcessError as e:
                logging.error(f"Command execution failed: {e}")
            except Exception as e:
                logging.error(f"An error occurred while generating the label: {e}")
            finally:
                # Cleanup in case of a failure
                if os.path.exists(html_path):
                    os.remove(html_path)
                    logging.info(f"Removed HTML file during error cleanup: {html_path}")
                return False  # Operation failed

    def is_duplicate(self, key):
        """
        Check if a key is a duplicate within a specified timeout.

        Args:
            key (str): The key to check for duplication.

        Returns:
            bool: True if the key is a duplicate, False otherwise.
        """
        now = time.time()
        last_time = self.recent_matches.get(key)
        if last_time:
            time_diff = now - last_time
            if time_diff < self.duplicate_timeout:
                print(f"\033[93mSkipping {key} - {self.duplicate_timeout - time_diff:.1f} seconds remaining\033[0m")
                return True
        self.recent_matches[key] = now
        return False

    def log_event(self, message):
        """
        Logs an event message to the log file with a timestamp.

        Args:
            message (str): The message to log.
        """
        log_file = os.path.join(os.path.expanduser("~/Documents/log.txt"))
        timestamp = datetime.now().strftime("[%a %b %d %H:%M:%S %Y]")
        try:
            with open(log_file, "a") as f:
                f.write(f"{timestamp} {message}\n")
            logging.info(f"Logged event: {message}")
        except Exception as e:
            logging.error(f"Failed to write to log file: {log_file}. Error: {e}")


    def load_api_key(self, filepath="apikey.txt"):
        """
        Loads an API key from the specified file.

        Args:
            filepath (str): File path to load the API key from. Defaults to "apikey.txt".

        Returns:
            str or None: The API key if successful, None otherwise.
        """
        try:
            with open(filepath, mode='r') as file:
                apikey = file.read().strip()  # Remove leading/trailing whitespace
                logging.info("API key loaded successfully.")
                return apikey
        except FileNotFoundError:
            logging.error(f"File {filepath} not found. Please ensure it is placed in the correct folder.")
            return None
        except Exception as e:
            logging.error(f"An error occurred while loading {filepath}: {e}")
            return None

    def icloudCheck(self, serial_number):
        """
        Performs an iCloud check for the given serial number using a third-party API.

        Args:
            serial_number (str): The serial number to check.

        Returns:
            tuple: Contains the extracted iCloud lock, MDM lock, configuration details, and model name.
        """
        import re
        import json

        # Load API key using the instance method
        apikey = self.load_api_key()
        if not apikey:
            self.log_event("API key is missing. Cannot proceed with iCloud check.")
            return "", "", "", ""

        # Build API URL using the loaded API key
        api_url = f"https://sickw.com/api.php?format=json&key={apikey}&imei={serial_number}&service=72"

        # Initialize default values
        icloud = ""
        mdm = ""
        config = ""
        model_name_sickw = ""
        response_code = "Unknown"  # Default value for response code

        try:
            # Use curl to fetch the API response and log the HTTP status code
            curl_command = f"curl -s -k -w '%{{http_code}}' --connect-timeout 60 --max-time 60 '{api_url}'"
            response = self.run_command(curl_command)  # Use the instance method to run the command

            # Separate the HTTP status code from the response content
            response_code = response[-3:]  # Last three characters are the HTTP status code
            response_body = response[:-3]  # All characters before the status code

            # Log the HTTP response code
            self.log_event(f"HTTP Response Code: {response_code}")

            # Parse the response JSON
            response_data = json.loads(response_body)

            # Extract raw result HTML from the `result` field
            raw_result = response_data.get("result", "")

            # Extract Model Name using regex
            model_name_sickw_match = re.search(r"Model Name:\s*([^<]+)<br \/>", raw_result)
            if model_name_sickw_match:
                model_name_sickw = model_name_sickw_match.group(1).strip()

            # Extract configuration and other values
            config_match = re.search(r"Device Configuration:\s*([^<]+)", raw_result)
            if config_match:
                config = config_match.group(1).strip()

            mdm_match = re.search(r"MDM Lock:\s*<font[^>]*>([^<]+)</font>", raw_result)
            if mdm_match:
                mdm = mdm_match.group(1).strip()

            icloud_match = re.search(r"iCloud Lock:\s*<font[^>]*>([^<]+)</font>", raw_result)
            if icloud_match:
                icloud = icloud_match.group(1).strip()

            # Log extracted information
            self.log_event(
                f"Full Check: {serial_number} | Model Name: {model_name_sickw} | Config: {config} | "
                f"iCloud: {icloud} | MDM: {mdm} | Response Code: {response_code}"
            )
            self.log_event(f"Response: {response_body}")

        except json.JSONDecodeError as e:
            self.log_event(f"Failed to parse JSON for serial number {serial_number}: {e}")
        except Exception as e:
            self.log_event(f"Unhandled error during iCloud check for {serial_number}: {e}")

        # Return the extracted values
        return icloud, mdm, config, model_name_sickw


    def clean_common_ocr_errors(self, text):
        """
        Cleans common OCR-related character recognition errors in text.

        Args:
            text (str): The text to clean.

        Returns:
            str: The cleaned text with common OCR errors replaced.
        """
        return (text.replace('I', '1')
                .replace('O', '0'))


    def most_common(self, items):
        """
        Finds the most common element in a list.

        Args:
            items (list): The list of elements.

        Returns:
            Any: The most common element in the list, or None if the list is empty.
        """
        return Counter(items).most_common(1)[0][0] if items else None

    def extract_matches(self, texts):
        """
        Extracts matches for serial numbers, amodel patterns, and emc patterns from a list of texts.

        Args:
            texts (list): List of strings to extract matches from.

        Returns:
            tuple: (serials, amodels, emcs) - Lists of extracted matches for each pattern.
        """
        from re import findall, search

        serials, amodels, emcs = [], [], []
        for t in texts:
            # Serial matches
            serials.extend(findall(self.serial_pattern, t))

            # Amodel pattern matches
            #if (amodel_match := search(self.amodel_pattern, t)):
                #amodels.append(amodel_match.group(0))

            # EMC pattern matches
            #if (emc_match := search(self.emc_pattern, t)):
                #emcs.append(emc_match.group(1))

        return serials, "", ""

    def update_video(self):
        """
        Updates the video feed by converting it to an RGB format and displaying it on the UI.

        This method retrieves the next frame from `self.feed_frame` (if available), updates the image display
        in `self.video_label`, and schedules itself to run again after 80 milliseconds.
        """
        if self.feed_frame_zoom_in is not None:
            # Convert feed_frame (BGR) to RGB
            img = cv2.cvtColor(self.feed_frame_zoom_in, cv2.COLOR_BGR2RGB)

            # Convert the frame to a PIL Image and then to an ImageTk object
            img = Image.fromarray(img)
            imgtk = ImageTk.PhotoImage(image=img)

            # Update the video_label with the new image
            self.zoom_in_video_label.imgtk = imgtk
            self.zoom_in_video_label.config(image=imgtk, width=700, height=500)
        if self.feed_frame_zoom_out is not None:
            # Convert feed_frame (BGR) to RGB
            img = cv2.cvtColor(self.feed_frame_zoom_out, cv2.COLOR_BGR2RGB)

            # Convert the frame to a PIL Image and then to an ImageTk object
            img = Image.fromarray(img)
            imgtk = ImageTk.PhotoImage(image=img)

            # Update the video_label with the new image
            self.zoom_out_video_label.imgtk = imgtk
            self.zoom_out_video_label.config(image=imgtk, width=800, height=600)

        # Re-run the update_video method after 80ms
        self.tk.after(10, self.update_video)


    def load_last4_data(self, filepath="last4.csv"):
        """
        Loads data from the given CSV file and initializes the `self.last4` attribute.
        Each row contains the last 4 digits of a serial number and the corresponding model name.
        The file doesn't include a header row.

        Args:
            filepath (str): The path to the CSV file. Defaults to "last4.csv".

        Updates:
            self.last4 (list): A list of tuples, where each tuple is (last_4_serial, model_name).
                               If the file is not found or an error occurs, an empty list is assigned.
        """
        try:
            with open(filepath, mode='r') as file:
                reader = csv.reader(file)
                # Populate self.last4 with tuples (last_4_serial, model_name)
                self.last4 = [(row[0], row[1]) for row in reader]
                self.log_event(f"Loaded {len(self.last4)} entries from {filepath}.")
        except FileNotFoundError:
            self.log_event(f"File {filepath} not found. Please ensure it is placed in the correct folder.")
            self.last4 = []  # Reset to an empty list on error
        except Exception as e:
            self.log_event(f"An error occurred while loading {filepath}: {e}")
            self.last4 = []  # Reset to an empty list on error


    def main_check(self, serial_number):
        """
        The main function to process a serial number and perform checks such as:
        - Duplicate checks
        - Local database lookup
        - Specification checks
        - iCloud and MDM checks
        - Generating a label

        Args:
            serial_number (str): The serial number to check.
            bypass (bool): Whether to bypass certain checks.
        """
        try:

            # Early return if no serial number
            if not serial_number:
                return
            # Clean the serial number to fix common OCR errors
            serial_number = self.clean_common_ocr_errors(serial_number)
            # Check for duplicate BEFORE acquiring the lock
            if self.is_duplicate(serial_number):
                self.log_event(
                    f"Duplicate serial found ! Skipping {serial_number}..."
                )
                return
            # Try to acquire the lock; return if it's already locked
            if not self.main_check_lock.acquire(blocking=False):
                self.log_event(
                    f"Another main_check is already running for serial {self.serial}, skipping {serial_number}..."
                )
                return


            self.log_event(f"Starting processing for Serial Number: {serial_number}")

            # Load the database (last4.csv)
            self.load_last4_data("last4.csv")

            # Update instance-level variables
            self.serial = serial_number
            self.processed_frame_count = 0
            #self.frame_queue = Queue()

            # Clear all frames from the queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    break

            # Update the UI
            #self.tk.after(50, lambda: self.right_label_second_row.config(
            #    text=f"Processed Frames: {self.processed_frame_count}   Frames in Queue: {self.frame_queue.qsize()}",
            #    anchor="e")
            #              )



            # Initialize variables for tracking details
            model_name = None
            cpu = None
            gpu = None
            ram = None
            ssd = None
            icloud = None
            mdm = None
            config = None
            model_name_sickw = None

            # Process the last 4 digits of the serial number
            self.log_event(f"Checking specification for Serial Number: {serial_number}")
            last_4_digits = serial_number[-4:]

            # Check if the last 4 digits already exist in local database (last4.csv)
            matches = [entry for entry in self.last4 if entry[0] == last_4_digits]
            if matches:
                for match in matches:
                    model_name = match[1]
                    self.log_event(f"Serial {serial_number} matches model: {model_name}.")
                    break
            else:
                # If not found locally, check Apple's database
                self.log_event(
                    f"Serial {serial_number} is unknown in local database. Checking with Apple for model name."
                )
                model_name = self.get_model_name(last_4_digits)
                if model_name:
                        self.write_last4_to_csv(last_4_digits, model_name)

            # Perform a spec check
            specs = self.spec_check(serial_number)
            if specs:
                cpu, gpu, ram, ssd = specs
                if cpu:
                    self.log_event(
                        f"Spec Check: {serial_number} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd}"
                    )
                else:
                    self.log_event(
                        f"Could not find spec info (VALID serial number) for serial: {serial_number}"
                    )
            else:
                self.log_event(
                    f"Could not find spec info (INVALID serial number) for serial: {serial_number}"
                )

            # Perform an iCloud and MDM check (if required)
            if self.check_type:
                icloud_info = self.icloudCheck(serial_number)
                if icloud_info:
                    icloud, mdm, config, model_name_sickw = icloud_info
                    self.log_event(
                        f"iCloud MDM Check: {serial_number} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | "
                        f"SSD: {ssd} | iCloud: {icloud} | MDM: {mdm} | Config: {config} | Model: {model_name_sickw}"
                    )

            # Generate and display the label
            self.generate_label(serial_number, model_name, cpu, gpu, ram, ssd, icloud, mdm, config, model_name_sickw)

        except Exception as e:
            self.log_event(f"Error in main_check: {e}")

        finally:
            # Always release the lock
            self.main_check_lock.release()
            self.log_event(f"Completed processing for serial: {serial_number}")

    def stop_and_review(self):
        """
        Stops the processing thread if it's running and opens the manual review window.
        """
        if self.thread_running:
            self.toggle_thread()  # Stop the thread
        self.tk.after(50, self.open_manual_window)  # Open the manual review window after a slight delay

    def auto_resume_thread(self):
        """
        Automatically resumes the thread if it's stopped, not manually paused, and no manual window is open.
        """
        if (self.stop_event.is_set() and
                not self.manual_stop and
                not self.thread_running and
                (self.manual_window is None or not self.manual_window.winfo_exists())):
            self.log_event("Auto-resuming thread...")
            self.stop_event.clear()
            self.stop_ocr_processing_event.clear()

            # Start background threads for OCR processing
            Thread(target=self.background_task, daemon=True).start()
            Thread(target=self.ocr_processing, daemon=True).start()

            self.start_button.config(text="Stop")
            self.thread_running = True

        # Re-check auto-resume conditions every 5 seconds
        self.tk.after(5000, self.auto_resume_thread)

    def on_spacebar(self, event=None):
        """
        Toggles manual stop state and starts/stops the thread as needed.
        """
        self.manual_stop = not self.manual_stop  # Toggle manual stop state
        self.toggle_thread()  # Stop/start the thread accordingly
        self.log_event(f"Manual stop {'enabled' if self.manual_stop else 'disabled'}")  # Debug log

    def cv2_to_cgimage(self, cv_img):
        """
        Converts an OpenCV image to a CGImage format for Vision processing.
        """
        import Quartz

        # Ensure the image is RGB (convert if it's BGR)
        if len(cv_img.shape) == 3 and cv_img.shape[2] == 3:
            cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)

        height, width = cv_img.shape[:2]

        # Handle both RGB and grayscale images
        if len(cv_img.shape) == 3:
            bytes_per_row = width * 3
            color_space = Quartz.CGColorSpaceCreateDeviceRGB()
            bitmap_info = Quartz.kCGBitmapByteOrderDefault | Quartz.kCGImageAlphaNone
        else:  # Grayscale image
            bytes_per_row = width
            color_space = Quartz.CGColorSpaceCreateDeviceGray()
            bitmap_info = Quartz.kCGImageAlphaNone

        # Convert the image to NSData
        data = cv_img.tobytes()
        data_provider = Quartz.CGDataProviderCreateWithData(None, data, len(data), None)

        # Create a CGImage object
        cg_image = Quartz.CGImageCreate(
            width, height,  # Dimensions
            8,  # Bits per component
            8 * cv_img.shape[-1],  # Bits per pixel
            bytes_per_row,  # Bytes per row
            color_space,  # Color space
            bitmap_info,  # Bitmap info
            data_provider,  # Data provider
            None,  # Decode array
            False,  # Should interpolate
            Quartz.kCGRenderingIntentDefault  # Rendering intent
        )
        return cg_image

    def process_with_vision(self, frame):
        """
        Processes an image frame using Apple's Vision framework for OCR.
        """
        from Vision import VNRecognizeTextRequest, VNImageRequestHandler, VNRecognizeTextRequestRevision3

        texts = []

        try:
            # Convert OpenCV frame to CGImage
            cg_image = self.cv2_to_cgimage(frame)

            # Create Vision request
            request = VNRecognizeTextRequest.alloc().init()
            request.setRevision_(VNRecognizeTextRequestRevision3)
            request.setRecognitionLevel_(0)  # Fast recognition
            request.setUsesLanguageCorrection_(False)
            request.setMinimumTextHeight_(0.05)  # Adjust as needed

            # Perform OCR
            handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
            success = handler.performRequests_error_([request], None)

            if success:
                results = request.results()
                if results:
                    for observation in results:
                        confidence = observation.confidence()
                        if confidence > 0.5:  # Confidence threshold
                            candidates = observation.topCandidates_(10)
                            if candidates and len(candidates):
                                recognized_text = candidates[0].string()
                                texts.append(recognized_text)

        except Exception as e:
            self.log_event(f"Vision framework error: {e}")
        return texts
    # Add this decorator to memory-intensive functions
    #@profile
    def ocr_processing(self):
        """
        Processes frames from the frame queue using OCR and extracts serial numbers.
        The function monitors the `stop_ocr_processing_event` to gracefully exit.
        """
        self.log_event("OCR Processing started")
        collected_serials = []  # Buffer to collect serials
        while not self.stop_ocr_processing_event.is_set():
            if self.stop_event.is_set():  # Stop if the global stop event is set
                break
            try:
                texts = None
                if self.frame_queue and self.frame_queue.qsize() >= 1:
                    # Get a frame from the queue with a timeout
                    #print(f"Debug: Type of frame_queue is {type(self.frame_queue)}")  # Debug
                    #self.print_frame_queue()

                    processing_frame = self.frame_queue.get(timeout=1)
                    # Increment processed frame count
                    self.processed_frame_count += 1
                    # Use Vision framework OCR to process the frame

                    texts = self.process_with_vision(processing_frame)

                    # Process detected texts to extract serial numbers
                    if texts:
                        #pass
                        #print(texts)
                        serials, _, _ = self.extract_matches(texts)
                        if serials:
                            # Add new serials to buffer, maintaining uniqueness
                            collected_serials.extend(serials)

                            # If sufficient serials are collected, identify the most common one
                            if len(collected_serials) >= self.total_serials_processing_limit:  # Threshold for determining the most common serial
                                most_common_serial = self.most_common(collected_serials)
                                if most_common_serial:
                                    self.log_event(f"Processing most common serial: {most_common_serial}")
                                    # Process the most common serial
                                    self.main_check(most_common_serial)
                                collected_serials = []  # Clear buffer after processing
                                # Limit frame polling frequency

                else:
                    pass
                    #self.log_event("No frames in queue. Waiting for frames...")

            except queue.Empty:
                # Handle the case when no frame is available
                print("No frame available in queue")
                continue  # Continue if the frame queue is empty
            except Exception as e:
                self.log_event(f"OCR processing error: {e}")
            time.sleep(0.01)
        #print("exiting ocr_processing")
        #self.tk.after(2000, self.ocr_processing())


    def background_task(self):
        """
        Background task to capture frames from the camera and prepare them for OCR processing.
        The method runs until the `stop_event` is set, and processes the video feed.
        """
        try:
            # Mark thread as running
            self.thread_running = True
            self.update_status()
            print("Background task running")
            # Start capturing video from the default camera
            cap = cv2.VideoCapture(0)

            #self.print_frame_queue()

            # Optional: Set desired camera properties (commented as examples)
            # cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            # cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            # cap.set(cv2.CAP_PROP_FPS, 30)

            if not cap.isOpened():  # Handle camera error
                self.number_var.set("Camera Error")
                self.status_var.set("🔴 Stopped")
                self.thread_running = False
                return

            # Define rectangle dimensions for cropping (example values)
            roi_w, roi_h = int(300 * 2.5), int(100 * 2.5)  # Rectangle size scaled 2.5x

            while not self.stop_event.is_set():
                if self.processed_frame_count >= 1000:
                    self.on_closing()

                    sys.exit(1)
                ret, frame = cap.read()  # Capture a frame
                if not ret:
                    self.number_var.set("Camera Read Fail")
                    break

                # Resize the frame for OCR processing
                zoom_in_frame = self.resize_for_ocr(frame, self.zoom_in_factor)
                zoom_out_frame = self.resize_for_ocr(frame, self.zoom_out_factor)

                # Apply horizontal/vertical flip if enabled
                if self.flip_active:
                    zoom_in_frame = cv2.flip(zoom_in_frame, -1)
                    zoom_out_frame = cv2.flip(zoom_out_frame, -1)

                # Apply cropping if `autocrop` is enabled, otherwise use the full frame
                if self.autocrop:
                    x, y, w, h = 100, 100, 300, 200  # Example values
                    final_frame = zoom_in_frame[y:y + h, x:x + w]  # Crop to rectangle
                else:
                    final_frame = zoom_in_frame

                # Add the processed frame to the frame queue
                self.add_to_frame_queue(final_frame)

                # Create a copy for UI rendering
                self.feed_frame_zoom_in = zoom_in_frame.copy()
                self.feed_frame_zoom_out = zoom_out_frame.copy()
                self.number_var.set(f"Serial: {self.serial}")

                # Update the status text
                self.status_text_core = "Checking For iCloud and MDM Lock" if self.check_type else "Checking Spec Only"
                status_text = f"^^^^^^  {self.status_text_core}  ^^^^^^"
                color = (0, 0, 255) if self.check_type else (0, 255, 0)

                # Get frame dimensions
                frame_h, frame_w = self.feed_frame_zoom_out.shape[:2]

                # Define rectangle placement for UI
                roi_w, roi_h = 500, 200
                roi_x = (frame_w - roi_w) // 2  # Center horizontally
                roi_y = (frame_h - roi_h) // 2  # Center vertically
                cv2.rectangle(self.feed_frame_zoom_out, (roi_x, roi_y), (roi_x + roi_w, roi_y + roi_h), (0, 255, 0), 2)

                # Helper to center text
                def center_text_x(text, font, scale, thickness):
                    size = cv2.getTextSize(text, font, scale, thickness)[0]
                    return int((frame_w - size[0]) / 2)

                # Add status text below the rectangle
                status_scale = 1.0
                status_thickness = 2
                status_x = center_text_x(status_text, cv2.FONT_HERSHEY_SIMPLEX, status_scale, status_thickness)
                status_y = roi_y + roi_h + 40
                cv2.putText(self.feed_frame_zoom_out, status_text, (status_x, status_y),
                            cv2.FONT_HERSHEY_SIMPLEX, status_scale, color, status_thickness, cv2.LINE_AA)

                time.sleep(0.1)  # Add delay to control the frame processing frequency

            # Release the camera resource
            cap.release()
            self.thread_running = False
            self.status_var.set("🔴 Stopped")

            # Periodic cleanup for garbage collection
            if self.processed_frame_count % 100 == 0:
                gc.collect()

        except Exception as e:
            logging.error(f"Background task error: {str(e)}")
            logging.error(traceback.format_exc())
            self.status_var.set(f"Error: {str(e)}")
            time.sleep(1)  # Prevent rapid error loops

    def submit_serial(self):

        self.serial = self.serial_entry.get()  # Update instance-level serial value
        self.uppercase_serial = self.serial.upper()
        self.main_check(self.uppercase_serial)  # Call main_check with the entered serial
        self.manual_window.destroy()  # Close the manual window
        self.tk.attributes('-topmost', True)  # Restore main window's "always on top" property

    def on_manual_window_close(self):
        # Restore root's topmost setting when manual_window is closed
        self.tk.attributes('-topmost', True)
        self.manual_window.destroy()

    def open_manual_window(self):
        """
        Creates and opens a manual check window for entering a serial manually.
        Ensures the window is properly bound to methods for submitting or closing.
        """
        # Handle serial submission
        #print("Opening manual window")


        # Ensure we are running in the main thread
        if threading.current_thread() is not threading.main_thread():
            self.tk.after(0, self.open_manual_window)
            return

        # If a manual window already exists, destroy it
        if self.manual_window is not None and self.manual_window.winfo_exists():
            self.manual_window.destroy()

        # Create a new pop-up window
        self.manual_window = tk.Toplevel(self.tk)
        self.manual_window.title("Manual Check")

        # Bind Escape key to close the window handler
        self.manual_window.bind('<Escape>', lambda event: self.on_manual_window_close())

        # Ensure the window appears on top
        self.manual_window.transient(self.tk)  # Make it a child of the main window
        self.manual_window.attributes("-topmost", True)  # Always on top

        # Temporarily remove the main window's "always on top" property to allow interaction
        self.tk.attributes('-topmost', False)

        # Configure the size and resizability of the manual window
        self.manual_window.geometry("500x200")
        self.manual_window.resizable(False, False)

        # Create interface components (label and entry for serial input)
        tk.Label(self.manual_window, text="Serial:").grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.serial_entry = tk.Entry(self.manual_window, width=30)
        self.serial_entry.grid(row=0, column=1, padx=10, pady=10, sticky="e")

        # Pre-fill the entry with the current serial, if available
        self.serial_entry.insert(0, self.serial if self.serial else "")
        self.serial_entry.focus_set()  # Set focus to the entry field for immediate input


        # Bind Enter key to the serial submission function
        self.manual_window.bind('<Return>', lambda event: self.submit_serial())

        # Button to manually validate and check the serial
        check_button = tk.Button(self.manual_window, text="Check", command=lambda: self.submit_serial())
        check_button.grid(row=1, column=1, pady=10, sticky="e")

        # Optionally include the "Bypass Check" feature as a commented example
        # bypass_button = tk.Button(self.manual_window, text="Bypass Check", command=lambda: submit_serial(True))
        # bypass_button.grid(row=1, column=2, pady=10, sticky="e")

        # Set up the behavior when the manual window is closed
        self.manual_window.protocol("WM_DELETE_WINDOW", self.on_manual_window_close)



    def toggle_flip(self):
        """
        Toggles the flip_active state and updates the associated button text.
        """
        self.flip_active = not self.flip_active
        self.flip_button.config(text="FLIP ON" if self.flip_active else "FLIP OFF")

    def update_processed_frames(self):
        """
        Updates labels to reflect processed frame count and queue size dynamically.
        """
        #Debug
        #print("update_processed_frame running")
        self.right_label_second_row.config(
            text=f"Processed Frames: {self.processed_frame_count}   Frames in Queue: {self.frame_queue.qsize()}",
            anchor="e"
        )
        # Schedule the next update in 80ms
        self.tk.after(80, self.update_processed_frames)


    def on_closing(self):
        """Clean shutdown when window is closed"""
        try:
            # Stop all threads
            self.stop_event.set()
            self.stop_ocr_processing_event.set()

            # Clean up resources
            if hasattr(self, 'frame_queue'):
                while not self.frame_queue.empty():
                    try:
                        self.frame_queue.get_nowait()
                    except:
                        break

            # Close serial connection if exists
            #if hasattr(self, 'serial') and self.serial:
                #self.serial.close()

            # Destroy the main window
            self.tk.destroy()

        except Exception as e:
            logging.error(f"Error during shutdown: {str(e)}")
            logging.error(traceback.format_exc())
            sys.exit(1)

    def __del__(self):
        # Stop monitoring thread
        if hasattr(self, 'monitor_thread'):
            self.stop_event.set()
            self.monitor_thread.join()

        # Clear frame queue only if it exists
        if hasattr(self, 'frame_queue'):
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    break

        # Force cleanup
        gc.collect()


if __name__ == "__main__":
    try:
        app = MainApp()
        app.tk.mainloop()
    except Exception as e:
        logging.critical(f"Fatal error: {str(e)}")
        logging.critical(traceback.format_exc())
        sys.exit(1)
