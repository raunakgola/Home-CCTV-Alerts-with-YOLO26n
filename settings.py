"""Things you may want to edit: NVR address, camera names, which objects count as what."""

DEFAULT_IP = "192.168.1.250"              # the fixed IP of the NVR
DEFAULT_PORT = 554                        # RTSP port from the NVR's Port tab
DEFAULT_CHANNELS = [1, 2, 3, 4, 5, 6]     # camera 7 is offline
CAMERA_NAMES = {                          # optional friendly names, e.g. 1: "Main lane"
    # 1: "Main lane",
}
LIVE_TEMPLATE = "rtsp://{auth}{ip}:{port}/chID={ch}&streamType={stream}"
NOMINAL_FPS = 15                          # your NVR streams at 15 fps

# What gets logged to Excel (override with --classes). Names are the COCO class names.
LOG_CLASSES = ["person", "bicycle", "motorcycle", "car", "bus", "truck", "dog", "cat"]
# Confidence needed to START a visit. Lower for things that flicker (motorcycles).
# Anything else uses --conf. Once a visit exists, weaker detections (--keep-conf) keep it alive.
START_CONF = {"person": 0.45, "motorcycle": 0.30, "bicycle": 0.30}
# Objects that can sit still for hours; if they flicker away and return to the same spot,
# the old visit is continued instead of starting a new one.
PARKABLE = {"motorcycle", "bicycle", "car", "bus", "truck"}
ZONE_FILE = "zones.json"                  # written by cctv_zone.py
