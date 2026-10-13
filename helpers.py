"""Small shared helpers: names, box maths, the .env reader, class ids and the ByteTrack settings."""
import math
import os
import sys
import threading

from settings import CAMERA_NAMES, NOMINAL_FPS


def cam_label(ch):
    """Camera name used in messages and in Excel (e.g. 'Camera 3')."""
    return CAMERA_NAMES.get(ch, f"Camera {ch}")


def center(b):
    """Middle point of a box."""
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def diag(b):
    """Diagonal length of a box (a handy 'size' measure)."""
    return math.hypot(b[2] - b[0], b[3] - b[1])


def iou(a, b):
    """How much two boxes overlap, from 0 (not at all) to 1 (identical)."""
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def fmt_dur(sec):
    """Seconds as h:mm:ss."""
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


def load_env(path=None):
    """Read KEY=VALUE lines from a .env file into os.environ (real environment variables win)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [path] if path else [os.path.join(os.getcwd(), ".env"), os.path.join(here, ".env")]
    for p in candidates:
        if not (p and os.path.isfile(p)):
            continue
        raw = open(p, "rb").read()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            os.environ.setdefault(key, val)
        return p
    return None


def class_ids(model, wanted):
    """Turn class names (person, dog...) into the model's numeric ids."""
    by_name = {v.lower(): k for k, v in model.names.items()}
    ids = []
    for w in wanted:
        if w.lower() not in by_name:
            sys.exit(f"Unknown class '{w}'. Known classes: {', '.join(model.names.values())}")
        ids.append(by_name[w.lower()])
    return ids


def make_tracker_cfg(args):
    """Copy Ultralytics' ByteTrack settings and let lost tracks live longer (fewer ID switches)."""
    import yaml
    from ultralytics.utils import ROOT
    with open(ROOT / "cfg" / "trackers" / "bytetrack.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    updates_per_sec = NOMINAL_FPS / max(1, args.step)
    cfg["track_buffer"] = max(15, int(args.merge_seconds * updates_per_sec * 1.5))
    cfg["track_low_thresh"] = min(args.keep_conf, cfg.get("track_high_thresh", 0.25) - 0.01)
    path = os.path.join(args.out, "bytetrack_tuned.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)
    return path

STOP = threading.Event()   # set by Ctrl+C or by pressing q in a preview window
