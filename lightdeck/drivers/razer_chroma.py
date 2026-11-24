"""Razer devices through Razer Synapse's Chroma SDK (a bridge: Synapse must be running).

Only used for Razer devices OpenRGB doesn't drive itself (LightDeck skips any device OpenRGB has).
Chroma SDK REST API on this PC (http://localhost:54235/razer/chromasdk):
  start      POST with the app's info -> {"sessionid", "uri"}; then use <uri>/... for everything
  keep alive PUT <uri>/heartbeat at least every 15 s
  keyboard   PUT <uri>/keyboard {"effect": "CHROMA_CUSTOM", "param": 6 rows x 22 columns of colors}
  mouse      PUT <uri>/mouse    {"effect": "CHROMA_STATIC", "param": {"color": c}}
  stop       DELETE <uri>
Colors are integers 0x00BBGGRR (blue in the high byte). Written from the SDK's published format;
not yet tried on a real Razer device.
"""
import threading
import time

import nethelp
import winhid
from driver_base import Driver

SDK = "http://localhost:54235/razer/chromasdk"
RAZER = 0x1532
ROWS, COLS = 6, 22


def bgr(c):
    return (c[2] & 255) << 16 | (c[1] & 255) << 8 | (c[0] & 255)


def sdk_running():
    try:
        nethelp.http_json("GET", SDK, timeout=0.5)
        return True
    except (OSError, ValueError):
        return False


class _Session:
    """One Chroma session shared by the Razer drivers, kept alive with a heartbeat."""
    lock = threading.Lock()
    uri = None
    users = 0

    @classmethod
    def acquire(cls):
        with cls.lock:
            if cls.uri is None:
                reply = nethelp.http_json("POST", SDK, {
                    "title": "LightDeck", "description": "LightDeck RGB effects",
                    "author": {"name": "LightDeck", "contact": "https://openrgb.org"},
                    "device_supported": ["keyboard", "mouse"], "category": "application"}, timeout=3)
                if not reply or "uri" not in reply:
                    raise RuntimeError(f"Razer Synapse didn't start a session ({reply})")
                cls.uri = reply["uri"]
                time.sleep(1.0)            # Synapse needs a moment before the session takes effects
                threading.Thread(target=cls._beat, daemon=True, name="razer heartbeat").start()
            cls.users += 1
            return cls.uri

    @classmethod
    def _beat(cls):
        while True:
            time.sleep(5)
            with cls.lock:
                uri = cls.uri
            if uri is None:
                return
            try:
                nethelp.http_json("PUT", uri + "/heartbeat", timeout=2)
            except (OSError, ValueError):
                pass

    @classmethod
    def release(cls):
        with cls.lock:
            cls.users -= 1
            if cls.users <= 0 and cls.uri:
                uri, cls.uri, cls.users = cls.uri, None, 0
                try:
                    nethelp.http_json("DELETE", uri, timeout=2)
                except (OSError, ValueError):
                    pass


def _present(usage):
    return winhid.devices(vid=RAZER, usage_page=1, usage=usage)[:1] if sdk_running() else []


class RazerChromaKeyboard(Driver):
    name = "Razer keyboard (Chroma)"
    zone_name = "Keys"
    bus = "Synapse"
    leds = ROWS * COLS
    matrix = [[r * COLS + c for c in range(COLS)] for r in range(ROWS)]
    max_fps = 30
    keepalive = 1.0
    note = ("Razer keyboard through Razer Synapse (Chroma SDK): Synapse must stay open. Keys follow a "
            "standard 22 x 6 grid, so a few positions may not match a key on your model.")

    @classmethod
    def find(cls):
        return _present(6)

    def connect(self, found):
        self.usb_ids = [(found.vid, found.pid)]
        self.uri = _Session.acquire()

    def send(self, colors):
        grid = [[bgr(colors[r * COLS + c]) for c in range(COLS)] for r in range(ROWS)]
        nethelp.http_json("PUT", self.uri + "/keyboard", {"effect": "CHROMA_CUSTOM", "param": grid})

    def disconnect(self):
        if getattr(self, "uri", None):
            _Session.release()


class RazerChromaMouse(Driver):
    name = "Razer mouse (Chroma)"
    zone_name = "Mouse lights"
    bus = "Synapse"
    leds = 1
    max_fps = 20
    keepalive = 1.0
    note = "Razer mouse through Razer Synapse (Chroma SDK): Synapse must stay open. It shows one color."

    @classmethod
    def find(cls):
        return _present(2)

    def connect(self, found):
        self.usb_ids = [(found.vid, found.pid)]
        self.uri = _Session.acquire()

    def send(self, colors):
        nethelp.http_json("PUT", self.uri + "/mouse", {"effect": "CHROMA_STATIC", "param": {"color": bgr(colors[0])}})

    def disconnect(self):
        if getattr(self, "uri", None):
            _Session.release()
