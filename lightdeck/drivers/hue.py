"""Philips Hue lights, through the Hue Bridge on the local network (Hue API v1 over HTTP).

  find       mDNS "_hue._tcp"; GET http://<bridge>/api/0/config -> name, bridgeid (no key needed)
  pairing    press the bridge's round link button, then POST /api {"devicetype": "LightDeck#pc"}
             -> [{"success": {"username": "<key>"}}]   (error type 101 = button not pressed)
  lights     GET /api/<key>/lights
  color      PUT /api/<key>/lights/<id>/state {"on", "bri" 1-254, "xy": [x, y], "transitiontime"}

The bridge handles about 10 commands a second for all lights together, so LightDeck sends one
light per update, the one whose color moved the most. Hue suits slow, calm effects.
When LightDeck stops, every light gets back the state it had before.
"""
import time

import nethelp
from driver_base import Driver

MAX_COMMANDS_PER_SEC = 10


def rgb_to_xy(r, g, b):
    """sRGB 0-255 -> CIE xy + brightness 1-254 (Philips' recommended conversion)."""
    def lin(v):
        v /= 255.0
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92
    rl, gl, bl = lin(r), lin(g), lin(b)
    X = rl * 0.664511 + gl * 0.154324 + bl * 0.162028
    Y = rl * 0.283881 + gl * 0.668433 + bl * 0.047685
    Z = rl * 0.000088 + gl * 0.072310 + bl * 0.986039
    total = X + Y + Z
    if total <= 0:
        return (0.3227, 0.329), 0
    return (round(X / total, 4), round(Y / total, 4)), max(r, g, b) * 254 // 255


def call(entry, method, path, body=None):
    reply = nethelp.http_json(method, f"http://{entry['address']}/api/{entry.get('key', '0')}/{path}", body)
    if isinstance(reply, list) and reply and isinstance(reply[0], dict) and "error" in reply[0]:
        err = reply[0]["error"]
        if err.get("type") == 1:
            raise RuntimeError("the Hue Bridge refused LightDeck's key - remove it in Settings and add it again")
        raise OSError(f"Hue Bridge: {err.get('description', err)}")
    return reply


class Hue(Driver):
    name = "Philips Hue"
    kind_name = "Philips Hue"
    network = True
    needs_pairing = True
    bus = "Wi-Fi"
    zone_name = "Lamps"
    max_fps = MAX_COMMANDS_PER_SEC     # one command per update
    keepalive = None
    pair_hint = "Press the round link button on top of your Hue Bridge, then click Add within 30 seconds."
    note = ("Philips Hue lamps through the Hue Bridge. The bridge takes about 10 changes a second for all "
            "lamps together, so each lamp follows the effect a bit slowly: calm effects look best. When "
            "LightDeck stops, the lamps go back to how they were.")

    @classmethod
    def entry(cls, address):
        cfg = nethelp.http_json("GET", f"http://{address}/api/0/config")
        if not isinstance(cfg, dict) or "bridgeid" not in cfg:
            raise OSError(f"{address} doesn't look like a Hue Bridge")
        return {"address": address, "name": cfg.get("name") or "Hue Bridge", "id": cfg["bridgeid"]}

    @classmethod
    def discover(cls):
        out = []
        for d in nethelp.mdns_browse("_hue._tcp.local"):
            try:
                out.append(cls.entry(d["address"]))
            except OSError:
                continue
        return out

    @classmethod
    def probe(cls, address):
        return cls.entry(address)

    @classmethod
    def pair(cls, entry):
        reply = nethelp.http_json("POST", f"http://{entry['address']}/api", {"devicetype": "LightDeck#pc"})
        item = reply[0] if isinstance(reply, list) and reply else {}
        if "success" in item:
            return {"key": item["success"]["username"]}
        if item.get("error", {}).get("type") == 101:
            raise RuntimeError("The link button wasn't pressed. " + cls.pair_hint)
        raise RuntimeError(f"The bridge said: {item.get('error', {}).get('description', reply)}")

    def connect(self, found):
        self.entry = found
        lights = call(found, "GET", "lights")
        ids = sorted((k for k, v in lights.items() if "bri" in v.get("state", {})), key=lambda k: int(k))
        if not ids:
            raise RuntimeError("no dimmable lamps on this bridge")
        self.ids = ids
        self.color = {k: "xy" in lights[k]["state"] for k in ids}
        self.leds = len(ids)
        self.before = {}
        for k in ids:
            st = lights[k]["state"]
            keep = {"on": st.get("on", True), "bri": st.get("bri", 254)}
            if st.get("colormode") == "ct" and "ct" in st:
                keep["ct"] = st["ct"]
            elif "xy" in st:
                keep["xy"] = st["xy"]
            self.before[k] = keep
        self.sent = {}

    def _target(self, k, color):
        xy, bri = rgb_to_xy(*color)
        if bri <= 1:
            return {"on": False}
        t = {"on": True, "bri": bri, "transitiontime": 1}
        if self.color[k]:
            t["xy"] = list(xy)
        return t

    @staticmethod
    def _distance(a, b):
        if a is None or a.get("on") != b.get("on"):
            return 1000
        d = abs(a.get("bri", 0) - b.get("bri", 0))
        if "xy" in a and "xy" in b:
            d += 400 * (abs(a["xy"][0] - b["xy"][0]) + abs(a["xy"][1] - b["xy"][1]))
        return d

    def send(self, colors):
        best, best_d = None, 6            # ignore changes too small to see
        for k, color in zip(self.ids, colors):
            t = self._target(k, color)
            d = self._distance(self.sent.get(k), t)
            if d > best_d:
                best, best_d = (k, t), d
        if best:
            k, t = best
            call(self.entry, "PUT", f"lights/{k}/state", t)
            self.sent[k] = t

    def disconnect(self):
        for k, st in getattr(self, "before", {}).items():
            try:
                call(self.entry, "PUT", f"lights/{k}/state", st)
            except (OSError, RuntimeError):
                pass
