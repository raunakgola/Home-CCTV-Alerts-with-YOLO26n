"""Zones: read zones.json (drawn with cctv_zone.py) and decide whether a box is inside one."""
import json
import os

import cv2
import numpy as np

ZONES = {}                 # camera label -> [(x, y), ...] as fractions 0..1 of the picture
_mask_cache = {}


def load_zones(path):
    """Read zones.json (current folder first, then next to this script). Bad or tiny shapes are ignored."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in ([path] if os.path.isabs(path) else [os.path.join(os.getcwd(), path), os.path.join(here, path)]):
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8-sig") as f:
            raw = json.load(f)
        zones = {}
        for label, pts in raw.items():
            pts = [(float(x), float(y)) for x, y in pts]
            if len(pts) >= 3:
                zones[label] = pts
        return zones, p
    return {}, None


def zone_place(label, box, shape, mode="feet", overlap=0.3):
    """'in' / 'out' for a camera that has a zone, None for a camera without one."""
    pts = ZONES.get(label)
    if not pts:
        return None
    h, w = shape
    poly = np.array([[x * w, y * h] for x, y in pts], dtype=np.float32)
    x1, y1, x2, y2 = box
    if mode == "feet":      # bottom-middle of the box = where the object stands
        foot = ((x1 + x2) / 2.0, min(max(y2, 0), h - 1))
        return "in" if cv2.pointPolygonTest(poly.reshape(-1, 1, 2), foot, False) >= 0 else "out"
    key = (label, h, w)     # overlap: share of the box that lies inside the zone
    if key not in _mask_cache:
        m = np.zeros((h, w), np.uint8)
        cv2.fillPoly(m, [poly.astype(np.int32)], 1)
        _mask_cache[key] = m
    ix1, iy1, ix2, iy2 = max(int(x1), 0), max(int(y1), 0), min(int(x2), w), min(int(y2), h)
    if ix2 <= ix1 or iy2 <= iy1:
        return "out"
    share = _mask_cache[key][iy1:iy2, ix1:ix2].sum() / float((ix2 - ix1) * (iy2 - iy1))
    return "in" if share >= overlap else "out"


def draw_zone_overlay(img, label):
    """Paint the camera's zone as a light blue area with an outline (does nothing without a zone)."""
    if label not in ZONES:
        return img
    h, w = img.shape[:2]
    poly = np.array([[x * w, y * h] for x, y in ZONES[label]], dtype=np.int32)
    shade = img.copy()
    cv2.fillPoly(shade, [poly], (255, 120, 0))
    img = cv2.addWeighted(shade, 0.18, img, 0.82, 0)
    cv2.polylines(img, [poly], True, (255, 120, 0), 2, cv2.LINE_AA)
    return img
