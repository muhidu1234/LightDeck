"""ASUS Aura lights through Armoury Crate (Aura SDK, a COM object Armoury Crate installs). A bridge.

For PCs where Armoury Crate is installed and running: motherboard, ARGB headers, ASUS graphics cards,
RAM and ASUS peripherals that Armoury Crate controls. Skipped completely when OpenRGB already drives
an ASUS device (both at once would fight over the same lights).
Aura SDK (late-bound COM, ProgID "aura.sdk.1"):
  sdk.SwitchMode()                 take over the lights (Armoury Crate stops its own effect)
  sdk.Enumerate(0)                 all devices: collection of {Name, Type, Lights, Apply()}
  light.Color = 0x00BBGGRR         one LED (blue in the high byte); dev.Apply() shows them
  sdk.ReleaseControl(0)            give the lights back to Armoury Crate
COM objects must stay on the thread that made them, so one helper thread does all the talking.
Written from ASUS's published SDK; Armoury Crate isn't installed on the test PC, so not yet tried live.
"""
import queue
import threading
import time

import apps
import comhelp
from driver_base import Driver

ASUS = 0x0B05
PROGID = "aura.sdk.1"
SERVICE = ("lightingservice.exe", "armourycrate.exe", "aurasyncservice.exe")
KINDS = {0x00010000: "motherboard", 0x00011000: "ARGB header", 0x00020000: "graphics card",
         0x00040000: "mouse", 0x00080000: "keyboard", 0x00070000: "RAM", 0x00030000: "headset",
         0x00050000: "mousepad", 0x00060000: "monitor"}


class _Host:
    """The one thread that owns the Aura SDK object and every device/LED object."""
    lock = threading.Lock()
    jobs = None
    thread = None
    sdk = None
    devices = []                 # [(device, [lights])]
    in_control = 0
    listed = (0.0, [])

    @classmethod
    def run(cls, fn, timeout=8.0):
        with cls.lock:
            if cls.thread is None or not cls.thread.is_alive():
                cls.jobs = queue.Queue()
                cls.thread = threading.Thread(target=cls._loop, daemon=True, name="aura sdk")
                cls.thread.start()
        done, box = threading.Event(), {}
        cls.jobs.put((fn, done, box))
        if not done.wait(timeout):
            raise OSError("Armoury Crate stopped answering")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    @classmethod
    def _loop(cls):
        comhelp.init()
        while True:
            fn, done, box = cls.jobs.get()
            try:
                box["value"] = fn()
            except Exception as e:
                box["error"] = e
            done.set()

    # ---- these run on the helper thread ----
    @classmethod
    def _open(cls):
        if cls.sdk is None:
            cls.sdk = comhelp.create(PROGID)
        return cls.sdk

    @classmethod
    def _enumerate(cls):
        sdk = cls._open()
        cls.devices = [(dev, dev.get("Lights").items()) for dev in sdk.call("Enumerate", 0).items()]
        out = []
        for i, (dev, lights) in enumerate(cls.devices):
            kind = KINDS.get(dev.get("Type"), "")
            out.append({"index": i, "name": dev.get("Name") or kind or f"device {i + 1}",
                        "kind": kind, "leds": len(lights)})
        return out

    @classmethod
    def devices_now(cls):
        """[{"index", "name", "kind", "leds"}], asked again at most every 30 s."""
        if time.monotonic() - cls.listed[0] > 30 or not cls.listed[1]:
            cls.listed = (time.monotonic(), cls.run(cls._enumerate))
        return cls.listed[1]

    @classmethod
    def take(cls):
        def go():
            if cls.in_control == 0:
                cls._open().call("SwitchMode")
            cls.in_control += 1
        cls.run(go)

    @classmethod
    def give_back(cls):
        def go():
            cls.in_control -= 1
            if cls.in_control <= 0 and cls.sdk is not None:
                cls.in_control = 0
                try:
                    cls.sdk.call("ReleaseControl", 0)
                except OSError:
                    pass
        try:
            cls.run(go, timeout=3)
        except OSError:
            pass

    @classmethod
    def show(cls, index, colors):
        def go():
            dev, lights = cls.devices[index]
            for light, (r, g, b) in zip(lights, colors):
                light.put("Color", (b & 255) << 16 | (g & 255) << 8 | (r & 255))
            dev.call("Apply")
        cls.run(go, timeout=3)


class AsusAura(Driver):
    name = "ASUS Aura (Armoury Crate)"
    maker = "ASUS"
    zone_name = "LEDs"
    bus = "Armoury Crate"
    max_fps = 30
    keepalive = 1.0
    note = ("ASUS lights through Armoury Crate (Aura SDK): Armoury Crate must stay installed and running. "
            "Close LightDeck and Armoury Crate takes its own lighting back.")

    @classmethod
    def find(cls):
        if not apps.is_running(*SERVICE) or not comhelp.registered(PROGID):
            return []
        if any(v == ASUS for v, _ in Driver.openrgb_ids):
            return []                                      # OpenRGB drives ASUS lights here already
        return [d for d in _Host.devices_now() if d["leds"] > 0]

    @classmethod
    def label(cls, found):
        name = found["name"]
        return name if name.lower().startswith("asus") else f"ASUS {name}"

    def connect(self, found):
        self.leds = found["leds"]
        self.index = found["index"]
        self.zone_name = found["kind"].capitalize() + " LEDs" if found["kind"] else "LEDs"
        _Host.take()
        self.taken = True

    def send(self, colors):
        _Host.show(self.index, colors)

    def disconnect(self):
        if getattr(self, "taken", False):
            _Host.give_back()
