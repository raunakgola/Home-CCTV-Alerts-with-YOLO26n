"""Camera side: read the stream, run YOLO + ByteTrack on each frame, draw boxes, preview windows."""
import threading
import time
from datetime import datetime

import cv2
from ultralytics import YOLO

import settings
from helpers import STOP, cam_label, class_ids
from zones import draw_zone_overlay, zone_place

# --------------------------------------------------------------------------
class Preview:
    """Shows the live boxes in OpenCV windows (windows must be drawn from the main thread)."""
    def __init__(self):
        self.enabled = False
        self.frames, self.slots = {}, {}
        self.lock = threading.Lock()

    def update(self, label, img):
        """Store the newest picture for one camera."""
        if self.enabled:
            with self.lock:
                self.frames[label] = img

    def pump(self):
        """Show the stored pictures and watch for the q key."""
        if not self.enabled:
            return
        with self.lock:
            items = list(self.frames.items())
        try:
            for label, img in items:
                if label not in self.slots:
                    i = self.slots[label] = len(self.slots)
                    cv2.namedWindow(label, cv2.WINDOW_NORMAL)
                    if label == "Performance":
                        cv2.resizeWindow(label, 920, 560)
                        cv2.moveWindow(label, 0, 0)
                        continue
                    cv2.moveWindow(label, (i % 3) * 360, (580 if PERF else 0) + (i // 3) * 330)
                    cv2.resizeWindow(label, 352, 288)
                cv2.imshow(label, img)
            key = cv2.waitKey(30) & 0xFF
        except cv2.error as e:
            print(f"Cannot open preview windows ({e}). Continuing without --show.")
            self.enabled = False
            return
        if key in (ord("q"), 27):
            print("Preview closed - stopping and saving.")
            STOP.set()


PREVIEW = Preview()
PERF = None          # set to a PerfMonitor by --performance


def draw(frame, items, label, ts):
    """Return a copy of the frame with the boxes, the zone and the camera name/time painted on."""
    img = frame.copy()
    for (x1, y1, x2, y2), text, known in items:
        color = (0, 255, 0) if known else (0, 165, 255)
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        cv2.putText(img, text, (int(x1), max(int(y1) - 5, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    color, 1, cv2.LINE_AA)
    img = draw_zone_overlay(img, label)
    cv2.putText(img, f"{label}  {ts:%Y-%m-%d %H:%M:%S}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 255, 255), 2, cv2.LINE_AA)
    return img


# --------------------------------------------------------------------------
# camera reading + detection
# --------------------------------------------------------------------------
class LiveReader(threading.Thread):
    """Reads the stream continuously and keeps only the newest sampled frame (no lag builds up)."""

    def __init__(self, url, step, label, seen, paced=False):
        super().__init__(daemon=True)
        self.url, self.step, self.label, self.seen, self.paced = url, step, label, seen, paced
        self.frame, self.seq, self.finished = None, 0, False
        self.lock = threading.Lock()

    def run(self):
        """Keep reading the stream; reconnect if it drops."""
        while not STOP.is_set():
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                time.sleep(5)
                continue
            fps = cap.get(cv2.CAP_PROP_FPS)
            fps = fps if 1 <= fps <= 120 else settings.NOMINAL_FPS
            n = 0
            while not STOP.is_set() and cap.grab():
                if self.paced:                      # test video: play at normal speed
                    time.sleep(1.0 / fps)
                if n % self.step == 0:
                    ok, f = cap.retrieve()
                    if ok:
                        self.seen[self.label] = time.time()
                        with self.lock:
                            self.frame, self.seq = f, self.seq + 1
                n += 1
            cap.release()
            if self.paced:
                self.finished = True
                return
            time.sleep(2)                           # stream dropped -> reconnect


class CameraDetector:
    """One YOLO model + tracker per camera, so track ids never mix between cameras."""
    def __init__(self, label, args, manager, tracker_cfg):
        self.label, self.a, self.manager, self.cfg = label, args, manager, tracker_cfg
        self.model = YOLO(args.model)
        self.ids = class_ids(self.model, args.classes)

    def process(self, frame, ts):
        """Detect and track one frame, work out in/out of zone, and hand the result to the VisitManager."""
        a = self.a
        r = self.model.track(frame, persist=True, tracker=self.cfg, conf=a.keep_conf, imgsz=a.imgsz,
                             classes=self.ids, device=a.device, verbose=False)[0]
        dets = []
        boxes = r.boxes
        if boxes is not None and len(boxes):
            ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
            for xyxy, tid, c, cf in zip(boxes.xyxy.tolist(), ids, boxes.cls.int().tolist(), boxes.conf.tolist()):
                dets.append({"tid": tid, "cls": self.model.names[c], "box": tuple(xyxy), "conf": cf})
        for d in dets:
            d["place"] = zone_place(self.label, d["box"], frame.shape[:2], a.zone_mode, a.zone_overlap)
        tracked = [d for d in dets if d["tid"] is not None]

        def snapshot():
            """Make the JPEG that goes with a Telegram alert."""
            items = [(d["box"], f'{d["cls"]} {d["conf"]:.2f}', True) for d in dets]
            ok, buf = cv2.imencode(".jpg", draw(frame, items, self.label, ts), [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buf.tobytes() if ok else None

        shown = self.manager.update(self.label, ts, tracked, snapshot)
        if a.show:
            items = []
            for d in dets:
                v = shown.get(d["tid"])
                tag = f' V{v.id}' if v is not None else ""
                if d["place"] == "in":
                    tag += " [zone]"
                items.append((d["box"], f'{d["cls"]} {d["conf"]:.2f}{tag}', v is not None))
            PREVIEW.update(self.label, draw(frame, items, self.label, ts))


def live_worker(ch, args, manager, cfg, seen):
    """Thread body for one camera: read frames, process them, never stop on a single bad frame."""
    label = cam_label(ch)
    det = CameraDetector(label, args, manager, cfg)
    if args.test_video:
        reader = LiveReader(args.test_video, args.step, label, seen, paced=True)
    else:
        url = settings.LIVE_TEMPLATE.format(auth=args.auth, ip=args.ip, port=args.port, ch=ch, stream=args.stream)
        if args.live_template:
            url = args.live_template.format(auth=args.auth, ip=args.ip, port=args.port, ch=ch, stream=args.stream)
        reader = LiveReader(url, args.step, label, seen)
    reader.start()
    last, last_err, first = 0, 0.0, True
    while not STOP.is_set():
        with reader.lock:
            frame, seq = reader.frame, reader.seq
        if frame is None or seq == last:
            if reader.finished:
                return
            time.sleep(0.05)
            continue
        skipped, last = seq - last - 1, seq        # frames we were too slow to look at
        try:
            t_start = time.time()
            det.process(frame, datetime.now())
            if PERF is not None:
                PERF.record(label, time.time() - t_start, 0 if first else skipped)
            first = False
        except Exception as e:      # keep running 24/7 even if one frame fails
            if time.time() - last_err > 30:
                print(f"[{label}] processing error: {type(e).__name__}: {e}")
                last_err = time.time()
            time.sleep(0.5)
