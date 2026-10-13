# Commands and options

Every command, with one or two lines on what it does. Back to the [README](README.md).

Run everything from the project folder with the virtual environment active (`.venv\Scripts\activate`, made with `uv venv`; packages installed with `uv pip install -r requirements.txt`). Lists of values are separated by spaces, not commas: `--channels 1 3 4`.

**Contents:** [Quick recipes](#quick-recipes) · [cctv_alert_live.py](#cctv_alert_livepy-live-detection-and-alerts) · [cctv_zone.py](#cctv_zonepy-draw-zones) · [playback.py / cctv_yolo.py](#playbackpy-and-cctv_yolopy-recorded-footage) · [Performance](#performance-monitor) · [Alert rules](#how-the-alert-lists-decide) · [Features](#all-features) · [Settings and .env](#settings-and-env) · [Keys](#keyboard)

---

## Quick recipes

| I want to... | Command |
|---|---|
| Check that every camera sends video | `python test_live.py` |
| Check the Telegram bot | `python cctv_alert_live.py --test-telegram` |
| Test all cameras, no alerts | `python cctv_alert_live.py --channels 1 2 3 4 5 6 --show --no-alerts --minutes 2` |
| Run live and leave it | `python cctv_alert_live.py` |
| Run live and watch it | `python cctv_alert_live.py --show` |
| Only some cameras | `python cctv_alert_live.py --channels 1 3 4` |
| Alert for people and motorcycles | `python cctv_alert_live.py --notify person motorcycle` |
| Draw a zone on camera 3 | `python cctv_zone.py draw 3` |
| People outside the zone, cows and dogs inside it | `python cctv_alert_live.py --notify-outside-zone person --notify-in-zone cow dog --show` |
| Excel only, nothing sent | `python cctv_alert_live.py --no-alerts` |
| Text alerts, no photos | `python cctv_alert_live.py --no-photo` |
| See how heavy it is on the PC | `python cctv_alert_live.py --performance --no-alerts --show` |
| Compare earlier performance runs | `python cctv_alert_live.py --performance-report` |
| Analyse recorded footage | `python playback.py --day 2026-10-12 --from 10:00 --to 10:02 --channels 3 --user admin --show` |
| Find which recordings the NVR has | `python playback.py probe --day 2026-10-12 --from 10:00` |
| Try it on a video file, no NVR | `python cctv_alert_live.py --test-video clip.mp4 --channels 1 --warmup 0 --minutes 1` |

---

## cctv_alert_live.py: live detection and alerts

The main program. It reads the live cameras, finds objects, logs visits to Excel and sends Telegram alerts. `python cctv_alert_live.py -h` prints the same list.

### Connection

| Option | Default | What it does |
|---|---|---|
| `--ip IP` | from `settings.py` | Address of the NVR. |
| `--port N` | `554` | RTSP port of the NVR. |
| `--user NAME` | from `.env` (`NVR_USER`) | NVR login name. If missing, you are asked. |
| `--channels 1 2 3` | `1 2 3 4 5 6` | Which cameras to open. Any number of them. Camera 7 is left out because it is offline. |
| `--stream sub` or `main` | `sub` | `sub` is the small, fast picture. `main` is the big one: more detail, much more CPU. |
| `--live-template TEXT` | built in | Your own RTSP address pattern, if the default does not work. Uses `{auth}`, `{ip}`, `{port}`, `{ch}`, `{stream}`. |
| `--env-file PATH` | `.env` in the current or script folder | Read the settings from another file. |

### What to detect and who gets an alert

| Option | Default | What it does |
|---|---|---|
| `--classes A B` | person, bicycle, motorcycle, car, bus, truck, dog, cat | Objects that are detected and written to Excel. Names are the COCO names (`person`, `cow`, `dog`...). Anything you put in a notify list is added automatically. |
| `--notify A B` | `person` (only if no notify list is given) | Alert when these appear **anywhere**, in or out of a zone. |
| `--notify-in-zone A B` | none | Alert only when these are **inside** a zone, including when they walk into it. |
| `--notify-outside-zone A B` | none | Alert only when these are **outside** a zone, including when they leave it. |

### Zones

| Option | Default | What it does |
|---|---|---|
| `--zones FILE` | `zones.json` | The zone file written by `cctv_zone.py`. |
| `--no-zones` | off | Ignore the zone file, so every camera works as if it had no zone. |
| `--zone-mode feet` or `overlap` | `feet` | How "inside" is decided. `feet` uses the bottom-middle of the box (where the object stands), best for ground areas. `overlap` uses the share of the box inside the zone, better for things on a table or counter. |
| `--zone-overlap 0.3` | `0.3` | In overlap mode, the share of the box (0 to 1) that must be inside. |
| `--zone-hold 3` | `3` | Frames an object must stay across the border before it counts as having entered or left. Stops one-frame flicker from sending alerts. |

### Tuning the visits

| Option | Default | What it does |
|---|---|---|
| `--conf 0.4` | `0.4` | Confidence needed to **start** a visit. People need 0.45 and motorcycles/bicycles 0.30 (set in `settings.py`). |
| `--keep-conf 0.2` | `0.2` | Weaker detections still **keep** an existing visit alive. Fewer broken visits. |
| `--min-hits 2` | `2` | How many analysed frames an object must appear in before it counts. Removes one-frame ghosts. |
| `--merge-seconds 8` | `8` | Gone for less than this and back means the same visit. Gone longer means the visit ends. |
| `--parked-minutes 30` | `30` | A parked vehicle that returns to the same spot within this time continues its old visit. |
| `--cooldown 60` | `60` | Minimum seconds between alerts of the same kind for the same camera and object. Skipped ones are counted in the next alert. |
| `--warmup 20` | `20` | Objects already in view during the first N seconds of a camera are logged but not alerted. Use `--warmup 0` to alert for them too. |

### Speed and model

| Option | Default | What it does |
|---|---|---|
| `--step 5` | `5` | Analyse every Nth frame. With 15 fps cameras, 5 means about 3 per second. A bigger number uses less CPU. |
| `--imgsz 640` | `640` | Picture size given to the model. Use `960` for `--stream main`. |
| `--model FILE` | `yolo26n.pt` | The YOLO model file. Downloaded on the first run. |
| `--device 0` or `cpu` | automatic | `0` uses the first NVIDIA GPU, `cpu` forces the CPU. |

### Output and running

| Option | Default | What it does |
|---|---|---|
| `--show` | off | One preview window per camera with boxes. Zones are drawn in blue. `q` stops and saves. |
| `--minutes N` | `0` (forever) | Stop automatically after N minutes. |
| `--out FOLDER` | `.` | Folder for the Excel file and performance files. |
| `--no-photo` | off | Send text-only alerts. No picture leaves your home. |
| `--no-alerts` | off | Send nothing to Telegram. Excel only. |
| `--test-telegram` | off | Send one test message and exit. |
| `--test-video FILE` | none | Use a video file instead of the NVR, to try things out. |
| `--performance` | off | Open the live performance graph and log it. See [Performance](#performance-monitor). |
| `--performance-report` | off | Print the table of all earlier performance runs and exit. |

---

## cctv_zone.py: draw zones

Only creates and manages zones. The alerts themselves come from `cctv_alert_live.py`.

| Command | What it does |
|---|---|
| `python cctv_zone.py draw 3` | Opens a picture from camera 3. Click the corners of the area. |
| `python cctv_zone.py draw 3 --from clip.mp4` | Draw on a picture or video file instead of the live camera. |
| `python cctv_zone.py list` | Shows which cameras have a zone. |
| `python cctv_zone.py remove 3` | Deletes the zone of camera 3. |

`draw` also accepts `--zones FILE`, `--ip`, `--port`, `--user`, `--stream sub|main` and `--live-template`, with the same meaning as above.

**In the drawing window:** left click adds a corner (3 or more), right click removes the last one, `r` starts again, Enter or `s` saves, `q` or Esc cancels. To delete a zone from the window, press `r` and then Enter.

The zone is stored in `zones.json` as fractions of the picture (0 to 1), so it still fits if you change between the sub and main stream. A zone needs at least 3 corners.

---

## playback.py and cctv_yolo.py: recorded footage

`cctv_yolo.py` is the original tool. It analyses recorded footage from the NVR, a video file or the live streams, and writes one Excel file with Camera, Object and First seen. It has no Telegram alerts and no zones.

`playback.py` runs `cctv_yolo.py` and adds your NVR's two long address options for you. Every `cctv_yolo.py` option works with it.

```powershell
python playback.py --day 2026-10-12 --from 10:00 --to 10:02 --channels 3 --user admin --show
python playback.py probe --day 2026-10-12 --from 10:00
python playback.py live --channels 1 2 3 --show
python playback.py file --file clip.mp4 --start "2026-10-12 10:00:00" --camera "Camera 1"
python playback.py --day 2026-10-12 --from 10:00 --to 10:02 --print-command
```

The first word is the mode: `playback` (the default if you leave it out), `probe`, `live` or `file`. `--print-command` shows the full `cctv_yolo.py` command without running it.

| Mode | What it does |
|---|---|
| `playback` | Analyses the NVR's recordings for one day and time range. |
| `probe` | Tests which recording address format and times the NVR accepts. Run this first if playback finds nothing. |
| `live` | Analyses the live streams and writes an Excel file when you stop. |
| `file` | Analyses a video file you exported. Needs `--file` and `--start`. |

| Option | Default | What it does |
|---|---|---|
| `--day YYYY-MM-DD` | none | The day of the recording (playback and probe). |
| `--from HH:MM` / `--to HH:MM` | none | Time range. `24:00` means midnight. |
| `--channels 1 2 3` | `1` to `7` | Which cameras. |
| `--stream sub` or `main` | `sub` | `sub` is 704x576 (fast), `main` is 2560x1440 (slow, more detail). |
| `--file FILE`, `--start "YYYY-MM-DD HH:MM:SS"`, `--camera NAME` | none | For `file` mode: the video, the real time it started, and the camera label. |
| `--ip`, `--port`, `--user` | NVR address, `554`, from `.env` | Connection, as above. |
| `--step N` | `5` | Analyse every Nth frame. |
| `--imgsz N` | `640` | Model picture size (`960` for the main stream). |
| `--conf X` | `0.4` | Minimum confidence. |
| `--classes A B` | all objects | Only these objects, for example `person car motorcycle`. |
| `--min-hits N` | `2` | An object must appear in at least N analysed frames. |
| `--model FILE`, `--device 0` or `cpu` | `yolo26n.pt`, automatic | Model file and processor. |
| `--workers N` | `1` | Cameras processed in parallel during playback. |
| `--minutes N` | `0` | Stop live mode after N minutes. |
| `--fps N` | from the video | Override the video speed used for timestamps. |
| `--show` | off | One preview window per camera. `q` stops and saves. With `--show`, playback cannot run faster than real time. |
| `--out FOLDER` | `.` | Folder for the Excel file. |
| `--playback-template`, `--live-template` | built in (`playback.py` fills your NVR's) | The RTSP address patterns. |

Output files are named like `detections_2026-10-12_1000-1002.xlsx` (playback) and `detections_live_<date>_<time>.xlsx` (live).

---

## Performance monitor

```powershell
python cctv_alert_live.py --performance --no-alerts --channels 1 2 3 --show
python cctv_alert_live.py --performance-report
```

`--performance` opens a window that updates every second and shows the last two minutes:

| Graph | Meaning |
|---|---|
| CPU | The whole PC, and the share used by this program. |
| RAM | The whole PC in percent, and this program in MB. |
| Detection time per frame | How long one analysis takes, in ms. |
| Frames analysed per second | Across all cameras. |
| Frames skipped | Frames the PC was too slow to look at, in percent. |

The top line says **KEEPING UP** (under 10% skipped), **STRUGGLING** (10 to 40%) or **OVERLOADED** (over 40%). The bottom line shows free disk space, RAM and the number of CPU threads.

When you stop, it prints a summary and saves:
- `performance_<date>_<time>.csv`: one row per second of this run.
- `performance_runs.csv`: one row per run, with the settings used. `--performance-report` prints it as a table, so you can compare 1 camera against 6, `sub` against `main`, `--step 5` against `--step 10`, or `--show` on against off.

Settings cannot be changed while it runs. Stop, change the options and run again.

---

## How the alert lists decide

| Object is... | in `--notify` | in `--notify-in-zone` | in `--notify-outside-zone` | in both zone lists |
|---|---|---|---|---|
| First seen **inside** a zone | alert | alert | no alert | alert |
| First seen **outside** a zone | alert | no alert (alerts later if it enters) | alert | alert |
| Walks **into** the zone later | no new alert | alert "entered the zone" | no alert | no new alert |
| **Leaves** the zone | no new alert | no alert | alert "left the zone" | no new alert |
| Seen on a camera **without** a zone | alert | no alert | alert | alert |

Alerts have three kinds: *detected* (a new visit), *entered the zone* and *left the zone*. The cooldown counts each kind separately. Alerts for cameras with a zone also say "Area: inside the zone" or "outside the zone".

---

## All features

- Live detection of 80 object types with YOLO26n, on CPU or GPU.
- ByteTrack tracking, so each object keeps one ID.
- Visits: flicker-proof, with the same visit continued after a short gap or when a parked vehicle returns.
- Excel report with a Visits sheet and a Summary sheet, saved every minute and when you stop.
- Telegram alerts with a snapshot and the camera, time and confidence.
- Cooldown and warm-up to avoid alert floods and alerts for things already there.
- Zones per camera, with separate lists for inside, outside and everywhere.
- Any number of cameras, each in its own thread.
- Preview windows with boxes and zones (`--show`).
- Recorded-footage analysis, video-file analysis and a probe tool for the NVR (`playback.py`).
- Performance graph, run log and run comparison.
- Test options that need no NVR or no Telegram (`--test-video`, `--no-alerts`, `--test-telegram`).

---

## Settings and .env

**`.env`** (private, never uploaded):

| Name | Meaning |
|---|---|
| `NVR_USER`, `NVR_PASSWORD` | NVR login. If missing, you are asked when the program starts. |
| `TELEGRAM_BOT_TOKEN` | The token from BotFather. |
| `TELEGRAM_CHAT_ID` | Your chat ID. |

If the token or chat ID is missing, the program runs with Excel only.

**`settings.py`** (safe to edit):

| Name | Meaning |
|---|---|
| `DEFAULT_IP`, `DEFAULT_PORT` | NVR address and RTSP port. |
| `DEFAULT_CHANNELS` | Cameras opened when you give no `--channels`. |
| `CAMERA_NAMES` | Friendly names, for example `{1: "Main lane"}`. Zones are stored under these names, so draw zones after you rename. |
| `LOG_CLASSES` | Default objects written to Excel. |
| `START_CONF` | Per-object confidence needed to start a visit. |
| `PARKABLE` | Objects that may sit still for hours (motorcycle, bicycle, car, bus, truck). |
| `LIVE_TEMPLATE`, `PLAYBACK_TEMPLATE` | RTSP address patterns for your NVR. |

---

## Keyboard

| Key | Where | What it does |
|---|---|---|
| `q` or Esc | A preview or performance window | Stop and save. |
| Ctrl+C | The terminal | Stop and save. |
| Left click / right click | Zone drawing window | Add a corner / remove the last one. |
| `r`, Enter or `s`, `q` | Zone drawing window | Restart, save, cancel. |
