#!/usr/bin/env python3
"""
cctv_alert_live.py  -  live CCTV detection (YOLO26n) with visit tracking, Excel log and Telegram alerts
=========================================================================================================

WHAT IT DOES
    * Reads the live sub-streams of your TVT NVR (cameras 1-6 by default).
    * Detects people / vehicles / animals and follows each one with the ByteTrack tracker.
    * Groups detections into VISITS: one visit = one object present in one camera.
      If an object flickers out for a few seconds and comes back (or the tracker gives it a new
      id), it stays the SAME visit instead of creating a new row.
    * Sends a Telegram alert when a NEW visit starts: camera, object, time (+ snapshot photo).
    * Writes an Excel file: one row per visit with First seen, Last seen and how long it stayed.
    * Optional ZONES: areas you mark per camera with  python cctv_zone.py draw 3.  Detection still
      runs on the whole picture; zones only decide WHICH alerts you get (see ZONE ALERTS below).

INSTALL (once)
    pip install ultralytics opencv-python openpyxl lap

SETTINGS FILE:  create a file named  .env  next to this script (see the step-by-step guide):
    NVR_USER=admin
    NVR_PASSWORD=your_nvr_password
    TELEGRAM_BOT_TOKEN=123456789:AAH...
    TELEGRAM_CHAT_ID=123456789
  Keep .env private. It is read by this script only; nothing is ever sent to anybody except
  Telegram (and only the alerts you enable).

RUN
    python cctv_alert_live.py --test-telegram        # sends one test message to your phone
    python cctv_alert_live.py --show                 # live, with preview windows (q = stop)
    python cctv_alert_live.py                        # live, no windows (leave running)
    python cctv_alert_live.py --channels 1 2 3 --notify person motorcycle
    python cctv_alert_live.py --no-photo             # text-only alerts (no picture leaves home)
    python cctv_alert_live.py --no-alerts            # Excel only

    # Try everything without the NVR, on a video file:
    python cctv_alert_live.py --test-video clip.mp4 --channels 1 --warmup 0 --minutes 1

ZONE ALERTS  (zones are drawn with cctv_zone.py and saved in zones.json)
    Three lists decide who triggers an alert:
        --notify X ...              anywhere in the picture (zone or not)
        --notify-in-zone X ...      only when X is inside the zone  (alert when it ENTERS the zone)
        --notify-outside-zone X ... only when X is outside the zone (alert when it appears there
                                    or LEAVES the zone)
    The same object in both zone lists (or in --notify) is alerted everywhere.
    A camera WITHOUT a zone has no "inside": it works as usual for --notify and for
    --notify-outside-zone, and never alerts for --notify-in-zone.
    With none of the three lists given, people are alerted everywhere (the original behaviour).

    python cctv_alert_live.py --notify-outside-zone person --notify-in-zone cow dog --show

PERFORMANCE  (how much does my PC have to work?)
    python cctv_alert_live.py --performance --no-alerts --channels 1 2 3 --show
    A window with live graphs shows CPU, RAM, free disk, detection time per frame and whether the PC
    keeps up. Run again with other settings (--stream main, --step 8, --channels 1, without --show...)
    and compare all runs with:  python cctv_alert_live.py --performance-report

NOTE: an object that is ALREADY in view when the script starts (e.g. parked bikes) is logged as
"present at start" and does not trigger an alert (see --warmup).
"""
import os

# TCP is more reliable than UDP for RTSP. Must be set before OpenCV opens a stream.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import argparse
import getpass
import threading
import time
from datetime import datetime
from urllib.parse import quote

from ultralytics import YOLO

import settings
import zones
import camera
from camera import PREVIEW, live_worker
from helpers import STOP, cam_label, load_env, make_tracker_cfg
from performance import PerfMonitor, show_runs
from report import save_excel
from telegram_client import Telegram, run_telegram_test
from visits import VisitManager


