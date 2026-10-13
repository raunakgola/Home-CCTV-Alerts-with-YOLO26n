"""--performance: live CPU / RAM / disk / detection-speed graph, a CSV log, and a table to compare runs."""
import csv
import os
import shutil
import threading
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np
import psutil

from helpers import STOP

HISTORY = 120                 # samples kept on the graph (one per second = the last 2 minutes)
RUNS_FILE = "performance_runs.csv"
RUN_COLUMNS = ["started", "minutes", "cameras", "stream", "step", "imgsz", "device", "preview",
               "avg_cpu_pct", "peak_cpu_pct", "avg_ram_mb", "peak_ram_mb", "avg_infer_ms",
               "frames_analysed_per_sec", "frames_skipped_pct", "verdict"]

# colours (BGR)
BG, GRID, TEXT = (30, 30, 30), (70, 70, 70), (230, 230, 230)
BLUE, ORANGE, GREEN, RED, YELLOW = (255, 160, 60), (60, 160, 255), (110, 200, 90), (80, 80, 240), (60, 220, 240)


class PerfMonitor:
    """Samples the PC once a second and collects how fast each camera is being analysed."""

    def __init__(self, args, out_dir):
        self.a, self.out_dir = args, out_dir
        self.proc = psutil.Process()
        self.cores = psutil.cpu_count() or 1
        self.lock = threading.Lock()
        self.started = datetime.now()
        self.t0 = time.time()
        self.hist = {k: deque(maxlen=HISTORY) for k in ("cpu", "proc_cpu", "ram", "proc_ram", "infer", "skip", "fps")}
        self.all = {k: [] for k in ("cpu", "proc_cpu", "proc_ram", "infer", "skip", "fps")}
        self._infer, self._frames, self._skipped = [], 0, 0      # collected between two samples
        self.total_frames = self.total_skipped = 0
        self.csv_path = os.path.join(out_dir, f"performance_{self.started:%Y%m%d_%H%M}.csv")
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["time", "cpu_pct", "process_cpu_pct", "ram_pct", "process_ram_mb",
                                    "infer_ms", "frames_per_sec", "skipped_pct", "disk_free_gb"])
        psutil.cpu_percent(None)       # the first call only starts the counter
        self.proc.cpu_percent(None)
        self.last_row = {}
        threading.Thread(target=self._sampler, daemon=True).start()

    def record(self, label, infer_seconds, skipped):
        """Called by a camera thread after each analysed frame (skipped = frames it had to drop before this one)."""
        with self.lock:
            self._infer.append(infer_seconds * 1000.0)
            self._frames += 1
            self._skipped += max(0, skipped)

    def _sampler(self):
        """Once a second: read CPU/RAM/disk, turn the collected frame numbers into rates, store everything."""
        while not STOP.wait(1.0):
            cpu = psutil.cpu_percent(None)
            pcpu = self.proc.cpu_percent(None) / self.cores          # share of the WHOLE pc used by this program
            vm = psutil.virtual_memory()
            pram = self.proc.memory_info().rss / 1e6
            free_gb = shutil.disk_usage(self.out_dir).free / 1e9
            with self.lock:
                infer = float(np.mean(self._infer)) if self._infer else 0.0
                n, sk = self._frames, self._skipped
                self._infer, self._frames, self._skipped = [], 0, 0
            skip_pct = 100.0 * sk / (n + sk) if (n + sk) else 0.0
            self.total_frames += n
            self.total_skipped += sk
            row = {"cpu": cpu, "proc_cpu": pcpu, "ram": vm.percent, "proc_ram": pram,
                   "infer": infer, "skip": skip_pct, "fps": float(n)}
            for k, v in row.items():
                self.hist[k].append(v)
                if k in self.all:
                    self.all[k].append(v)
            self.last_row = dict(row, free_gb=free_gb, ram_used_gb=vm.used / 1e9, ram_total_gb=vm.total / 1e9)
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([f"{datetime.now():%H:%M:%S}", f"{cpu:.1f}", f"{pcpu:.1f}", f"{vm.percent:.1f}",
                                        f"{pram:.0f}", f"{infer:.0f}", n, f"{skip_pct:.0f}", f"{free_gb:.1f}"])

    # ------------------------------------------------------------------ drawing
    def verdict(self):
        """One plain sentence: is the PC keeping up with the cameras?"""
        recent = list(self.hist["skip"])[-15:]
        if len(recent) < 5:
            return "measuring...", YELLOW
        if not any(list(self.hist["fps"])[-15:]):
            return "waiting for video from the cameras...", YELLOW
        s = float(np.mean(recent))
        if s < 10:
            return "KEEPING UP - every wanted frame is analysed", GREEN
        if s < 40:
            return f"STRUGGLING - {s:.0f}% of wanted frames skipped (raise --step or use fewer cameras)", YELLOW
        return f"OVERLOADED - {s:.0f}% of wanted frames skipped (raise --step, use sub stream, fewer cameras)", RED

    def _panel(self, img, box, title, series, vmax, unit):
        """Draw one line graph. series = [(history_key, colour, legend)]."""
        x0, y0, x1, y1 = box
        cv2.rectangle(img, (x0, y0), (x1, y1), GRID, 1)
        cv2.putText(img, title, (x0 + 6, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT, 1, cv2.LINE_AA)
        for frac in (0.25, 0.5, 0.75):
            y = int(y1 - frac * (y1 - y0))
            cv2.line(img, (x0, y), (x1, y), (50, 50, 50), 1)
        if vmax:
            top = vmax
        else:        # no fixed maximum: scale to the biggest value seen on this graph
            top = max([max(self.hist[k], default=0) for k, _, _ in series] + [1.0]) * 1.1
        for i, (key, colour, legend) in enumerate(series):
            data = list(self.hist[key])
            pts = []
            for j, v in enumerate(data):
                x = int(x1 - (len(data) - 1 - j) * (x1 - x0) / (HISTORY - 1))
                y = int(y1 - min(v, top) / top * (y1 - y0 - 24))
                pts.append((x, y))
            if len(pts) > 1:
                cv2.polylines(img, [np.array(pts, np.int32)], False, colour, 2, cv2.LINE_AA)
            now = data[-1] if data else 0
            cv2.putText(img, f"{legend}: {now:.0f}{unit}", (x0 + 6, y0 + 36 + 16 * i),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)
        cv2.putText(img, f"{top:.0f}{unit}", (x1 - 60, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, GRID, 1, cv2.LINE_AA)

    def render(self):
        """The whole performance window as one picture."""
        a = self.a
        img = np.full((560, 920, 3), BG, np.uint8)
        text, colour = self.verdict()
        cv2.putText(img, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, colour, 2, cv2.LINE_AA)
        dev = a.device if a.device is not None else "cpu (auto)"
        settings_line = (f"cameras {len(a.channels)} {a.channels} | stream {a.stream} | step {a.step} | imgsz {a.imgsz} | "
                         f"device {dev} | preview {'on' if a.show else 'off'}")
        cv2.putText(img, settings_line, (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT, 1, cv2.LINE_AA)
        self._panel(img, (10, 62, 455, 270), "CPU  (whole PC / this program)",
                    [("cpu", BLUE, "PC total"), ("proc_cpu", ORANGE, "this program")], 100, "%")
        self._panel(img, (465, 62, 910, 270), "RAM  (whole PC % / this program MB)",
                    [("ram", BLUE, "PC used %")], 100, "%")
        # the program's own RAM is in MB, so it gets its own small line on the same box
        mb = list(self.hist["proc_ram"])
        cv2.putText(img, f"this program: {mb[-1] if mb else 0:.0f} MB", (475, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    ORANGE, 1, cv2.LINE_AA)
        self._panel(img, (10, 280, 305, 488), "Detection time per frame",
                    [("infer", GREEN, "avg")], None, " ms")
        self._panel(img, (315, 280, 610, 488), "Frames analysed per second",
                    [("fps", GREEN, "all cameras")], None, "")
        self._panel(img, (620, 280, 910, 488), "Frames skipped (too slow)",
                    [("skip", RED, "skipped")], 100, "%")
        r = self.last_row
        if r:
            cv2.putText(img, f"Storage: {r['free_gb']:.1f} GB free on the drive of '{self.out_dir}'   |   "
                             f"RAM {r['ram_used_gb']:.1f} / {r['ram_total_gb']:.1f} GB   |   {self.cores} CPU threads",
                        (12, 512), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT, 1, cv2.LINE_AA)
        cv2.putText(img, f"Running {int(time.time() - self.t0)} s | log: {os.path.basename(self.csv_path)} | "
                         f"q = stop and save", (12, 536), cv2.FONT_HERSHEY_SIMPLEX, 0.45, GRID, 1, cv2.LINE_AA)
        return img

    # ------------------------------------------------------------------ results
    def summary(self):
        """Averages for the whole run; also appended to performance_runs.csv for comparing settings."""
        a = self.all
        if len(a["cpu"]) < 3:
            return None
        infer = [v for v in a["infer"] if v > 0]
        secs = max(1.0, time.time() - self.t0)
        seen = self.total_frames + self.total_skipped
        skip = 100.0 * self.total_skipped / seen if seen else 0.0
        verdict = "keeping up" if skip < 10 else ("struggling" if skip < 40 else "overloaded")
        args = self.a
        return {
            "started": f"{self.started:%Y-%m-%d %H:%M}", "minutes": round(secs / 60, 1),
            "cameras": " ".join(str(c) for c in args.channels), "stream": args.stream, "step": args.step,
            "imgsz": args.imgsz, "device": args.device if args.device is not None else "cpu",
            "preview": "on" if args.show else "off",
            "avg_cpu_pct": round(float(np.mean(a["cpu"])), 1), "peak_cpu_pct": round(max(a["cpu"]), 1),
            "avg_ram_mb": round(float(np.mean(a["proc_ram"]))), "peak_ram_mb": round(max(a["proc_ram"])),
            "avg_infer_ms": round(float(np.mean(infer))) if infer else 0,
            "frames_analysed_per_sec": round(self.total_frames / secs, 1),
            "frames_skipped_pct": round(skip, 1), "verdict": verdict,
        }

    def finish(self):
        """Print the summary and add it to performance_runs.csv."""
        s = self.summary()
        if not s:
            print("Performance: run was too short to measure.")
            return
        path = os.path.join(self.out_dir, RUNS_FILE)
        new = not os.path.isfile(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=RUN_COLUMNS)
            if new:
                w.writeheader()
            w.writerow(s)
        print("\n=== Performance summary ===")
        print(f"  settings : cameras {s['cameras']} | {s['stream']} stream | step {s['step']} | imgsz {s['imgsz']} | "
              f"device {s['device']} | preview {s['preview']}")
        print(f"  CPU      : average {s['avg_cpu_pct']}%  peak {s['peak_cpu_pct']}%")
        print(f"  RAM      : this program average {s['avg_ram_mb']} MB, peak {s['peak_ram_mb']} MB")
        print(f"  speed    : {s['avg_infer_ms']} ms per frame, {s['frames_analysed_per_sec']} frames analysed per second, "
              f"{s['frames_skipped_pct']}% skipped")
        print(f"  verdict  : {s['verdict']}")
        print(f"  saved    : {self.csv_path}  and a row in {path}")


def show_runs(out_dir):
    """--performance-report: print every earlier run side by side so settings can be compared."""
    path = os.path.join(out_dir, RUNS_FILE)
    if not os.path.isfile(path):
        print(f"No runs recorded yet ({path}). Run with --performance first.")
        return
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    head = f"{'started':16} {'min':>4} {'cams':>10} {'stream':>6} {'step':>4} {'imgsz':>5} {'prev':>4} " \
           f"{'cpu%':>5} {'peak':>5} {'ramMB':>6} {'ms':>5} {'fps':>5} {'skip%':>6}  verdict"
    print(head)
    print("-" * len(head))
    for r in rows:
        print(f"{r['started']:16} {r['minutes']:>4} {r['cameras']:>10} {r['stream']:>6} {r['step']:>4} {r['imgsz']:>5} "
              f"{r['preview']:>4} {r['avg_cpu_pct']:>5} {r['peak_cpu_pct']:>5} {r['avg_ram_mb']:>6} "
              f"{r['avg_infer_ms']:>5} {r['frames_analysed_per_sec']:>5} {r['frames_skipped_pct']:>6}  {r['verdict']}")
