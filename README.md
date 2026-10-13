# Home CCTV Alerts with YOLO26n

Watch the cameras on a TVT NVR with a normal Windows PC. The program finds people, vehicles and animals, follows each one while it is on camera, writes everything into an Excel file and sends a Telegram message with a photo when something new shows up.

<p align="center">
  <img src="assets/live-detection-3-cameras.png" alt="Live detection on three cameras" width="800"><br>
  <em>Live detection on three cameras</em>
</p>

**All commands and options are in [COMMANDS.md](COMMANDS.md).**

---

## 1. What this is, and why alerts are useful

A normal NVR records everything, but nobody sits and watches it. This program watches for you and answers four questions:

- **Who** came: person, motorcycle, car, dog, cow, and so on.
- **Which camera** saw it first.
- **When** it arrived.
- **How long** it stayed.

One object in one camera is called a **visit**. A visit is logged once, with its first and last time, even if the detector loses the object for a few seconds. When a new visit starts, you get a Telegram alert like this:

<p align="center">
  <img src="assets/telegram-alert-examples.png" alt="Telegram alerts" width="360"><br>
  <em>Telegram alerts</em>
</p>

Every visit also goes into an Excel file, so you can look at the day later:

<p align="center">
  <img src="assets/excel-visits-sheet.png" alt="Excel sheet" width="800"><br>
  <em>Excel sheet</em>
</p>

(The screenshot is from an early run. Cameras that have a zone also get a "Zone time (sec)" column.)