def parse_args():
    """Every command-line option of the program."""
    p = argparse.ArgumentParser(description="Live CCTV detection with visit tracking, Excel log and Telegram alerts")
    p.add_argument("--ip", default=settings.DEFAULT_IP)
    p.add_argument("--port", type=int, default=settings.DEFAULT_PORT)
    p.add_argument("--user", help="NVR username (or NVR_USER in .env)")
    p.add_argument("--channels", type=int, nargs="+", default=settings.DEFAULT_CHANNELS)
    p.add_argument("--stream", choices=["sub", "main"], default="sub")
    p.add_argument("--live-template", help="custom RTSP address template if the default does not work")
    p.add_argument("--classes", nargs="+", default=settings.LOG_CLASSES, help="objects to log in Excel")
    p.add_argument("--notify", nargs="+", help="objects alerted everywhere, in or out of a zone (default: person)")
    p.add_argument("--notify-in-zone", nargs="+", default=[], metavar="OBJ",
                   help="objects alerted only when they are INSIDE the zone (alert when they enter it)")
    p.add_argument("--notify-outside-zone", nargs="+", default=[], metavar="OBJ",
                   help="objects alerted only when they are OUTSIDE the zone (or leave it)")
    p.add_argument("--zones", default=settings.ZONE_FILE, help="zone file written by cctv_zone.py")
    p.add_argument("--no-zones", action="store_true", help="ignore the zone file")
    p.add_argument("--zone-mode", choices=["feet", "overlap"], default="feet",
                   help="feet = bottom-middle of the box must be in the zone; overlap = a share of the box")
    p.add_argument("--zone-overlap", type=float, default=0.3, help="share of the box inside the zone (overlap mode)")
    p.add_argument("--zone-hold", type=int, default=3,
                   help="frames an object must stay on the other side of the border before it counts as entered/left")
    p.add_argument("--conf", type=float, default=0.4, help="confidence to START a visit (default for classes not in START_CONF)")
    p.add_argument("--keep-conf", type=float, default=0.2, help="weaker detections still keep an existing visit alive")
    p.add_argument("--min-hits", type=int, default=2, help="appearances needed before a visit counts (removes ghosts)")
    p.add_argument("--merge-seconds", type=float, default=8,
                   help="an object gone shorter than this and back = same visit; gone longer = visit ends")
    p.add_argument("--parked-minutes", type=float, default=30,
                   help="a parked vehicle returning to the same spot within this time continues its old visit")
    p.add_argument("--cooldown", type=float, default=60, help="min seconds between alerts for the same camera + object")
    p.add_argument("--warmup", type=float, default=20,
                   help="objects already in view during the first N seconds of a camera are logged but not alerted")
    p.add_argument("--step", type=int, default=5, help="analyse every N-th frame (5 = about 3 per second)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--device", default=None, help="0 for the first NVIDIA GPU, cpu for CPU")
    p.add_argument("--show", action="store_true", help="preview windows with boxes (q = stop and save)")
    p.add_argument("--minutes", type=float, default=0, help="stop after N minutes (0 = run until stopped)")
    p.add_argument("--out", default=".", help="folder for the Excel file")
    p.add_argument("--env-file", help="path to the .env file (default: .env next to the script or in the current folder)")
    p.add_argument("--no-photo", action="store_true", help="send text-only alerts (no snapshot)")
    p.add_argument("--no-alerts", action="store_true", help="do not send anything to Telegram")
    p.add_argument("--test-telegram", action="store_true", help="send one test message and exit")
    p.add_argument("--performance", action="store_true",
                   help="open a live graph of CPU / RAM / disk / detection speed and log it (compare runs afterwards)")
    p.add_argument("--performance-report", action="store_true",
                   help="print the table of all earlier --performance runs and exit")
    p.add_argument("--test-video", help="use this video file instead of the NVR (for testing)")
    return p.parse_args()


