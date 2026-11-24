"""Corsair devices through Corsair iCUE (iCUE SDK 4). A bridge: iCUE must be running.

iCUE only lets other apps in through Corsair's own small library, iCUESDK.x64_2019.dll, which doesn't
come with iCUE: it is in Corsair's free iCUE SDK (github.com/CorsairOfficial/cue-sdk, "Releases",
redist folder). Put that file in LightDeck's drivers folder (Settings > Other RGB apps > Open drivers
folder) and this bridge turns on.
Without it, quit iCUE and OpenRGB drives most Corsair devices directly.
Skipped completely when OpenRGB already drives a Corsair device (both at once would fight).
  CorsairConnect(callback, ctx)           -> callback(state 6 = connected)
  CorsairGetDevices(filter, max, infos, &n)  {type, id[128], serial[128], model[128], ledCount, channelCount}
  CorsairGetLedPositions(id, max, pos, &n)   {luid, cx, cy}   (cx/cy in mm: used to find key rows)
  CorsairRequestControl(id, 1)            exclusive lighting control (iCUE pauses its own effects)
  CorsairSetLedColors(id, n, colors)      {luid, r, g, b, a}
  CorsairReleaseControl(id), CorsairDisconnect()
Written from Corsair's published SDK headers; not yet tried with real Corsair devices.
"""
import ctypes
import os
import sys
import threading
import time
from pathlib import Path

import apps
from driver_base import Driver

CORSAIR = 0x1B1C
DLL_NAME = "iCUESDK.x64_2019.dll"
ICUE = ("icue.exe", "corsair.service.exe", "icuedevicepluginhost.exe")
CONNECTED = 6
KINDS = {0x1: "keyboard", 0x2: "mouse", 0x4: "mousepad", 0x8: "headset", 0x10: "headset stand",
         0x20: "fan controller", 0x40: "LED controller", 0x80: "RAM", 0x100: "cooler", 0x200: "motherboard",
         0x400: "graphics card", 0x800: "touchbar", 0x1000: "game controller"}


class Version(ctypes.Structure):
    _fields_ = [("major", ctypes.c_int), ("minor", ctypes.c_int), ("patch", ctypes.c_int)]


class StateChanged(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("client", Version), ("server", Version), ("host", Version)]


class DeviceInfo(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("id", ctypes.c_char * 128), ("serial", ctypes.c_char * 128),
                ("model", ctypes.c_char * 128), ("ledCount", ctypes.c_int), ("channelCount", ctypes.c_int)]


class LedPosition(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint), ("cx", ctypes.c_double), ("cy", ctypes.c_double)]


class LedColor(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint), ("r", ctypes.c_ubyte), ("g", ctypes.c_ubyte), ("b", ctypes.c_ubyte),
                ("a", ctypes.c_ubyte)]


Handler = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(StateChanged))


def library_path():
    """Where iCUESDK.x64_2019.dll is: the LightDeck folder, its drivers folder, or Corsair's folders."""
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    places = [here, here / "drivers", Path(__file__).resolve().parent]
    for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if pf:
            places += [Path(pf) / "Corsair" / d for d in ("CORSAIR iCUE 5 Software", "CORSAIR iCUE 4 Software",
                                                          "Corsair iCUE5 Software", "iCUE SDK")]
    for p in places:
        if (p / DLL_NAME).is_file():
            return str(p / DLL_NAME)
    return None


