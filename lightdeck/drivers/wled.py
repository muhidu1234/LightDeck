"""WLED: the popular free firmware for Wi-Fi LED strips (ESP8266 / ESP32 boards).

Found on the network through mDNS ("_wled._tcp"). The LED count comes from http://<ip>/json/info.
Colors are streamed with WLED's realtime UDP protocol on port 21324:
    DRGB  (2): [2, timeout_s] + r,g,b for LED 0, 1, 2 ...            (up to 490 LEDs)
    DNRGB (4): [4, timeout_s, start_hi, start_lo] + r,g,b ...         (489 LEDs per packet, any length)
After `timeout_s` seconds without packets WLED goes back to its own effect by itself.
"""
import time

import nethelp
from driver_base import Driver

PORT = 21324
DRGB, DNRGB = 2, 4
TIMEOUT_S = 2
PER_PACKET = 489


def info(address):
    i = nethelp.http_json("GET", f"http://{address}/json/info")
    if not isinstance(i, dict) or "leds" not in i:
        raise OSError(f"{address} doesn't look like a WLED light")
    return i


class WLED(Driver):
    name = "WLED light"
    kind_name = "WLED"
    network = True
    bus = "Wi-Fi"
    zone_name = "LEDs"
    max_fps = 60
    keepalive = 1.0            # keep WLED in realtime mode (it times out after 2 s)
    pair_hint = "WLED lights need no pairing: they only have to be on the same network as this PC."
    note = ("Wi-Fi LED strip running WLED. LightDeck streams colors to it over your network; when LightDeck "
            "stops, WLED goes back to its own effect within 2 seconds. Set the LED count in WLED itself.")

    @classmethod
    def entry(cls, address, i):
        return {"address": address, "name": i.get("name") or f"WLED {address}", "id": i.get("mac") or address}

    @classmethod
    def discover(cls):
        out = []
        for d in nethelp.mdns_browse("_wled._tcp.local"):
            try:
                out.append(cls.entry(d["address"], info(d["address"])))
            except OSError:
                continue
        return out

    @classmethod
    def probe(cls, address):
        return cls.entry(address, info(address))

    def connect(self, found):
        self.address = found["address"]
        i = info(self.address)
        self.leds = max(1, int(i["leds"].get("count", 0)))
        self.sock = nethelp.udp_sender(self.address, PORT)
        self._checked = time.time()

    def send(self, colors):
        if time.time() - self._checked > 10:        # UDP never fails: check now and then that it's still there
            info(self.address)
            self._checked = time.time()
        flat = bytes(v & 255 for c in colors[:self.leds] for v in c)
        if self.leds <= 490:
            self.sock.send(bytes([DRGB, TIMEOUT_S]) + flat)
        else:
            for start in range(0, self.leds, PER_PACKET):
                part = flat[start * 3:(start + PER_PACKET) * 3]
                self.sock.send(bytes([DNRGB, TIMEOUT_S, start >> 8, start & 255]) + part)

    def disconnect(self):
        sock = getattr(self, "sock", None)
        if sock:
            sock.close()
