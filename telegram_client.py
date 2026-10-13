"""Telegram: alerts are queued and sent from a background thread so detection never waits."""
import os
import queue
import sys
import threading
import time

import requests

class Telegram:
    """Sends text and photos to a Telegram chat from a background thread."""
    def __init__(self, token, chat_id, photo=True, enabled=True):
        self.token, self.chat_id, self.photo = token or "", chat_id or "", photo
        self.enabled = bool(enabled and self.token and self.chat_id)
        self.base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        self.q = queue.Queue(maxsize=50)
        self.busy = False
        if self.enabled:
            threading.Thread(target=self._worker, daemon=True).start()

    def scrub(self, text):
        """Never let the bot token show up in messages (error texts from 'requests' contain the URL)."""
        return str(text).replace(self.token, "***") if self.token else str(text)

    def _call(self, method, data, files=None):
        """One raw request to the Telegram Bot API; raises a readable error on failure."""
        r = requests.post(f"{self.base}/bot{self.token}/{method}", data=data, files=files, timeout=20)
        if r.status_code != 200:
            try:
                desc = r.json().get("description", r.text)
            except Exception:
                desc = r.text
            raise RuntimeError(f"HTTP {r.status_code}: {desc}")

    def send_now(self, text, jpg=None):
        """Send immediately (used by the test command)."""
        if jpg is not None and self.photo:
            self._call("sendPhoto", {"chat_id": self.chat_id, "caption": text[:1000]},
                       {"photo": ("snapshot.jpg", jpg, "image/jpeg")})
        else:
            self._call("sendMessage", {"chat_id": self.chat_id, "text": text})

    def send(self, text, jpg=None):
        """Put an alert in the queue; returns at once."""
        if not self.enabled:
            return
        try:
            self.q.put_nowait((text, jpg))
        except queue.Full:
            print("  Telegram queue is full - one alert was dropped")

    def _worker(self):
        """Background loop that empties the queue, with retries."""
        while True:
            text, jpg = self.q.get()
            self.busy = True
            for attempt in (1, 2):
                try:
                    self.send_now(text, jpg)
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  Telegram alert failed: {type(e).__name__}: {self.scrub(e)}")
                    else:
                        time.sleep(2)
            self.busy = False

    def flush(self, timeout=10):
        """Wait (up to timeout seconds) until all queued alerts are sent."""
        t0 = time.time()
        while (not self.q.empty() or self.busy) and time.time() - t0 < timeout:
            time.sleep(0.2)


def run_telegram_test(tg):
    """Send one test message so the user can check the bot setup."""
    if not tg.enabled:
        sys.exit("TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID not found. Put both in the .env file "
                 "(next to this script) and run again.")
    try:
        tg.send_now("Test message from your CCTV alert script. If you can read this, Telegram works.")
    except Exception as e:
        msg = tg.scrub(e)
        print(f"Telegram test FAILED: {type(e).__name__}: {msg}")
        low = msg.lower()
        if "401" in msg or "unauthorized" in low:
            print("-> The bot token is wrong. Copy it again from BotFather (no spaces, no quotes needed).")
        elif "chat not found" in low or "400" in msg:
            print("-> Wrong chat id, or you have not opened your bot in Telegram and pressed Start yet.")
        else:
            print("-> Check the internet connection of this computer.")
        sys.exit(1)
    print("Telegram test message sent. Check your phone.")
