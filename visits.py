"""Visits: one object present in one camera, from first to last sighting, plus the alert rules."""
import math
import threading

from helpers import center, diag, iou
from settings import PARKABLE, START_CONF

# --------------------------------------------------------------------------
# visits: one object present in one camera, from first to last sighting
# --------------------------------------------------------------------------
class Visit:
    """One object seen in one camera, from first to last sighting."""
    def __init__(self, vid, cam, cls, ts, box, conf, warm):
        self.id, self.cam, self.cls = vid, cam, cls
        self.first = self.last = ts
        self.box = box
        self.first_center = center(box)
        self.diag = diag(box)
        self.max_disp = 0.0
        self.hits = 1
        self.best = conf
        self.confirmed = False
        self.closed = False
        self.warm = warm          # already in view when the script started
        self.returns = 0          # times a parked object came back after disappearing
        self.place = None         # 'in' / 'out' of the camera's zone (None = camera has no zone)
        self.pending = None       # a different place seen in the last few frames, not yet accepted
        self.pending_n = 0
        self.zone_seconds = 0.0   # time spent inside the zone
        self.zone_entries = 0     # how many times it stepped into the zone

    def seconds(self):
        """How long the visit lasted."""
        return (self.last - self.first).total_seconds()

    def note(self):
        """Short text for the Excel Note column."""
        parts = []
        if self.warm:
            parts.append("present at start")
        if self.seconds() >= 20 and self.max_disp < 0.3 * self.diag:
            parts.append("stationary")
        if self.returns:
            parts.append(f"re-detected {self.returns}x")
        if self.zone_entries:
            parts.append(f"entered zone {self.zone_entries}x")
        if not self.closed:
            parts.append("ongoing")
        return ", ".join(parts)


