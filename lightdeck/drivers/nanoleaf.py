"""Nanoleaf panels (Shapes, Canvas, Elements, Lines, Light Panels) over the local network.

Nanoleaf's Open API, port 16021:
  pairing    POST /api/v1/new  (only in the 30 s after holding the controller's power button 5-7 s)
             -> {"auth_token": "..."}; 403 = not in pairing mode
  layout     GET /api/v1/<token>/  -> panelLayout.layout.positionData = [{panelId, x, y, o, shapeType}]
  streaming  PUT /api/v1/<token>/effects {"write": {"command": "display", "animType": "extControl",
             "extControlVersion": "v2"}}, then UDP port 60222, big-endian:
             [panel count: 2 bytes] + per panel [panelId: 2][R][G][B][W][transition: 2, in 100 ms]
When LightDeck stops, the effect that was running before is selected again.
Written from Nanoleaf's published API; not yet tried on a real Nanoleaf.
"""
import struct
import time

import nethelp
from driver_base import Driver

API_PORT, STREAM_PORT = 16021, 60222
NO_LIGHT = {1, 12, 16, 19, 20}     # Rhythm module, controllers, connectors, caps, power: no LEDs


def api(entry, method="GET", path="", body=None):
    return nethelp.http_json(method, f"http://{entry['address']}:{API_PORT}/api/v1/{entry['token']}/{path}",
                             body, timeout=3)


class Nanoleaf(Driver):
    name = "Nanoleaf"
    kind_name = "Nanoleaf"
    network = True
    needs_pairing = True
    bus = "Wi-Fi"
    zone_name = "Panels"
    max_fps = 15
    keepalive = 2.0
    pair_hint = ("Hold the power button on your Nanoleaf controller for 5-7 seconds, until the lights flash. "
                 "Then click Add within 30 seconds.")
    note = ("Nanoleaf panels over your network. LightDeck streams colors to every panel; when LightDeck stops, "
            "the effect that was running before comes back.")

    @classmethod
    def discover(cls):
        return [{"address": d["address"], "name": d["name"] or f"Nanoleaf {d['address']}", "id": d["name"]
                 or d["address"]} for d in nethelp.mdns_browse("_nanoleafapi._tcp.local")]

    @classmethod
    def probe(cls, address):
        import socket
        with socket.create_connection((address, API_PORT), timeout=2):
            pass
        return {"address": address, "name": f"Nanoleaf {address}", "id": address}

    @classmethod
    def pair(cls, entry):
        try:
            reply = nethelp.http_json("POST", f"http://{entry['address']}:{API_PORT}/api/v1/new", timeout=4)
        except OSError as e:
            if "HTTP 403" in str(e):
                raise RuntimeError("The Nanoleaf isn't ready to pair. " + cls.pair_hint) from None
            raise RuntimeError(str(e)) from None
        if not reply or "auth_token" not in reply:
            raise RuntimeError("The Nanoleaf didn't send a key. " + cls.pair_hint)
        return {"token": reply["auth_token"]}

    def connect(self, found):
        self.entry = found
        try:
            info = api(found)
        except OSError as e:
            if "HTTP 401" in str(e) or "HTTP 403" in str(e):
                raise RuntimeError("the Nanoleaf refused LightDeck's key - remove it in Settings and add it "
                                   "again") from None
            raise
        panels = [p for p in info["panelLayout"]["layout"]["positionData"] if p.get("shapeType") not in NO_LIGHT]
        if not panels:
            raise RuntimeError("no light panels found")
        span_x = max(p["x"] for p in panels) - min(p["x"] for p in panels)
        span_y = max(p["y"] for p in panels) - min(p["y"] for p in panels)
        key = (lambda p: (p["x"], p["y"])) if span_x >= span_y else (lambda p: (p["y"], p["x"]))
        self.panels = [p["panelId"] for p in sorted(panels, key=key)]
        self.leds = len(self.panels)
        try:
            self.previous = api(found, path="effects/select")
        except OSError:
            self.previous = None
        api(found, "PUT", "effects", {"write": {"command": "display", "animType": "extControl",
                                                "extControlVersion": "v2"}})
        self.sock = nethelp.udp_sender(found["address"], STREAM_PORT)
        self._checked = time.time()

    def send(self, colors):
        if time.time() - self._checked > 10:
            api(self.entry, path="state/on")          # still there? (raises OSError if not)
            self._checked = time.time()
        pkt = struct.pack(">H", self.leds)
        for pid, (r, g, b) in zip(self.panels, colors):
            pkt += struct.pack(">HBBBBH", pid, r & 255, g & 255, b & 255, 0, 1)
        self.sock.send(pkt)

    def disconnect(self):
        sock = getattr(self, "sock", None)
        if sock:
            sock.close()
        if getattr(self, "previous", None):
            try:
                api(self.entry, "PUT", "effects", {"select": self.previous})
            except OSError:
                pass
