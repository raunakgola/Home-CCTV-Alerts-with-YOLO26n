#!/usr/bin/env python3
"""
cctv_zone.py  -  draw and manage the zones (marked areas) used by cctv_alert_live.py
====================================================================================

This tool only CREATES zones. The alerts are made by cctv_alert_live.py, which reads zones.json
by itself. Keep both files in the same folder.

    python cctv_zone.py draw 3            mark the area of Camera 3 (a window opens)
    python cctv_zone.py draw 3 --from clip.mp4    use a picture/video instead of the live camera
    python cctv_zone.py list              show which cameras have a zone
    python cctv_zone.py remove 3          delete the zone of Camera 3

Drawing window:
    left click   add a corner (3 or more)        right click  remove the last corner
    r            start again                      Enter or s   save
    q or Esc     cancel (nothing is saved)
    To delete a zone from inside the window: press r, then Enter.

Corners are stored as fractions of the picture, so the zone still fits if you switch between
the sub and main stream. A camera without a zone keeps working as usual.
"""
import argparse
import getpass
import json
import os
import sys

import cv2
import numpy as np

import helpers
import settings
from urllib.parse import quote


def read_json(path):
    """Read the zone file (empty dict if it does not exist yet)."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save_zone(path, label, pts):
    """Store (or remove, with fewer than 3 corners) the zone of one camera."""
    data = read_json(path)
    if len(pts) >= 3:
        data[label] = [[round(x, 4), round(y, 4)] for x, y in pts]
    else:
        data.pop(label, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def grab_frame(source, ch, args):
    """One picture to draw on: from a file, or from the live camera."""
    if source:
        if not os.path.isfile(source):
            sys.exit(f"File not found: {source}")
        img = cv2.imread(source)
        if img is not None:
            return img
        cap = cv2.VideoCapture(source)
        frame = None
        for _ in range(15):
            ok, f = cap.read()
            if ok:
                frame = f
        cap.release()
        if frame is None:
            sys.exit(f"Could not read a picture from {source}")
        return frame
    helpers.load_env(None)
    user = args.user or os.environ.get("NVR_USER") or input("NVR username: ").strip()
    pw = os.environ.get("NVR_PASSWORD") or getpass.getpass("NVR password (hidden): ")
    auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@"
    template = args.live_template or settings.LIVE_TEMPLATE
    url = template.format(auth=auth, ip=args.ip, port=args.port, ch=ch, stream=args.stream)
    print(f"Opening camera {ch} ...")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    frame = None
    if cap.isOpened():
        for _ in range(20):
            ok, f = cap.read()
            if ok:
                frame = f
    cap.release()
    if frame is None:
        sys.exit(f"No picture from camera {ch}. Check the camera, the NVR password and the address "
                 f"(or use --from picture.jpg).")
    return frame


def cmd_draw(args):
    """'draw' command: open a picture and let the user click the zone corners."""
    label = helpers.cam_label(args.channel)
    frame = grab_frame(args.source, args.channel, args)
    h, w = frame.shape[:2]
    old = read_json(args.zones).get(label)
    pts = [(x * w, y * h) for x, y in old] if old else []
    win = f"Mark the zone for {label}"

    def on_mouse(event, x, y, flags, param):
        """Left click adds a corner, right click removes the last one."""
        if event == cv2.EVENT_LBUTTONDOWN:
            pts.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and pts:
            pts.pop()

    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(win, on_mouse)
    print("Left click = add corner | right click = undo | r = restart | Enter = save | q = cancel")
    while True:
        img = frame.copy()
        if len(pts) >= 3:
            shade = img.copy()
            cv2.fillPoly(shade, [np.array(pts, np.int32)], (255, 120, 0))
            img = cv2.addWeighted(shade, 0.25, img, 0.75, 0)
        if len(pts) >= 2:
            cv2.polylines(img, [np.array(pts, np.int32)], len(pts) >= 3, (255, 120, 0), 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(img, (int(p[0]), int(p[1])), 4, (0, 255, 255), -1)
        cv2.putText(img, f"{label}: {len(pts)} corners  (Enter = save, q = cancel)", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow(win, img)
        k = cv2.waitKey(30) & 0xFF
        if k in (13, 10, ord("s")):
            break
        if k in (ord("q"), 27):
            cv2.destroyAllWindows()
            print("Cancelled - nothing saved.")
            return
        if k == ord("r"):
            pts.clear()
    cv2.destroyAllWindows()
    norm = [(x / w, y / h) for x, y in pts]
    save_zone(args.zones, label, norm)
    if len(norm) >= 3:
        print(f"Saved the zone for {label} ({len(norm)} corners) in {args.zones}")
    else:
        print(f"Zone for {label} removed (fewer than 3 corners).")


def cmd_list(args):
    """'list' command: print the cameras that have a zone."""
    data = read_json(args.zones)
    if not data:
        print(f"No zones in {args.zones}. Draw one with:  python cctv_zone.py draw 3")
        return
    for label, pts in sorted(data.items()):
        print(f"  {label}: {len(pts)} corners")


def cmd_remove(args):
    """'remove' command: delete one camera's zone."""
    label = helpers.cam_label(args.channel)
    if label not in read_json(args.zones):
        print(f"{label} has no zone.")
        return
    save_zone(args.zones, label, [])
    print(f"Zone for {label} removed from {args.zones}")


def main():
    """Read the command line and run the chosen command."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--zones", default=settings.ZONE_FILE, help="zone file (default zones.json)")
    p = argparse.ArgumentParser(description="Draw and manage the zones used by cctv_alert_live.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draw", parents=[common], help="mark the zone of one camera with the mouse")
    d.add_argument("channel", type=int, help="camera number, e.g. 3")
    d.add_argument("--from", dest="source", metavar="FILE", help="use this picture/video instead of the live camera")
    d.add_argument("--ip", default=settings.DEFAULT_IP)
    d.add_argument("--port", type=int, default=settings.DEFAULT_PORT)
    d.add_argument("--user", help="NVR username (or NVR_USER in .env)")
    d.add_argument("--stream", choices=["sub", "main"], default="sub")
    d.add_argument("--live-template", help="custom RTSP address template")
    d.set_defaults(func=cmd_draw)

    sub.add_parser("list", parents=[common], help="show the cameras that have a zone").set_defaults(func=cmd_list)

    r = sub.add_parser("remove", parents=[common], help="delete the zone of one camera")
    r.add_argument("channel", type=int)
    r.set_defaults(func=cmd_remove)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