class VisitManager:
    """Turns per-frame detections into visits and decides which ones deserve a Telegram alert."""
    def __init__(self, args, telegram):
        self.a, self.tg = args, telegram
        self.lock = threading.RLock()
        self.visits = []          # every visit (confirmed or still pending)
        self.active = {}          # camera -> visits currently open
        self.parked = {}          # camera -> recently closed parkable visits (can be re-opened)
        self.tid_map = {}         # (camera, tracker id) -> visit
        self.cam_start = {}       # camera -> time of its first processed frame
        self.last_alert = {}      # (camera, object, kind) -> time of last alert
        self.suppressed = {}      # (camera, object, kind) -> alerts skipped during cooldown
        self.next_id = 1

    def start_conf(self, cls):
        """Confidence needed to start a visit for this kind of object."""
        return START_CONF.get(cls, self.a.conf)

    def update(self, cam, ts, dets, snapshot_fn):
        """dets: list of dicts(tid, cls, box, conf). Returns {tid: Visit or None} for drawing."""
        with self.lock:
            self.cam_start.setdefault(cam, ts)
            self.active.setdefault(cam, [])
            matched, out, rest = set(), {}, []
            for d in dets:   # 1) tracker ids we already know
                v = self.tid_map.get((cam, d["tid"]))
                if v is not None and not v.closed and v.cls == d["cls"] and v.id not in matched:
                    self._touch(v, ts, d, snapshot_fn)
                    matched.add(v.id)
                    out[d["tid"]] = v
                else:
                    rest.append(d)
            for d in sorted(rest, key=lambda x: -x["conf"]):
                v = self._find_recent(cam, ts, d, matched)      # 2) same object, lost for a moment
                if v is None:
                    v = self._find_parked(cam, ts, d, matched)  # 3) parked object came back
                if v is not None:
                    self.tid_map[(cam, d["tid"])] = v
                    self._touch(v, ts, d, snapshot_fn)
                else:                                           # 4) genuinely new
                    if d["conf"] < self.start_conf(d["cls"]):
                        out[d["tid"]] = None
                        continue
                    v = self._new(cam, ts, d, snapshot_fn)
                matched.add(v.id)
                out[d["tid"]] = v
            return out

    def _touch(self, v, ts, d, snapshot_fn):
        """Update a visit with a new sighting (and follow it across the zone border)."""
        if v.place == "in":       # count the time spent inside the zone (a long gap counts as the merge limit)
            v.zone_seconds += min((ts - v.last).total_seconds(), self.a.merge_seconds)
        v.last, v.box = ts, d["box"]
        self._track_zone(v, ts, d.get("place"), snapshot_fn)
        v.hits += 1
        v.best = max(v.best, d["conf"])
        v.max_disp = max(v.max_disp, math.dist(center(d["box"]), v.first_center))
        if not v.confirmed and v.hits >= self.a.min_hits:
            self._confirm(v, ts, snapshot_fn)

    def _new(self, cam, ts, d, snapshot_fn):
        """Start a new visit."""
        warm = (ts - self.cam_start[cam]).total_seconds() < self.a.warmup
        v = Visit(self.next_id, cam, d["cls"], ts, d["box"], d["conf"], warm)
        v.place = d.get("place")
        self.next_id += 1
        self.visits.append(v)
        self.active[cam].append(v)
        self.tid_map[(cam, d["tid"])] = v
        if self.a.min_hits <= 1:
            self._confirm(v, ts, snapshot_fn)
        return v

    def _find_recent(self, cam, ts, d, matched):
        """Find an open visit of the same object that was lost a moment ago."""
        best, best_dist = None, None
        for v in self.active.get(cam, []):
            if v.cls != d["cls"] or v.id in matched:
                continue
            gap = (ts - v.last).total_seconds()
            if gap < 0 or gap > self.a.merge_seconds:
                continue
            dist = math.dist(center(v.box), center(d["box"]))
            allowed = max(diag(v.box), diag(d["box"])) * (1.0 + 0.3 * gap)
            if dist <= allowed and (best is None or dist < best_dist):
                best, best_dist = v, dist
        return best

    def _find_parked(self, cam, ts, d, matched):
        """Find a parked vehicle's old visit if it returned to the same spot."""
        if d["cls"] not in PARKABLE:
            return None
        window = self.a.parked_minutes * 60
        keep = [v for v in self.parked.get(cam, []) if (ts - v.last).total_seconds() <= window]
        found = next((v for v in keep if v.cls == d["cls"] and iou(v.box, d["box"]) >= 0.5), None)
        if found is not None:
            keep.remove(found)
            found.closed = False
            found.returns += 1
            self.active[cam].append(found)
        self.parked[cam] = keep
        return found

    def _wants(self, cls, kind, place):
        """Does the person want a Telegram message for this object, event and place?"""
        a = self.a
        if kind == "arrival":
            return (cls in a.notify_any
                    or (place == "in" and cls in a.notify_in_only)
                    or (place != "in" and cls in a.notify_out_only))   # a camera without a zone counts as 'outside'
        if kind == "entered":
            return cls in a.notify_in_only
        return cls in a.notify_out_only                                 # kind == "left"

    def _track_zone(self, v, ts, place, snapshot_fn):
        """Follow an object across the zone border; a change must last --zone-hold frames to count."""
        if place is None:
            return
        if v.place is None:
            v.place = place
            return
        if place == v.place:
            v.pending, v.pending_n = None, 0
            return
        v.pending_n = v.pending_n + 1 if v.pending == place else 1
        v.pending = place
        if v.pending_n < self.a.zone_hold:
            return
        v.place, v.pending, v.pending_n = place, None, 0
        if place == "in":
            v.zone_entries += 1
        in_warmup = (ts - self.cam_start[v.cam]).total_seconds() < self.a.warmup
        if v.confirmed and not in_warmup:
            self._alert(v, ts, "entered" if place == "in" else "left", snapshot_fn)

    def _confirm(self, v, ts, snapshot_fn):
        """A visit has been seen often enough: log it and maybe alert."""
        v.confirmed = True
        tag = "  (already there at start - no alert)" if v.warm else ""
        where = {"in": "  [in zone]", "out": "  [outside zone]"}.get(v.place, "")
        print(f"[{ts:%H:%M:%S}] {v.cam}: {v.cls} - visit #{v.id}{where}{tag}")
        if not v.warm:
            self._alert(v, ts, "arrival", snapshot_fn)

    def _alert(self, v, ts, kind, snapshot_fn):
        """Send one Telegram message (if wanted and not in cooldown) for an arrival / entered / left event."""
        if not self._wants(v.cls, kind, v.place if kind == "arrival" else None):
            return
        key = (v.cam, v.cls, kind)
        last = self.last_alert.get(key)
        if last is not None and (ts - last).total_seconds() < self.a.cooldown:
            self.suppressed[key] = self.suppressed.get(key, 0) + 1
            return
        skipped = self.suppressed.pop(key, 0)
        self.last_alert[key] = ts
        name = v.cls.capitalize()
        if kind == "arrival":
            text = (f"ALERT: {name} detected\nCamera: {v.cam}\n"
                    f"First seen: {v.first:%Y-%m-%d %H:%M:%S}\nConfidence: {v.best:.2f}")
            if v.place:
                text += f"\nArea: {'inside' if v.place == 'in' else 'outside'} the zone"
        else:
            text = (f"ALERT: {name} {'entered' if kind == 'entered' else 'left'} the zone\nCamera: {v.cam}\n"
                    f"Time: {ts:%Y-%m-%d %H:%M:%S}\nConfidence: {v.best:.2f}")
        if skipped:
            text += f"\n(+{skipped} more {v.cls} alert(s) of this kind during the last {self.a.cooldown:.0f} s were skipped)"
        jpg = snapshot_fn() if (self.tg.enabled and self.tg.photo and snapshot_fn) else None
        self.tg.send(text, jpg)
        if self.tg.enabled:
            print(f"    alert queued for Telegram: {v.cam} / {v.cls} / {kind}")

    def _close(self, cam, v):
        """End a visit (ghosts that never confirmed are dropped)."""
        self.active[cam].remove(v)
        v.closed = True
        if not v.confirmed:
            self.visits.remove(v)                       # a ghost that never got confirmed
        elif v.cls in PARKABLE:
            self.parked.setdefault(cam, []).append(v)

    def close_stale(self, now):
        """End visits not seen for longer than --merge-seconds."""
        with self.lock:
            for cam, act in self.active.items():
                for v in list(act):
                    if (now - v.last).total_seconds() > self.a.merge_seconds:
                        self._close(cam, v)

    def close_all(self):
        """End every open visit (used on shutdown)."""
        with self.lock:
            for cam, act in self.active.items():
                for v in list(act):
                    self._close(cam, v)

    def rows(self):
        """All confirmed visits in time order, for the Excel file."""
        with self.lock:
            return sorted((v for v in self.visits if v.confirmed), key=lambda v: (v.first, v.id))