You can also mark an **area (zone)** on a camera and get different alerts for what happens inside and outside it. See [section 8](#8-zones).

---

## 2. What you need

- A Windows PC that can stay on, with Python 3.10 or newer. A GPU is optional. It runs on a plain CPU.
- A TVT NVR with its cameras, connected to your router by a network cable. The PC must be on the same network.
- A free Telegram account for the alerts.
- [uv](https://docs.astral.sh/uv/) to make the Python environment and install the packages (once):

```powershell
# in the project folder
uv venv --python 3.12          # creates the .venv folder
.venv\Scripts\activate         # turn it on (do this in every new terminal)
uv pip install -r requirements.txt
```

If you prefer plain pip: `python -m venv .venv`, activate it, then `pip install -r requirements.txt`.

`requirements.txt` contains `ultralytics`, `opencv-python`, `openpyxl`, `requests`, `lap` and `psutil`. The first run downloads the model file `yolo26n.pt` (about 5 MB).

---

## 3. NVR setup (once)

Do this on the NVR itself, with the TV and a mouse. Menu names differ a little between firmware versions, so look for the closest match. In short:

1. **Give the NVR a fixed (static) IP.** In `Configuration → Network`, turn off DHCP and type a fixed address. Use any free address on your network, for example `192.168.1.100` (the examples below use that). *Why:* with DHCP the router can hand the NVR a different address after a restart, and then every `rtsp://` address in the program stops working.
2. **Turn on RTSP, port 554, and press Apply.** It is on the Port tab of the same network settings. *Why:* RTSP is the way the program asks the NVR for live video. If it is off, nothing connects.
3. **Change the authentication from Digest to Basic** (look for an RTSP or login authentication setting). *Why:* with Digest the login from this program fails with **401 Unauthorized** and no video arrives. Basic works.
4. **Make sure you know the NVR username and password** (the same ones you use on the TV). They go into the `.env` file in step 5. The password is never written into any program file.

Then check the NVR from the PC:

```powershell
ping 192.168.1.100
```

If you get replies, the PC can see the NVR. A camera that is offline (camera 7 here) simply gives no picture. Leave it out with `--channels`.

### What is RTSP, and how does this work?

RTSP (Real Time Streaming Protocol) is a standard way for a recorder or camera to send live video over the network. The program asks the NVR for one camera with an address like this:

```
rtsp://admin:PASSWORD@192.168.1.100:554/chID=3&streamType=sub
```

| Part | Meaning |
|---|---|
| `admin:PASSWORD@` | the login (Basic authentication) |
| `192.168.1.100:554` | the NVR and its RTSP port |
| `chID=3` | camera number 3 |
| `streamType=sub` | `sub` is the small, fast picture; `main` is the big, detailed one |

**Is it safe to show this address?** Yes. `192.168.x.x` addresses are private. They only work inside your own home network and cannot be reached from the internet, so the same address appears in thousands of homes. What must stay private is the **password** (in `.env`) and any **public** address of your router. Also make sure your router does **not** forward port 554 (or the NVR) to the internet.

The video travels over TCP (more reliable than UDP on home networks). OpenCV reads the frames, and YOLO looks at every 5th frame, which is about 3 frames per second per camera. That is enough to see a person walk by, and it keeps the CPU load low.

---

## 4. Telegram bot setup (once)

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`, choose a name (for example *Home CCTV*) and a username that ends in `bot`.
3. BotFather replies with a **token** that looks like `123456789:AAH...`. Copy it. **Anyone who has the token can use your bot, so keep it private.**
4. Open your new bot in Telegram and press **Start** (send `/start`). A bot cannot message you until you have written to it first.
5. Find your **chat ID**. Open this address in a browser, with your token in it:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   Look for `"chat":{"id":123456789,...}`. That number is your chat ID.

<p align="center">
  <img src="assets/telegram-bot-and-first-alert.png" alt="Bot chat with test message" width="320"><br>
  <em>Bot chat with test message</em>
</p>

---

## 5. The `.env` file

Copy `.env.example` to `.env` (same folder) and fill in your own values:

```
NVR_USER=admin
NVR_PASSWORD=your_nvr_password
TELEGRAM_BOT_TOKEN=123456789:replace_with_token_from_BotFather
TELEGRAM_CHAT_ID=123456789
```

`.env` is listed in `.gitignore`, so it is never uploaded to GitHub. **Never commit it.** If the token leaks, send `/revoke` to BotFather to get a new one.

Send one test message to check the bot:

```powershell
python cctv_alert_live.py --test-telegram
```

You should see "Telegram test message sent" and the message on your phone.

---

## 6. Test that every camera works

**First, run the quick check script.** It is the fastest way to see which cameras work:

```powershell
python test_live.py
```

Then run all cameras with preview windows, without sending alerts, for two minutes:

```powershell
python cctv_alert_live.py --channels 1 2 3 4 5 6 --show --no-alerts --minutes 2
```

- Each working camera opens its own window with the live picture.
- A camera that never sends video prints `[Camera N] no video after 60 s - check the camera, the NVR password and the address`.
- To test one camera on its own: `python cctv_alert_live.py --channels 3 --show --no-alerts --minutes 1`
- To grab a still picture from one camera, run `python cctv_zone.py draw 3`. If the picture opens, the camera works. Press `q` to cancel.
- Without a camera, try a video file: `python cctv_alert_live.py --test-video clip.mp4 --channels 1 --warmup 0 --minutes 1`

If cameras fail, see [Troubleshooting](#10-troubleshooting).

---

## 7. Running it

```powershell
python cctv_alert_live.py                 # live, no windows, leave it running
python cctv_alert_live.py --show          # live, with preview windows (q = stop and save)
python cctv_alert_live.py --channels 1 3 4 --notify person motorcycle
python cctv_alert_live.py --no-photo      # text-only alerts, no picture leaves home
python cctv_alert_live.py --no-alerts     # Excel only
```

**What happens:**
- The first 20 seconds of each camera are a warm-up. Things already in view (parked bikes, a person standing there) are logged as "present at start" and do **not** send an alert.
- A new object must be seen in 2 analysed frames before it counts, which removes one-frame ghosts.
- The same camera and object type alerts at most once every 60 seconds. The next alert says how many arrivals were skipped.
- Press **Ctrl+C** (or `q` in a window) to stop. The Excel file is saved when you stop and once a minute while it runs.

**The Excel file** `detections_live_<date>_<time>.xlsx`:

| Sheet | Contents |
|---|---|
| Visits | Camera, Object, Visit #, First seen, Last seen, Duration (h:mm:ss), Duration (sec), Zone time (sec), Note |
| Summary | per camera and object: number of visits, total time, time in zone |

The *Note* column can say `present at start`, `stationary`, `re-detected 2x` (a parked vehicle that flickered and came back), `entered zone 1x` or `ongoing`.

### Recorded footage (playback)

`playback.py` fills in the NVR's long address formats for you and runs `cctv_yolo.py`:

```powershell
python playback.py --day 2026-10-12 --from 10:00 --to 10:02 --channels 3 --user admin --show
python playback.py probe --day 2026-10-12 --from 10:00      # test which recordings / URL formats work
python playback.py file --file clip.mp4 --start "2026-10-12 10:00:00"
```

The NVR keeps recordings only for a limited time, so very old days may be gone.

### How much load is it? (`--performance`)

```powershell
python cctv_alert_live.py --performance --no-alerts --channels 1 2 3 --show
```

<p align="center">
  <img src="assets/performance-graph.png" alt="Performance graph" width="700"><br>
  <em>Performance graph</em>
</p>

A live window shows CPU, RAM, free disk, detection time per frame and how many frames had to be skipped because the PC was too slow. Run again with other settings (`--stream main`, `--step 8`, fewer cameras, no `--show`) and compare all runs with `python cctv_alert_live.py --performance-report`.

---

## 8. Zones

A **zone** is an area you draw on one camera, for example the street in front of the gate. The detector still looks at the whole picture, and the zone only decides **which alerts you get**.

**Draw a zone** (the picture opens, you click the corners):

```powershell
python cctv_zone.py draw 3
```

Left click adds a corner, right click removes the last one, `r` starts again, Enter saves, `q` cancels. The zone is saved in `zones.json` as fractions of the picture, so it still fits if you switch between the sub and main stream.

<p align="center">
  <img src="assets/zone-drawn-camera3.png" alt="A zone drawn on camera 3" width="800"><br>
  <em>A zone drawn on camera 3</em>
</p>

`cctv_zone.py` only draws zones. `cctv_alert_live.py` reads `zones.json` itself, so there is nothing else to switch on.

**Three alert lists:**

| Option | You get an alert when... |
|---|---|
| `--notify X` | X appears anywhere, in or out of the zone |
| `--notify-in-zone X` | X is **inside** the zone (including when it walks into it) |
| `--notify-outside-zone X` | X is **outside** the zone (including when it leaves it) |

Put an object in both zone lists (or in `--notify`) and it alerts everywhere.

Example: show me people who are *not* in the zone, and cows and dogs that *are* in it:

```powershell
python cctv_alert_live.py --notify-outside-zone person --notify-in-zone cow dog --show
```

**Cameras without a zone** work as usual: `--notify` and `--notify-outside-zone` alert there, while `--notify-in-zone` never does (there is no "inside"). The program prints which cameras have a zone when it starts. With none of the three lists, people are alerted everywhere (the original behaviour).

Other zone commands: `python cctv_zone.py list` and `python cctv_zone.py remove 3`.

---

## 9. What runs under the hood

- **Model: YOLO26n** from Ultralytics, the *nano* size. It is small and fast enough for a CPU, and it recognises the 80 everyday object types of the COCO set (person, bicycle, car, motorcycle, bus, truck, dog, cat, cow and more). The file is `yolo26n.pt`.
- **Tracker: ByteTrack.** It gives each object an ID so the same person is followed from frame to frame instead of being counted again. Its settings are in `config/bytetrack_tuned.yaml`. The program lets lost tracks live a bit longer, so a motorcycle that flickers for a moment keeps its ID.
- **Visit logic:** if an object of the same type reappears in the same camera within 8 seconds, or a parked vehicle returns to the same spot within 30 minutes, it is the same visit and not a new row.
- **Telegram** messages are sent from a background thread, so detection never waits for the network.

### What each file does

| File | What it is for |
|---|---|
| `cctv_alert_live.py` | The main program: live detection, visits, Excel, Telegram alerts. Run this one. |
| `cctv_zone.py` | Draw, list and remove zones. |
| `playback.py` | Short commands for recorded footage (runs `cctv_yolo.py`). |
| `cctv_yolo.py` | Original tool: analyse recorded footage, video files or live streams into Excel. |
| `settings.py` | Things you may edit: NVR address, camera names, default cameras, what counts as parked. |
| `helpers.py` | Small shared functions: box maths, the `.env` reader, ByteTrack settings. |
| `camera.py` | Reads the stream, runs YOLO and the tracker, draws boxes, preview windows. |
| `visits.py` | Turns detections into visits and decides which ones deserve an alert. |
| `zones.py` | Reads `zones.json` and decides whether something is inside a zone. |
| `telegram_client.py` | Sends alerts to Telegram. |
| `report.py` | Builds the Excel file. |
| `performance.py` | The `--performance` graph and the run comparison. |
| `test_live.py` | Quick check that every camera sends video. Run it first when you set things up (see section 6). |
| `config/bytetrack_tuned.yaml` | The tracker settings, with a comment on each value. |
| `.env.example` | Template for your private `.env`. |
| `zones.example.json` | Example of what a zone file looks like. |
| `requirements.txt` | The Python packages. |

Output files (`*.xlsx`, `performance_*.csv`) are written into the folder you run from, or into `--out`.

---

## 10. Troubleshooting

| Problem | What to try |
|---|---|
| No picture, or the NVR says 401 | Change the RTSP authentication to **Basic** (step 3). Check the user and password in `.env`. |
| `no video after 60 s` for one camera | Check the camera on the TV. Check `ping 192.168.1.100`. Make sure RTSP is on and applied. |
| Telegram test fails | Send `/start` to your bot first. Check the token and chat ID in `.env` for extra spaces. |
| Preview windows do not open | The program prints `Cannot open preview windows` and keeps running without them. |
| Frames skipped, CPU at 100% | Use `--step 8`, `--stream sub`, fewer cameras, or leave out `--show`. Measure with `--performance`. |
| Playback finds nothing | Try a more recent day, then `python playback.py probe ...`. The NVR may have overwritten old footage. |
| Too many alerts | Raise `--cooldown`, raise `--min-hits`, or narrow `--notify`. |

---

## Privacy and safety

- The program sends nothing anywhere except Telegram, and only the alerts you enable. Use `--no-photo` to send text only, or `--no-alerts` to send nothing.
- **Never upload** `.env`, `zones.json`, your Excel files or the model file. The included `.gitignore` already skips them.
- Camera pictures can show neighbours and your home. Blur faces, number plates, NVR serial numbers, QR codes and tokens in any screenshot before you publish it.

## License and credits

Add a `LICENSE` file before you publish. Ultralytics (YOLO26) is released under AGPL-3.0, so code that uses it is usually published under AGPL-3.0 as well (check the Ultralytics licence; this is not legal advice).

Built with [Ultralytics YOLO26](https://docs.ultralytics.com/), ByteTrack, OpenCV and openpyxl.
