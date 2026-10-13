import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import getpass
from urllib.parse import quote
import cv2

pw = quote(getpass.getpass("NVR password: "), safe="")
for ch in range(1, 8):
    url = f"rtsp://admin:{pw}@192.168.1.250:554/chID={ch}&streamType=sub"
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    ok, frame = cap.read()
    cap.release()
    if ok:
        cv2.imwrite(f"cam{ch}.jpg", frame)
        print(ch, "OK", frame.shape)
    else:
        print(ch, "no video")