def main():
    """Set everything up, start one thread per camera, save the Excel file when done."""
    args = parse_args()
    env_path = load_env(args.env_file)
    os.makedirs(args.out, exist_ok=True)
    if args.performance_report:
        show_runs(args.out)
        return

    tg = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
                  os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
                  photo=not args.no_photo, enabled=not args.no_alerts or args.test_telegram)
    if args.test_telegram:
        run_telegram_test(tg)
        return

    lower = lambda items: {c.lower() for c in items or []}
    n_any, n_in, n_out = lower(args.notify), lower(args.notify_in_zone), lower(args.notify_outside_zone)
    if not (n_any or n_in or n_out):
        n_any = {"person"}
    n_any |= n_in & n_out                      # wanted both inside and outside = wanted everywhere
    args.notify_any, args.notify_in_only, args.notify_out_only = n_any, n_in - n_any, n_out - n_any
    args.notify_set = n_any | n_in | n_out
    args.classes = [c.lower() for c in args.classes]
    for c in sorted(args.notify_set - set(args.classes)):
        args.classes.append(c)
        print(f"Note: '{c}' was added to the detected objects because you asked for alerts about it.")

    if not args.no_zones:
        found, zpath = zones.load_zones(args.zones)
        zones.ZONES.update(found)
    else:
        zpath = None

    if not args.test_video:
        user = args.user or os.environ.get("NVR_USER") or input("NVR username: ").strip()
        pw = os.environ.get("NVR_PASSWORD") or getpass.getpass("NVR password (hidden): ")
        args.auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@"
    else:
        args.auth = ""

    print(f"Settings file: {env_path or 'none found (.env)'}")
    if args.no_alerts:
        print("Alerts: OFF (--no-alerts). Excel only.")
    elif tg.enabled:
        print(f"Alerts: Telegram ON, {'text only' if args.no_photo else 'with snapshot'}, cooldown {args.cooldown:.0f}s")
        print(f"  everywhere:   {sorted(args.notify_any) or '-'}")
        print(f"  only inside:  {sorted(args.notify_in_only) or '-'}")
        print(f"  only outside: {sorted(args.notify_out_only) or '-'}")
    else:
        print("Alerts: OFF - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not found in .env. Excel only.")
    labels = [cam_label(c) for c in args.channels]
    if zones.ZONES:
        print(f"Zones ({zpath}): with zone {[l for l in labels if l in zones.ZONES]}, "
              f"without zone (work as usual) {[l for l in labels if l not in zones.ZONES]}")
        for l in sorted(set(zones.ZONES) - set(labels)):
            print(f"  Note: {l} has a zone but is not in --channels, so it is not watched.")
    elif args.notify_in_only or args.notify_out_only:
        print("Note: no zones found, so every camera works as usual. Draw one with:  python cctv_zone.py draw 3")
    if args.notify_in_only and zones.ZONES and not any(l in zones.ZONES for l in labels):
        print("Note: --notify-in-zone only alerts on cameras that have a zone.")
    print(f"Cameras: {args.channels}   stream={args.stream}   every {args.step}th frame   model={args.model}")

    YOLO(args.model)                         # download once, before the cameras start
    cfg = make_tracker_cfg(args)
    PREVIEW.enabled = args.show or args.performance
    perf = None
    if args.performance:
        perf = camera.PERF = PerfMonitor(args, args.out)
        print(f"Performance graph ON (log: {perf.csv_path}). Change settings, run again, then compare with --performance-report")
    manager = VisitManager(args, tg)
    out_path = os.path.join(args.out, f"detections_live_{datetime.now():%Y%m%d_%H%M}.xlsx")
    seen = {}

    threads = [threading.Thread(target=live_worker, args=(ch, args, manager, cfg, seen), daemon=True)
               for ch in args.channels]
    for t in threads:
        t.start()
    if tg.enabled:
        tg.send("CCTV alerts started on " + ", ".join(cam_label(c) for c in args.channels) + ".")

    started = time.time()
    deadline = started + args.minutes * 60 if args.minutes else None
    print("Running. Press Ctrl+C" + (" (or q in a window)" if args.show else "") + " to stop and save.")
    last_save, warned, tick = time.time(), set(), 0.0
    try:
        while not STOP.is_set() and (deadline is None or time.time() < deadline):
            if PREVIEW.enabled:
                if perf:
                    PREVIEW.update("Performance", perf.render())
                PREVIEW.pump()
            else:
                time.sleep(0.3)
            if time.time() - tick >= 1.0:
                tick = time.time()
                manager.close_stale(datetime.now())
                if not args.test_video:
                    for ch in args.channels:
                        lab = cam_label(ch)
                        if lab in seen:
                            silent = time.time() - seen[lab] > 60
                            if silent and lab not in warned:
                                print(f"[{lab}] no video for 60 s (still retrying)")
                                warned.add(lab)
                            elif not silent and lab in warned:
                                print(f"[{lab}] video is back")
                                warned.discard(lab)
                        elif time.time() - started > 60 and lab not in warned:
                            print(f"[{lab}] no video after 60 s - check the camera, the NVR password and "
                                  f"the address (still retrying)")
                            warned.add(lab)
                if args.test_video and not any(t.is_alive() for t in threads):
                    time.sleep(args.merge_seconds + 1)
                    manager.close_stale(datetime.now())
                    break
            if time.time() - last_save >= 60:
                out_path, _ = save_excel(manager.rows(), out_path)
                last_save = time.time()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        STOP.set()
        time.sleep(1)
        manager.close_all()
        out_path, count = save_excel(manager.rows(), out_path)
        tg.flush()
        if perf:
            perf.finish()
    print(f"\nDone. {count} visits written to {out_path}")


if __name__ == "__main__":
    main()
