"""Logitech devices through Logitech G HUB (or the older Logitech Gaming Software). A bridge: G HUB must run.

Only used for Logitech devices OpenRGB doesn't drive itself (LightDeck skips any device OpenRGB has).
G HUB installs its lighting library for apps and games and registers where it is:
  HKLM\\SOFTWARE\\Classes\\CLSID\\{a6519e67-7632-4375-afdf-caa889744403}\\ServerBinary
  -> e.g. C:\\Program Files\\LGHUB\\sdks\\sdk_legacy_led_x64.dll   (Logitech LED SDK functions)
  LogiLedInitWithName(name)            connect to G HUB (fails if G HUB isn't running)
  LogiLedSetTargetDevice(kind)         1 = one-color, 2 = RGB (mice, headsets...), 4 = per-key keyboards
  LogiLedSetLighting(r%, g%, b%)       one color, 0..100 each
  LogiLedSetLightingFromBitmap(bytes)  per-key keyboards: 21 x 6 keys, 4 bytes each in B, G, R, A order
  LogiLedShutdown()                    give the lights back to G HUB
Nothing is downloaded: the library comes with G HUB. In G HUB, "Allow games & applications to control
my lighting" must stay on. Tested: the library loads and answers; not yet tried with G HUB running and a
lit Logitech device.
"""
import ctypes
import os
import threading
import winreg

import apps
import winhid
from driver_base import Driver

LOGITECH = 0x046D
CLSID = r"SOFTWARE\Classes\CLSID\{a6519e67-7632-4375-afdf-caa889744403}\ServerBinary"
W, H = 21, 6
PERKEY, RGB, MONO = 4, 2, 1
GHUB_PROCESSES = ("lghub_agent.exe", "lghub.exe", "lcore.exe")
KEYBOARD_RECEIVERS = {0xC541, 0xC545, 0xC547}          # LIGHTSPEED receivers of G915 / G915 TKL / G715
MOUSE_RECEIVERS = {0xC539, 0xC53A, 0xC53D, 0xC547}      # LIGHTSPEED receivers of RGB mice
NO_LIGHTS = {0xC099, 0xC094, 0xC09B}                    # G502 X, PRO X SUPERLIGHT (1 and 2): no RGB


def library_path():
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CLASSES_ROOT):
        key = CLSID if root == winreg.HKEY_LOCAL_MACHINE else CLSID.split("Classes\\", 1)[1]
        try:
            with winreg.OpenKey(root, key) as k:
                path = winreg.QueryValueEx(k, "")[0]
                if path and os.path.isfile(path):
                    return path
        except OSError:
            pass
    return None


class _Sdk:
    """G HUB's lighting library, shared by the Logitech drivers (one connection for all)."""
    lock = threading.Lock()
    dll = None
    users = 0

    @classmethod
    def acquire(cls):
        with cls.lock:
            if cls.users == 0:
                path = library_path()
                if not path:
                    raise RuntimeError("G HUB's lighting library isn't installed")
                if cls.dll is None:
                    cls.dll = ctypes.CDLL(path)
                    cls.dll.LogiLedInitWithName.argtypes = [ctypes.c_char_p]
                    cls.dll.LogiLedSetLightingFromBitmap.argtypes = [ctypes.c_char_p]
                if not cls.dll.LogiLedInitWithName(b"LightDeck"):
                    raise RuntimeError("G HUB didn't accept LightDeck: is G HUB running, with "
                                       "\"Allow games & applications to control my lighting\" on?")
            cls.users += 1
            return cls.dll

    @classmethod
    def release(cls):
        with cls.lock:
            cls.users -= 1
            if cls.users <= 0:
                cls.users = 0
                try:
                    cls.dll.LogiLedShutdown()
                except Exception:
                    pass


def _ghub_ready():
    return apps.is_running(*GHUB_PROCESSES) and library_path() is not None


def _logitech(test):
    seen, out = set(), []
    for d in winhid.devices(vid=LOGITECH):
        if d.pid not in seen and d.pid not in NO_LIGHTS and test(d.pid):
            seen.add(d.pid)
            out.append(d)
    return out


def pct(v):
    return max(0, min(100, round(v * 100 / 255)))


class LogitechKeyboard(Driver):
    name = "Logitech keyboard (G HUB)"
    maker = "Logitech"
    zone_name = "Keys"
    bus = "G HUB"
    leds = W * H
    matrix = [[r * W + c for c in range(W)] for r in range(H)]
    max_fps = 30
    keepalive = 1.0
    note = ("Logitech keyboard through Logitech G HUB: G HUB must stay open. Keys follow Logitech's "
            "21 x 6 grid, so a few positions may not match a key on your model.")

    @classmethod
    def find(cls):
        if not _ghub_ready():
            return []
        return _logitech(lambda pid: (pid & 0xFF00) == 0xC300 or pid in KEYBOARD_RECEIVERS)[:1]

    def connect(self, found):
        self.usb_ids = [(found.vid, found.pid)]
        self.dll = _Sdk.acquire()
        self.buf = bytearray(W * H * 4)

    def send(self, colors):
        b = self.buf
        for i, (r, g, bl) in enumerate(colors[:W * H]):
            b[4 * i:4 * i + 4] = bytes((bl & 255, g & 255, r & 255, 255))
        with _Sdk.lock:
            self.dll.LogiLedSetTargetDevice(PERKEY)
            ok = self.dll.LogiLedSetLightingFromBitmap(bytes(b))
        if not ok and not apps.is_running(*GHUB_PROCESSES):
            raise OSError("G HUB was closed")

    def disconnect(self):
        if getattr(self, "dll", None):
            _Sdk.release()


class LogitechLights(Driver):
    name = "Logitech lights (G HUB)"
    maker = "Logitech"
    zone_name = "Mouse, headset & speaker lights"
    bus = "G HUB"
    leds = 1
    max_fps = 20
    keepalive = 1.0
    note = ("Logitech mice, headsets and speakers through Logitech G HUB: G HUB must stay open. They all "
            "show one color. A device without lights simply stays dark.")

    @classmethod
    def find(cls):
        if not _ghub_ready():
            return []
        return _logitech(lambda pid: 0xC080 <= pid <= 0xC0FF or pid in MOUSE_RECEIVERS or
                         0x0A00 <= pid <= 0x0AFF)[:1]

    def connect(self, found):
        self.usb_ids = [(found.vid, found.pid)]
        self.dll = _Sdk.acquire()

    def send(self, colors):
        r, g, b = colors[0]
        with _Sdk.lock:
            self.dll.LogiLedSetTargetDevice(RGB | MONO)
            ok = self.dll.LogiLedSetLighting(pct(r), pct(g), pct(b))
        if not ok and not apps.is_running(*GHUB_PROCESSES):
            raise OSError("G HUB was closed")

    def disconnect(self):
        if getattr(self, "dll", None):
            _Sdk.release()
