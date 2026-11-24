"""SteelSeries devices through SteelSeries GG / Engine (GameSense SDK; a bridge: GG must be running).

Only used for SteelSeries devices OpenRGB doesn't drive itself (LightDeck skips any device OpenRGB has).
GameSense, a small web server on this PC; its address is in
%PROGRAMDATA%\\SteelSeries\\SteelSeries Engine 3\\coreProps.json ({"address": "127.0.0.1:<port>"}).
  POST /game_metadata     {"game": "LIGHTDECK", "game_display_name", "developer"}
  POST /bind_game_event   {"game", "event", "value_optional": true, "handlers": [...]}
      keyboards: {"device-type": "rgb-per-key-zones", "mode": "bitmap"}
                 -> event data {"frame": {"bitmap": 132 x [r, g, b]}}  (22 x 6 grid, row by row)
      others:    {"device-type": "mouse", "zone": "wheel", "mode": "context-color", "context-frame-key": "color"}
                 -> event data {"frame": {"color": {"red", "green", "blue"}}}
  POST /game_event        {"game", "event", "data": {"value": 0, "frame": {...}}}
  POST /game_heartbeat    {"game"}   (GG drops the game after 15 s of silence)
  POST /stop_game         {"game"}
"""
import json
import os
import threading
import time

import nethelp
import winhid
from driver_base import Driver

GAME = "LIGHTDECK"
STEELSERIES = 0x1038
ROWS, COLS = 6, 22
CORE_PROPS = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "SteelSeries", "SteelSeries Engine 3",
                          "coreProps.json")


def address():
    try:
        with open(CORE_PROPS, encoding="utf-8") as f:
            return "http://" + json.load(f)["address"]
    except (OSError, ValueError, KeyError):
        return None


def post(path, body, timeout=2):
    base = address()
    if not base:
        raise OSError("SteelSeries GG isn't running")
    return nethelp.http_json("POST", base + path, body, timeout=timeout)


class _Game:
    """LightDeck registered once as a GameSense "game", kept alive with a heartbeat."""
    lock = threading.Lock()
    users = 0

    @classmethod
    def acquire(cls):
        with cls.lock:
            if cls.users == 0:
                post("/game_metadata", {"game": GAME, "game_display_name": "LightDeck", "developer": "LightDeck",
                                        "deinitialize_timer_length_ms": 15000})
                threading.Thread(target=cls._beat, daemon=True, name="steelseries heartbeat").start()
            cls.users += 1

    @classmethod
    def _beat(cls):
        while True:
            time.sleep(5)
            with cls.lock:
                if cls.users <= 0:
                    return
            try:
                post("/game_heartbeat", {"game": GAME})
            except (OSError, ValueError):
                pass

    @classmethod
    def release(cls):
        with cls.lock:
            cls.users -= 1
            if cls.users <= 0:
                cls.users = 0
                try:
                    post("/stop_game", {"game": GAME})
                except (OSError, ValueError):
                    pass


def _present(usage):
    return winhid.devices(vid=STEELSERIES, usage_page=1, usage=usage)[:1] if address() else []


class SteelSeriesKeyboard(Driver):
    name = "SteelSeries keyboard (GG)"
    zone_name = "Keys"
    bus = "GG"
    leds = ROWS * COLS
    matrix = [[r * COLS + c for c in range(COLS)] for r in range(ROWS)]
    max_fps = 30
    keepalive = 1.0
    note = ("SteelSeries keyboard through SteelSeries GG (GameSense): GG must stay open. Keys follow a "
            "standard 22 x 6 grid, so a few positions may not match a key on your model.")

    @classmethod
    def find(cls):
        return _present(6)

    def connect(self, found):
        self.usb_ids = [(found.vid, found.pid)]
        _Game.acquire()
        self.joined = True
        post("/bind_game_event", {"game": GAME, "event": "KEYS", "value_optional": True,
                                  "handlers": [{"device-type": "rgb-per-key-zones", "mode": "bitmap"}]})

    def send(self, colors):
        bitmap = [[r & 255, g & 255, b & 255] for r, g, b in colors[:self.leds]]
        post("/game_event", {"game": GAME, "event": "KEYS", "data": {"value": 0, "frame": {"bitmap": bitmap}}})

    def disconnect(self):
        if getattr(self, "joined", False):
            _Game.release()


class SteelSeriesMouse(Driver):
    name = "SteelSeries mouse (GG)"
    zone_name = "Mouse lights"
    bus = "GG"
    leds = 1
    max_fps = 20
    keepalive = 1.0
    note = "SteelSeries mouse through SteelSeries GG (GameSense): GG must stay open. It shows one color."

    @classmethod
    def find(cls):
        return _present(2)

    def connect(self, found):
        self.usb_ids = [(found.vid, found.pid)]
        _Game.acquire()
        self.joined = True
        handlers = [{"device-type": "mouse", "zone": z, "mode": "context-color", "context-frame-key": "color"}
                    for z in ("wheel", "logo")]
        post("/bind_game_event", {"game": GAME, "event": "MOUSE", "value_optional": True, "handlers": handlers})

    def send(self, colors):
        r, g, b = colors[0]
        post("/game_event", {"game": GAME, "event": "MOUSE",
                             "data": {"value": 0, "frame": {"color": {"red": r, "green": g, "blue": b}}}})

    def disconnect(self):
        if getattr(self, "joined", False):
            _Game.release()
