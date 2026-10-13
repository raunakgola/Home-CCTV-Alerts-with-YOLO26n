#!/usr/bin/env python3
"""
playback.py  -  short commands for cctv_yolo.py (recorded footage) with your NVR's address formats built in
==========================================================================================================

cctv_yolo.py is left exactly as it is. This file only adds the long --playback-template / --live-template
options for you and then runs it, so every cctv_yolo.py option still works.

    python playback.py --day 2026-10-06 --from 10:00 --to 10:02 --channels 3 --user admin --show
        = python cctv_yolo.py --mode playback ... --playback-template "rtsp://{auth}{ip}:{port}/chID=..."
    python playback.py probe --day 2026-10-06 --from 10:00     # find out which recording times exist / which URL works
    python playback.py live --channels 1 2 3 --show            # cctv_yolo.py live mode
    python playback.py file --file clip.mp4 --start "2026-10-06 10:00:00" --show

First word (optional): playback (default), probe, live or file.
Add  --print-command  to see the exact command without running it.
"""
import os
import runpy
import sys

# Address formats of the TVT NVR (edit here if your NVR ever changes)
PLAYBACK_TEMPLATE = ("rtsp://{auth}{ip}:{port}/chID={ch}&date={date}&time={time}"
                     "&timelen={timelen}&streamType={stream}&action=playback")
LIVE_TEMPLATE = "rtsp://{auth}{ip}:{port}/chID={ch}&streamType={stream}"

MODES = ("playback", "probe", "live", "file")


def build_command(argv):
    """Turn the short command into the full cctv_yolo.py argument list."""
    mode = "playback"
    if argv and argv[0] in MODES:
        mode, argv = argv[0], argv[1:]
    args = list(argv)
    if "--mode" not in args:
        args = ["--mode", mode] + args
    if "--playback-template" not in args:
        args += ["--playback-template", PLAYBACK_TEMPLATE]
    if "--live-template" not in args:
        args += ["--live-template", LIVE_TEMPLATE]
    return args


def main():
    """Build the full argument list, then run cctv_yolo.py with it."""
    argv = sys.argv[1:]
    show_only = "--print-command" in argv
    argv = [a for a in argv if a != "--print-command"]
    full = build_command(argv)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cctv_yolo.py")
    if show_only:
        print("python cctv_yolo.py " + " ".join(f'"{a}"' if ("{" in a or " " in a) else a for a in full))
        return
    if not os.path.isfile(script):
        sys.exit("cctv_yolo.py must be in the same folder as playback.py")
    sys.argv = [script] + full
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
