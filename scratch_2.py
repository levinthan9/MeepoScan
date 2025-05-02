# image_path = "/Users/tn/Desktop/s234.jpg"
# frame = cv2.imread(image_path)
# if frame is None:
#    raise FileNotFoundError(f"Could not load image at: {image_path}")
# custom_config = r'-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 --psm 6'
text = pytesseract.image_to_string(processed)
text = clean_common_ocr_errors(text)
if text and text.strip():
    cv2.putText(frame, text[:80], (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)
    # print(text)  # Shows invisible characters like \n, \t
    cv2.imshow("Original", frame)

# Draw serial, model, and EMC on the image if found
y_offset = 200  # Starting y position
if is_full_check:
    cv2.putText(frame, f"Checking For iCloud and MDM Lock", (100, 500),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 1, cv2.LINE_AA)
else:
    cv2.putText(frame, f"Checking Spec Only", (100, 500),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 1, cv2.LINE_AA)

if serial:
    if tempSerial != serial:
        cv2.putText(frame, f"Serial Number: {serial}", (100, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 1, cv2.LINE_AA)
        y_offset += 50  # Move down for next line
        if amodel:
            cv2.putText(frame, f"AModel: {amodel}", (100, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 1, cv2.LINE_AA)
            y_offset += 50

        if emc:
            cv2.putText(frame, f"EMC: {emc}", (100, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 1, cv2.LINE_AA)
        specs = spec_check(serial)
        if specs:
            cpu, gpu, ram, ssd = specs
            if cpu:
                tempSerial = serial
                ##messagebox.showinfo("Basic Info", f"Serial: {serial}\nAmodel: {amodel}\nEMC: {emc}\nCPU: {cpu}\nGPU: {gpu}\nRAM: {ram}\nSSD: {ssd}")
                if is_full_check:
                    icloudInfo = icloudCheck(serial)
                    if icloudInfo:
                        icloud, mdm, config = icloudInfo
                    log_event(
                        f"iCloud MDM Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd} | iCloud: {icloud} | MDM: {mdm} | Config: {config} ")
                else:
                    icloud = None
                    mdm = None
                    config = None
                    log_event(
                        f"Spec Check: {serial} | Amodel: {amodel} | EMC: {emc} | CPU: {cpu} | GPU: {gpu} | RAM: {ram} | SSD: {ssd}")
                generate_label(serial, amodel, emc, cpu, gpu, ram, ssd, icloud, mdm, config)
    # for serial in serials:
    # handle_match(serial, model, emc)
    # cv2.imshow("Original", frame)
    ##cv2.imshow("Processed", processed)