class _Sdk:
    lock = threading.Lock()
    dll = None
    state = 0
    users = 0
    _handler = None

    @classmethod
    def connect(cls):
        """Load the library and connect to iCUE (once). Returns the library."""
        with cls.lock:
            if cls.dll is None:
                path = library_path()
                if not path:
                    raise RuntimeError(f"{DLL_NAME} isn't in LightDeck's drivers folder")
                dll = ctypes.CDLL(path)
                dll.CorsairConnect.argtypes = [Handler, ctypes.c_void_p]
                dll.CorsairGetDevices.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int,
                                                  ctypes.POINTER(DeviceInfo), ctypes.POINTER(ctypes.c_int)]
                dll.CorsairGetLedPositions.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(LedPosition),
                                                       ctypes.POINTER(ctypes.c_int)]
                dll.CorsairRequestControl.argtypes = [ctypes.c_char_p, ctypes.c_int]
                dll.CorsairReleaseControl.argtypes = [ctypes.c_char_p]
                dll.CorsairSetLedColors.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(LedColor)]

                def on_state(_ctx, event):
                    cls.state = event.contents.state
                cls._handler = Handler(on_state)               # must stay alive while connected
                err = dll.CorsairConnect(cls._handler, None)
                if err:
                    raise RuntimeError(f"iCUE refused the connection (error {err})")
                cls.dll = dll
        deadline = time.monotonic() + 5
        while cls.state != CONNECTED and time.monotonic() < deadline:
            time.sleep(0.05)
        if cls.state != CONNECTED:
            raise RuntimeError("iCUE didn't answer: is iCUE running, with \"Enable SDK\" on in its settings?")
        return cls.dll

    @classmethod
    def devices(cls):
        dll = cls.connect()
        infos, n = (DeviceInfo * 64)(), ctypes.c_int()
        mask = ctypes.c_int(-1)                                 # every kind of device
        if dll.CorsairGetDevices(ctypes.byref(mask), 64, infos, ctypes.byref(n)):
            return []
        return [infos[i] for i in range(n.value)]

    @classmethod
    def positions(cls, dev_id):
        dll = cls.connect()
        pos, n = (LedPosition * 512)(), ctypes.c_int()
        if dll.CorsairGetLedPositions(dev_id, 512, pos, ctypes.byref(n)):
            return []
        return [(pos[i].id, pos[i].cx, pos[i].cy) for i in range(n.value)]


def key_rows(points):
    """Turn LED positions (luid, x mm, y mm) into a grid of rows (frame positions, None = gap)."""
    if len(points) < 20:
        return None
    rows = []
    for k in sorted(range(len(points)), key=lambda i: points[i][2]):
        y = points[k][2]
        if rows and abs(y - rows[-1][0]) < 8:
            rows[-1][1].append(k)
        else:
            rows.append([y, [k]])
    xs = sorted({round(p[1]) for p in points})
    step = min([b - a for a, b in zip(xs, xs[1:]) if b - a >= 8] or [19])
    x0 = xs[0]
    cols = min(30, int((xs[-1] - x0) / step) + 1)
    grid = []
    for _, members in rows:
        row = [None] * cols
        for k in sorted(members, key=lambda i: points[i][1]):
            c = min(cols - 1, int(round((points[k][1] - x0) / step)))
            while c < cols - 1 and row[c] is not None:
                c += 1
            if row[c] is None:
                row[c] = k
        grid.append(row)
    return grid


class CorsairICue(Driver):
    name = "Corsair device (iCUE)"
    maker = "Corsair"
    bus = "iCUE"
    max_fps = 30
    keepalive = 1.0
    note = ("Corsair device through Corsair iCUE (iCUE SDK): iCUE must stay open with \"Enable SDK\" on. "
            "Close LightDeck and iCUE takes its own lighting back.")

    @classmethod
    def find(cls):
        if not apps.is_running(*ICUE) or not library_path():
            return []
        if any(v == CORSAIR for v, _ in Driver.openrgb_ids):
            return []                                      # OpenRGB drives Corsair devices here already
        return [{"id": d.id.decode(errors="replace"), "name": d.model.decode(errors="replace") or "Corsair device",
                 "kind": KINDS.get(d.type, ""), "leds": d.ledCount} for d in _Sdk.devices() if d.ledCount > 0]

    @classmethod
    def label(cls, found):
        name = found["name"]
        return name if name.lower().startswith("corsair") else f"Corsair {name}"

    def connect(self, found):
        self.dev_id = found["id"].encode()
        points = _Sdk.positions(self.dev_id)
        if not points:
            raise RuntimeError("iCUE didn't list its LEDs")
        self.leds = len(points)
        self.zone_name = (found["kind"].capitalize() + " LEDs") if found["kind"] else "LEDs"
        if found["kind"] == "keyboard":
            self.matrix = key_rows(points)
        self.buf = (LedColor * self.leds)(*[LedColor(p[0], 0, 0, 0, 255) for p in points])
        if _Sdk.dll.CorsairRequestControl(self.dev_id, 1):
            raise RuntimeError("iCUE didn't hand over the lighting")
        self.controlled = True

    def send(self, colors):
        b = self.buf
        for i, (r, g, bl) in enumerate(colors[:self.leds]):
            b[i].r, b[i].g, b[i].b = r & 255, g & 255, bl & 255
        err = _Sdk.dll.CorsairSetLedColors(self.dev_id, self.leds, b)
        if err:
            if _Sdk.state != CONNECTED:
                raise OSError("iCUE was closed")
            raise RuntimeError(f"iCUE refused the colors (error {err})")

    def disconnect(self):
        if getattr(self, "controlled", False):
            _Sdk.dll.CorsairReleaseControl(self.dev_id)
