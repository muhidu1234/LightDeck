"""LightDeck engine: talks to OpenRGB, runs effects, pushes colors to devices."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

# inside a packaged LightDeck.exe the editable files (effects, config) live next to the .exe
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from effect_base import Effect  # noqa: E402
from driver_base import load_drivers  # noqa: E402

VERSION = "1.0"


def _user_dir():
    """Where settings and effects live: next to the program if Windows lets us write there
    (portable / per-user install), otherwise %APPDATA%\\LightDeck (e.g. under Program Files)."""
    try:
        probe = APP_DIR / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return APP_DIR
    except OSError:
        d = Path(os.environ.get("APPDATA", str(Path.home()))) / "LightDeck"
        d.mkdir(parents=True, exist_ok=True)
        import shutil
        for sub in ("effects", "drivers"):     # first run: give the user editable effects and drivers
            if not (d / sub).exists() and (APP_DIR / sub).exists():
                shutil.copytree(APP_DIR / sub, d / sub)
        return d


USER_DIR = _user_dir()
EFFECTS_DIR = USER_DIR / "effects"
DRIVERS_DIR = USER_DIR / "drivers"
CONFIG_PATH = USER_DIR / "config.json"
FIRST_RUN = not CONFIG_PATH.exists()
_BUNDLED_OPENRGB = APP_DIR / "OpenRGB" / "OpenRGB.exe"          # copy shipped with the installed app
_PORTABLE_OPENRGB = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenRGB" / "OpenRGB Windows 64-bit" / "OpenRGB.exe"
DEFAULT_OPENRGB = _BUNDLED_OPENRGB if _BUNDLED_OPENRGB.exists() else _PORTABLE_OPENRGB
HOST, PORT = "127.0.0.1", 6742
GLOBAL = "__global__"
DEFAULT_HEADER_LEDS = 60
FPS_MIN, FPS_MAX = 10, 120
# Devices on I2C/SMBus (graphics cards, RAM, some motherboards) share a slow bus with
# their driver. Flooding them with updates garbles the data and the lights glitch,
# so they get a low default rate. USB devices can take full speed.
SLOW_BUS_FPS = 10
# Re-send unchanged colors this often, so a garbled update is corrected quickly.
KEEPALIVE_FAST, KEEPALIVE_SLOW = 1.0, 2.0

# How LightDeck controls an OpenRGB device:
#   "direct"  live per-LED colors (the normal case)
#   "perled"  no live mode, but a mode such as Static takes per-LED colors: same idea, gentler pace
#   "single"  only a mode with one color for the whole device: it shows the effect's average color
#   "none"    no color can be set from outside
CTRL_DIRECT, CTRL_PERLED, CTRL_SINGLE, CTRL_NONE = "direct", "perled", "single", "none"
PERLED_FPS, SINGLE_FPS = 10, 2      # default updates per second for devices without a live mode
SINGLE_MIN_CHANGE = 6               # one-color devices: ignore changes smaller than this (0-255 per channel)
STATIC_NAMES = ("static", "custom", "fixed", "solid", "steady", "direct")


def pick_control(dev):
    """(kind, mode) - the best way to drive an OpenRGB device. See CTRL_* above."""
    from openrgb.utils import ModeColors, ModeFlags
    modes = list(dev.modes or [])

    def prefer(cands):
        for word in STATIC_NAMES:
            for m in cands:
                if m.name.lower().startswith(word):
                    return m
        return cands[0]

    direct = [m for m in modes if m.name.lower().startswith("direct")]
    if direct:
        return CTRL_DIRECT, direct[0]
    per_led = [m for m in modes if m.color_mode == ModeColors.PER_LED]
    if per_led:
        return CTRL_PERLED, prefer(per_led)
    # one color for the whole device: only modes that hold still (no speed = no animation)
    single = [m for m in modes if m.color_mode == ModeColors.MODE_SPECIFIC and (m.colors_max or 0) >= 1
              and (m.name.lower().startswith(STATIC_NAMES) or not (m.flags & ModeFlags.HAS_SPEED))]
    if single:
        return CTRL_SINGLE, prefer(single)
    return CTRL_NONE, None


def send_mode(dev, mode):
    """Send a mode (with its colors) to OpenRGB without waiting for a reply.
    (The library's set_mode asks for the whole device again up to 5 times: far too slow per frame.)"""
    from openrgb.utils import PacketType
    data = mode.pack(dev.comms._protocol_version)
    dev.comms.send_header(dev.id, PacketType.RGBCONTROLLER_UPDATEMODE, len(data))
    dev.comms.send_data(data)


def send_leds(dev, colors):
    """Per-LED colors (works in Direct and in per-LED modes like Static)."""
    from openrgb.utils import RGBColor
    rgb = [RGBColor(*c) for c in colors]
    if hasattr(dev, "_set_device_colors"):
        dev._set_device_colors(rgb, fast=True)   # never mistaken for a one-color mode
    else:
        dev.set_colors(rgb, fast=True)


def is_slow_bus(location):
    loc = (location or "").lower()
    return loc.startswith("i2c") or "smbus" in loc

DEFAULT_CONFIG = {
    "brightness": 100,
    "fps": 60,
    "openrgb_path": str(DEFAULT_OPENRGB),
    "openrgb_admin": True,     # start OpenRGB as administrator so RAM lighting works
    "led_counts": {},      # hardware zone key -> number of LEDs on that header
    "segments": {},        # hardware zone key -> [LEDs in part 1, part 2, ...]   (cut along the cable)
    "layouts": {},         # hardware zone key -> {"strips", "order", "zigzag"}  (parallel strips)
    "names": {},           # device name / zone key / part key -> your own name
    "device_fps": {},      # device name -> max updates per second for that device
    "overrides": [],       # light keys that use their own effect instead of the global one
    "disabled": [],        # light keys that stay dark
    "targets": {GLOBAL: {"effect": "Rainbow Strips", "values": {}}},
}


ORDER_ALONG = "along"    # LEDs run down strip 1, then strip 2, ...
ORDER_ACROSS = "across"  # LEDs run across all strips, then the next row, ...
ORDER_ROWS = "rows"      # a keyboard (or other grid): one strip per row of its key map


def part_key(zone_key, i, kind="part"):
    return f"{zone_key} #{kind}{i + 1}"


def strip_indices(n, strips, order, zigzag):
    """For a header of n LEDs wired as `strips` parallel strips, return the LED numbers
    (0-based, inside the header) of each strip, from one end of the cable to the other."""
    length = n // strips
    out = []
    for s in range(strips):
        idx = []
        for p in range(length):
            if order == ORDER_ALONG:
                pos = (length - 1 - p) if (zigzag and s % 2) else p
                idx.append(s * length + pos)
            else:
                col = (strips - 1 - s) if (zigzag and p % 2) else s
                idx.append(p * strips + col)
        out.append(idx)
    return out


KIND_WORDS = {"part": "Part", "strip": "Strip", "row": "Row"}


class ZoneInfo:
    """One controllable strip of LEDs: a whole OpenRGB zone, a part cut along it,
    or one of several parallel strips inside it."""

    def __init__(self, dev_idx, dev_name, hw_key, hw_name, hw_leds, hw_start, indices, resizable,
                 part=None, kind="part", fixed=False, matrix=None):
        self.dev_idx = dev_idx
        self.device = dev_name          # device name (numbered if there are identical ones)
        self.hw_key = hw_key            # key of the real zone ("Device :: Zone")
        self.hw_name = hw_name          # OpenRGB zone name
        self.hw_leds = hw_leds          # LEDs in the whole real zone
        self.hw_start = hw_start        # first LED of the real zone inside the device
        self.resizable = resizable      # can it be split / (unless fixed) resized
        self.fixed = fixed              # LED count is fixed by the hardware (e.g. a keyboard)
        self.part = part                # None, or 1, 2, 3... when the zone is split
        self.kind = kind                # "part" (cut along the cable), "strip" (parallel) or "row" (key map)
        self.key = hw_key if part is None else part_key(hw_key, part - 1, kind)
        self.name = hw_name if part is None else f"{KIND_WORDS.get(kind, 'Part')} {part}"
        self.matrix = matrix            # key map of the whole zone (rows of LED numbers / None), if it has one
        self.indices = indices          # LED numbers inside the device, in effect order (None = gap in a row)
        self.leds = len(indices)        # what the effect draws (gaps included, so columns line up)
        self.lit = sum(1 for i in indices if i is not None)   # real LEDs
        # filled in per frame for the effect:
        self.index = 0
        self.count = 1


def load_effects():
    """Import every effects/*.py file and collect the Effect classes in it."""
    classes, errors = {}, []
    for path in sorted(EFFECTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"lightdeck_effect_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for obj in vars(module).values():
                if isinstance(obj, type) and issubclass(obj, Effect) and obj is not Effect \
                        and obj.__module__ == module.__name__:
                    classes[obj.name] = obj
        except Exception:
            errors.append(f"{path.name}: {traceback.format_exc(limit=2).strip().splitlines()[-1]}")
    return classes, errors


def effect_mtimes():
    return {p.name: p.stat().st_mtime for p in EFFECTS_DIR.glob("*.py")}


def port_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


class Engine:
    def __init__(self):
        self.cfg = self._load_config()
        self.effect_classes, self.effect_errors = load_effects()
        self._mtimes = effect_mtimes()
        self.driver_classes, self.driver_errors = load_drivers(DRIVERS_DIR)
        self._bind_driver_store()
        self.lock = threading.RLock()
        self.client = None
        self.zones = []         # ZoneInfo for every controllable strip (parts included)
        self.dev_led_counts = []
        self.dev_names = []     # per device: unique name (duplicates numbered)
        self.dev_info = []      # per device: {"name", "slow", "location"} (OpenRGB devices, then extras)
        self.ogb_info = []      # OpenRGB devices only
        self.dev_ctrl = []      # per OpenRGB device: (kind, mode) - see pick_control()
        self.extras = []        # devices LightDeck drives itself (e.g. the RK N80 keyboard)
        self._extras_checked = 0.0
        self._new_extras = []   # (driver, class) connected in the background, not taken in yet
        self._finding = False
        self.driver_problems = {}   # device name -> why it can't be used right now
        self._devices_checked = 0.0
        self._ogb_sig = ()
        self.other_devices = []          # gaming devices found that no driver can light (shown in the app)
        self._others_checked = 0.0
        self._others_running = False
        self._last_sent = []    # per device: (frame, time sent)
        self.status = "Starting..."
        self.last_error = ""
        self.effects = {}       # target -> Effect instance
        self.states = {}        # (target, light key) -> dict
        self.preview = {}       # light key -> list of colors
        self.actual_fps = 0.0
        # live statistics for the telemetry panel
        self.frame_ms = 0.0          # time to render + send one frame (smoothed)
        self.inst_fps = 0.0          # frames per second, smoothed every frame
        self.packets_per_sec = {}    # device name -> updates actually sent per second
        self.total_packets = 0
        self.started_at = time.time()
        self._packet_count = {}
        self.identify = (frozenset(), 0.0)   # (keys to blink, until)
        self.order_test = ("", 0.0, 0.0)     # (header key, started, seconds) for "Show LED order"
        self._stop = threading.Event()
        self._reconnect = threading.Event()
        self._rebuild = threading.Event()
        self._thread = None
        self._t0 = time.perf_counter()

    # ---------- config ----------
    def _load_config(self):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if CONFIG_PATH.exists():
            try:
                cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
            except Exception:
                pass
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, json.loads(json.dumps(v)))
        cfg["targets"].setdefault(GLOBAL, {"effect": "Rainbow Strips", "values": {}})
        return cfg

    def save_config(self):
        with self.lock:
            for target, eff in self.effects.items():
                if eff is None:
                    continue
                t = self.cfg["targets"].setdefault(target, {"effect": eff.name, "values": {}})
                t["effect"] = eff.name
                t.setdefault("values", {})[eff.name] = dict(eff.values)
            CONFIG_PATH.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")

    # ---------- names ----------
    def display_name(self, key, default):
        return self.cfg["names"].get(key) or default

    def rename(self, key, new_name):
        with self.lock:
            new_name = (new_name or "").strip()
            if new_name:
                self.cfg["names"][key] = new_name
            else:
                self.cfg["names"].pop(key, None)

    def light_name(self, z):
        """Readable name for a strip, e.g. 'Strip Cable' or 'Header 1 · Fans'."""
        hw = self.display_name(z.hw_key, z.hw_name)
        if z.part is None:
            return hw
        return f"{hw} · {self.display_name(z.key, z.name)}"

    # ---------- effects ----------
    def effect_names(self):
        return sorted(self.effect_classes)

    def _instantiate(self, target, name=None):
        tcfg = self.cfg["targets"].setdefault(target, {"effect": "", "values": {}})
        name = name or tcfg.get("effect")
        if name not in self.effect_classes:
            name = "Rainbow Strips" if "Rainbow Strips" in self.effect_classes else (self.effect_names() or [None])[0]
        if name is None:
            return None
        tcfg["effect"] = name
        values = tcfg.setdefault("values", {}).get(name, {})
        return self.effect_classes[name](values)

    def get_effect(self, target):
        with self.lock:
            if self.effects.get(target) is None:
                self.effects[target] = self._instantiate(target)
            return self.effects[target]

    def _remember(self, target):
        old = self.effects.get(target)
        if old is not None:
            t = self.cfg["targets"].setdefault(target, {"effect": old.name, "values": {}})
            t.setdefault("values", {})[old.name] = dict(old.values)

    def set_effect(self, target, name):
        with self.lock:
            self._remember(target)
            self.effects[target] = self._instantiate(target, name)
            for k in [k for k in self.states if k[0] == target]:
                del self.states[k]
            return self.effects[target]

    def reset_effect(self, target):
        with self.lock:
            eff = self.get_effect(target)
            if eff:
                self.cfg["targets"][target]["values"].pop(eff.name, None)
                self.effects[target] = self._instantiate(target, eff.name)
            return self.effects[target]

    def reload_if_changed(self):
        """Hot-reload effect files that were edited. Returns True if anything changed."""
        now = effect_mtimes()
        if now == self._mtimes:
            return False
        self._mtimes = now
        classes, errors = load_effects()
        with self.lock:
            for target in list(self.effects):
                self._remember(target)
            self.effect_classes, self.effect_errors = classes, errors
            self.effects = {}
            self.states = {}
        return True

    # ---------- lights ----------
    def uses_own_effect(self, key):
        return key in self.cfg["overrides"]

    def set_override(self, key, own):
        with self.lock:
            ov = self.cfg["overrides"]
            if own and key not in ov:
                ov.append(key)
            elif not own and key in ov:
                ov.remove(key)

    def is_enabled(self, key):
        return key not in self.cfg["disabled"]

    def set_enabled(self, key, enabled):
        with self.lock:
            dis = self.cfg["disabled"]
            if not enabled and key not in dis:
                dis.append(key)
            elif enabled and key in dis:
                dis.remove(key)

    def set_led_count(self, hw_key, n):
        with self.lock:
            self.cfg["led_counts"][hw_key] = int(n)
            # keep the parts inside the new length
            parts = self.cfg["segments"].get(hw_key)
            if parts and sum(parts) > n:
                self.cfg["segments"].pop(hw_key)
            lay = self.cfg["layouts"].get(hw_key)
            if lay and lay["strips"] > n:
                self.cfg["layouts"].pop(hw_key)
        self.reconnect()

    def segments(self, hw_key):
        return list(self.cfg["segments"].get(hw_key) or [])

    def set_segments(self, hw_key, sizes):
        """Cut a zone into parts along the cable. sizes=[] puts it back to one piece."""
        with self.lock:
            sizes = [int(s) for s in sizes if int(s) > 0]
            self.cfg["layouts"].pop(hw_key, None)
            if len(sizes) <= 1:
                self.cfg["segments"].pop(hw_key, None)
            else:
                self.cfg["segments"][hw_key] = sizes
        self._rebuild.set()

    def layout(self, hw_key):
        return self.cfg["layouts"].get(hw_key)

    def set_layout(self, hw_key, strips, order, zigzag):
        """Split a zone into parallel strips that run side by side along the cable."""
        with self.lock:
            self.cfg["segments"].pop(hw_key, None)
            if int(strips) <= 1:
                self.cfg["layouts"].pop(hw_key, None)
            else:
                self.cfg["layouts"][hw_key] = {"strips": int(strips), "order": order, "zigzag": bool(zigzag)}
        self._rebuild.set()

    def join(self, hw_key):
        """Undo any split: the zone is one light again."""
        with self.lock:
            self.cfg["segments"].pop(hw_key, None)
            self.cfg["layouts"].pop(hw_key, None)
        self._rebuild.set()

    def identify_lights(self, keys, seconds=3.0):
        """Blink lights white so you can find them on your PC. keys: light, zone or device keys."""
        self.identify = (frozenset(keys), time.perf_counter() + seconds)

    def show_led_order(self, hw_key):
        """Run a single dot through a header's LEDs in wiring order (LED 1, 2, 3...),
        so you can see how the cable is wired and how many LEDs it really has."""
        z = next((z for z in self.zones if z.hw_key == hw_key), None)
        if z is None:
            return 0.0
        seconds = max(4.0, z.hw_leds / 8.0)   # 8 LEDs per second
        self.order_test = (hw_key, time.perf_counter(), seconds)
        return seconds

    def stop_led_order(self):
        self.order_test = ("", 0.0, 0.0)

    def set_fps(self, fps):
        self.cfg["fps"] = int(max(FPS_MIN, min(FPS_MAX, fps)))

    def device_fps(self, dev_name):
        """Max updates per second for one device (slow I2C devices default to SLOW_BUS_FPS,
        devices without a live mode even lower)."""
        saved = self.cfg["device_fps"].get(dev_name)
        if saved:
            return int(saved)
        info = next((d for d in self.dev_info if d["name"] == dev_name), None)
        if info and info.get("ctrl") == CTRL_SINGLE:
            return SINGLE_FPS
        if info and info.get("ctrl") == CTRL_PERLED:
            return min(PERLED_FPS, SLOW_BUS_FPS)
        return SLOW_BUS_FPS if info and info["slow"] else FPS_MAX

    def set_device_fps(self, dev_name, fps):
        with self.lock:
            self.cfg["device_fps"][dev_name] = int(max(1, min(FPS_MAX, fps)))

    def is_slow_device(self, dev_name):
        info = next((d for d in self.dev_info if d["name"] == dev_name), None)
        return bool(info and info["slow"])

    def reconnect(self):
        self._reconnect.set()

    # ---------- OpenRGB connection ----------
    def _launch_openrgb(self):
        exe = Path(self.cfg.get("openrgb_path") or DEFAULT_OPENRGB)
        if not exe.exists():
            exe = DEFAULT_OPENRGB
        if not exe.exists():
            raise RuntimeError(f"OpenRGB not found at {exe}")
        started = False
        if self.cfg.get("openrgb_admin", True):
            # RAM (and some motherboards) sit on the SMBus, which OpenRGB can only reach with
            # administrator rights. Windows shows its "allow this app" prompt for this.
            self.status = "Starting OpenRGB as administrator (click Yes on the Windows prompt)..."
            try:
                import ctypes
                rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), "--server", str(exe.parent), 7)
                started = rc > 32
            except Exception:
                started = False
            if not started:
                self.last_error = "Admin prompt declined - RAM lighting won't be available this time"
        if not started:
            self.status = "Starting OpenRGB..."
            # OpenRGB's own --startminimized flag makes it quit after its startup warning,
            # so start it normally and ask Windows to open the window minimized instead.
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
            subprocess.Popen([str(exe), "--server"], cwd=str(exe.parent), startupinfo=si)
        for _ in range(60):
            if port_open():
                time.sleep(1.0)  # let it finish detecting devices
                return
            time.sleep(0.5)
        raise RuntimeError("OpenRGB did not start its server")

    def _connect(self):
        from openrgb import OpenRGBClient
        from openrgb.utils import ZoneType

        if not port_open():
            self._launch_openrgb()
        self.status = "Connecting..."
        client = OpenRGBClient(HOST, PORT, "LightDeck")

        # identical devices (e.g. two RAM sticks both called "ENE DRAM") get numbered names
        totals, seen, dev_names = {}, {}, []
        for dev in client.devices:
            totals[dev.name] = totals.get(dev.name, 0) + 1
        for dev in client.devices:
            seen[dev.name] = seen.get(dev.name, 0) + 1
            dev_names.append(f"{dev.name} {seen[dev.name]}" if totals[dev.name] > 1 else dev.name)
        self.dev_names = dev_names

        # put everything in its live mode (or the best fallback) and size the ARGB headers
        changed = False
        ctrl = []
        for di, dev in enumerate(client.devices):
            kind, mode = pick_control(dev)
            if mode is not None:
                try:
                    if kind == CTRL_SINGLE:
                        from openrgb.utils import RGBColor
                        mode.colors = [RGBColor(0, 0, 0)] * mode.colors_max
                    dev.set_mode(mode)
                except Exception:
                    kind = CTRL_NONE if kind == CTRL_SINGLE else kind
            ctrl.append((kind, mode))
            for zone in dev.zones:
                if zone.type != ZoneType.LINEAR:
                    continue
                key = f"{dev_names[di]} :: {zone.name}"
                want = self.cfg["led_counts"].get(key)
                if want is None and len(zone.leds) == 0:
                    want = DEFAULT_HEADER_LEDS
                    self.cfg["led_counts"][key] = want
                if want is not None and want != len(zone.leds):
                    try:
                        zone.resize(int(want))
                        changed = True
                    except Exception:
                        pass
        if changed:
            client.update()
        info = []
        for di, dev in enumerate(client.devices):
            try:
                location = dev.metadata.location
            except Exception:
                location = ""
            info.append({"name": dev_names[di], "location": location, "slow": is_slow_bus(location),
                         "ctrl": ctrl[di][0], "mode": ctrl[di][1].name if ctrl[di][1] else ""})
        with self.lock:
            self.client = client
            self.dev_ctrl = ctrl
            self.ogb_info = info
            self._ogb_sig = tuple(d.name for d in client.devices)
            self._devices_checked = time.perf_counter()
            self._last_sent = [(None, 0.0)] * len(client.devices)
        self._scan_extras(force=True)
        self._build_zones()

    # ---------- devices LightDeck drives itself ----------
    def _count_packet(self, name):
        self._packet_count[name] = self._packet_count.get(name, 0) + 1
        self.total_packets += 1

    def _bind_driver_store(self):
        """Give every driver class its own saved settings (inside config.json), e.g. paired Wi-Fi lights."""
        store = self.cfg.setdefault("driver_settings", {})
        for cls in self.driver_classes:
            cls.store = store.setdefault(cls.__name__, {})

    def _scan_extras(self, force=False):
        """Drop devices whose driver stopped, take in newly connected ones, and every 10 s look for more
        in the background (connecting can be slow, e.g. a Wi-Fi light that is switched off), so the
        lights never stutter. Returns True if the list changed."""
        changed = False
        for ex in [e for e in self.extras if not e.alive]:
            self.last_error = ex.error
            self.driver_problems[ex.display] = ex.error
            self.extras.remove(ex)
            try:
                ex.close()
            except Exception:
                pass
            changed = True
        with self.lock:
            new, self._new_extras = self._new_extras, []
        for ex, cls in new:
            if self._stop.is_set():
                ex.close()
                continue
            self.extras.append(ex)
            self._first_time_setup(cls, ex.display)
            changed = True
        now = time.perf_counter()
        if (force or now - self._extras_checked >= 10) and not self._finding and not self._stop.is_set():
            self._extras_checked = now
            self._finding = True
            threading.Thread(target=self._find_extras, daemon=True, name="find devices").start()
        return changed

    def _driver_problem(self, name, msg):
        if self.driver_problems.get(name) != msg:
            self.last_error = f"{name}: {msg}"
        self.driver_problems[name] = msg

    def _find_extras(self):
        """Background: ask every driver for its devices and connect the new ones."""
        try:
            import winhid
            ogb_ids = set()                    # devices OpenRGB already drives: leave them to it
            for info in self.ogb_info:
                ogb_ids |= winhid.ids_in(info.get("location", ""))
            with self.lock:
                running = list(self.extras) + [e for e, _ in self._new_extras]
            for cls in list(self.driver_classes):
                try:
                    found = [f for f in cls.find() if not (cls.ids_of(f) & ogb_ids)]
                    labels = [cls.label(f) for f in found]
                except Exception as e:
                    self._driver_problem(cls.name, str(e))
                    continue
                mine = [e for e in running if type(e) is cls and e.alive]
                for k, item in enumerate(found):
                    if self._stop.is_set():
                        return
                    if any(e.found == item for e in mine):
                        continue
                    same = [i for i, lab in enumerate(labels) if lab == labels[k]]
                    name = labels[k] if len(same) == 1 else f"{labels[k]} {same.index(k) + 1}"
                    try:
                        ex = cls(item, on_sent=self._count_packet, display_name=name)
                    except Exception as e:
                        self._driver_problem(name, str(e) or type(e).__name__)
                        continue
                    self.driver_problems.pop(name, None)
                    with self.lock:
                        self._new_extras.append((ex, cls))
        finally:
            self._finding = False

    # ---------- Wi-Fi / network lights (added in Settings) ----------
    def network_drivers(self):
        return [c for c in self.driver_classes if getattr(c, "network", False)]

    def network_lights(self):
        """[(driver class, saved entry, status text)] for every light added in Settings."""
        out = []
        for cls in self.network_drivers():
            for entry in cls.saved():
                ex = next((e for e in self.extras if type(e) is cls and e.found == entry and e.alive), None)
                if ex:
                    status = f"Connected  ·  {ex.leds} light{'s' if ex.leds != 1 else ''}"
                else:
                    name = cls.label(entry)
                    status = self.driver_problems.get(name) or "Looking for it..."
                out.append((cls, entry, status))
        return out

    def search_network(self):
        """Look for Wi-Fi lights on the network (takes a few seconds; call it from a background thread).
        Returns [(driver class, entry)] for the ones that aren't added yet, plus a list of problems."""
        found, problems = [], []
        for cls in self.network_drivers():
            try:
                saved_ids = {e.get("id") or e.get("address") for e in cls.saved()}
                for entry in cls.discover():
                    if (entry.get("id") or entry.get("address")) not in saved_ids:
                        found.append((cls, entry))
            except Exception as e:
                problems.append(f"{cls.kind_name}: {e}")
        return found, problems

    def add_network_light(self, cls, entry):
        """Pair (if the light needs it) and remember it. Blocking: call it from a background thread.
        Raises RuntimeError with what to do if pairing isn't possible yet."""
        entry = dict(entry)
        if cls.needs_pairing:
            entry.update(cls.pair(entry))
        with self.lock:
            saved = cls.saved()
            key = entry.get("id") or entry.get("address")
            saved[:] = [e for e in saved if (e.get("id") or e.get("address")) != key] + [entry]
        self._extras_checked = 0.0
        return entry

    def remove_network_light(self, cls, entry):
        with self.lock:
            saved = cls.saved()
            if entry in saved:
                saved.remove(entry)
        for ex in [e for e in self.extras if type(e) is cls and e.found == entry]:
            ex.alive = False             # taken out (and closed) on the next frame
            ex.error = ""

    def _first_time_setup(self, cls, name):
        """The first time a device with named rows shows up (like a keyboard): split it into its rows."""
        if not cls.rows:
            return
        done = self.cfg.setdefault("drivers_setup", [])
        if name in done or (name == "RK N80" and self.cfg.get("n80_setup_done")):
            return
        hw_key = f"{name} :: {cls.zone_name}"
        order = ORDER_ACROSS if cls.rows_stored == "across" else ORDER_ALONG
        self.cfg["layouts"].setdefault(hw_key, {"strips": len(cls.rows), "order": order, "zigzag": False})
        for i, row in enumerate(cls.rows):
            self.cfg["names"].setdefault(part_key(hw_key, i, "strip"), row)
        done.append(name)

    def _check_device_changes(self):
        """Every few seconds ask OpenRGB how many devices it has. Plugging something in or out
        makes OpenRGB re-detect; when its list changes we reconnect and the new light appears."""
        now = time.perf_counter()
        if now - self._devices_checked < 6:
            return
        self._devices_checked = now
        self.client.comms.requestDeviceNum()     # also reads any "device list changed" notice
        sig = tuple(d.name if d is not None else None for d in self.client.devices)
        if sig != self._ogb_sig:
            self.last_error = ""
            self.status = "Device list changed - reconnecting..."
            self._reconnect.set()

    def _scan_others(self, force=False):
        """List gaming devices that nothing here can control (runs in the background)."""
        now = time.perf_counter()
        if self._others_running or (not force and now - self._others_checked < 30):
            return
        self._others_checked = now
        self._others_running = True

        def work():
            try:
                import devscan
                handled = set()
                for info in self.ogb_info:
                    handled |= devscan.ids_in(info.get("location", ""))
                for ex in self.extras:
                    handled |= set(getattr(ex, "usb_ids", ()))
                self.other_devices = devscan.other_gaming_devices(handled)
            except Exception as e:
                self.last_error = f"Device scan: {e}"
            finally:
                self._others_running = False

        threading.Thread(target=work, daemon=True).start()

    def rescan(self):
        """Look for new devices everywhere: reconnect OpenRGB, re-check own drivers and others."""
        self.driver_classes, self.driver_errors = load_drivers(DRIVERS_DIR)
        self._bind_driver_store()
        self._extras_checked = 0.0
        self._others_checked = 0.0
        self._scan_others(force=True)
        self.reconnect()

    def device_note(self, dev_name):
        """Explanation for a device LightDeck drives itself (it sets its own pace), else None."""
        ex = next((e for e in self.extras if e.display == dev_name), None)
        return (getattr(ex, "note", None) or "This device is run by one of LightDeck's own drivers.") if ex else None

    def device_control(self, dev_name):
        """How a device is driven: CTRL_* for OpenRGB devices, "driver" for LightDeck's own drivers."""
        info = next((d for d in self.dev_info if d["name"] == dev_name), None)
        return info.get("ctrl") if info else None

    def control_note(self, dev_name):
        """Why an OpenRGB device behaves differently (no live mode), else None."""
        info = next((d for d in self.ogb_info if d["name"] == dev_name), None)
        kind = info.get("ctrl") if info else None
        if kind == CTRL_PERLED:
            return (f"This device has no live mode, so LightDeck uses its \"{info['mode']}\" mode and sends new "
                    f"colors at a gentler pace. Most effects work; very fast ones may look a bit choppy.")
        if kind == CTRL_SINGLE:
            return (f"This device can only show one color at a time (its \"{info['mode']}\" mode). LightDeck "
                    f"gives it the average color of the effect, at most {SINGLE_FPS} times a second by default, "
                    f"so solid colors and slow fades look best.")
        if kind == CTRL_NONE:
            return ("OpenRGB found this device, but it offers no color setting that other apps can change, "
                    "so LightDeck can't light it.")
        return None

    def _build_zones(self):
        """Turn the OpenRGB zones (and any parts you split them into) into strips to render."""
        from openrgb.utils import ZoneType

        zones, counts = [], []

        def add_zone(di, dev_name, zone_name, n, start, resizable, fixed=False, matrix=None):
            hw_key = f"{dev_name} :: {zone_name}"
            parts = self.segments(hw_key)
            lay = self.layout(hw_key)
            if lay and lay.get("order") == ORDER_ROWS and matrix:
                # one strip per row of the key map; gaps stay in so the columns line up between rows
                rows = [[start + v if v is not None and v < n else None for v in row] for row in matrix]
                rows = [idx for idx in rows if any(i is not None for i in idx)]   # skip empty rows
                for ri, idx in enumerate(rows):
                    zones.append(ZoneInfo(di, dev_name, hw_key, zone_name, n, start, idx, resizable,
                                          part=ri + 1, kind="row", fixed=fixed, matrix=matrix))
            elif lay and lay.get("order") != ORDER_ROWS and 1 < lay["strips"] <= n:
                # parallel strips side by side along the cable
                for si, idx in enumerate(strip_indices(n, lay["strips"], lay["order"], lay["zigzag"])):
                    zones.append(ZoneInfo(di, dev_name, hw_key, zone_name, n, start, [start + i for i in idx],
                                          resizable, part=si + 1, kind="strip", fixed=fixed))
            elif len(parts) > 1 and sum(parts) <= n:
                # parts cut one after another along the cable
                off = start
                for pi, size in enumerate(parts):
                    zones.append(ZoneInfo(di, dev_name, hw_key, zone_name, n, start, list(range(off, off + size)),
                                          resizable, part=pi + 1, fixed=fixed))
                    off += size
            else:
                zones.append(ZoneInfo(di, dev_name, hw_key, zone_name, n, start, list(range(start, start + n)),
                                      resizable, fixed=fixed, matrix=matrix))

        for di, dev in enumerate(self.client.devices):
            dev_name = self.dev_names[di] if di < len(self.dev_names) else dev.name
            start = 0
            for zone in dev.zones:
                hw_key = f"{dev_name} :: {zone.name}"
                n = len(zone.leds)
                looks_like_header = any(w in zone.name.lower() for w in ("header", "addressable", "argb"))
                resizable = zone.type == ZoneType.LINEAR and (hw_key in self.cfg["led_counts"] or looks_like_header)
                matrix = getattr(zone, "matrix_map", None) if zone.type == ZoneType.MATRIX else None
                if matrix and len(matrix) > 1 and n > 1:
                    self._auto_rows(hw_key, matrix)
                    add_zone(di, dev_name, zone.name, n, start, True, fixed=True, matrix=matrix)
                else:
                    add_zone(di, dev_name, zone.name, n, start, resizable)
                start += n
            counts.append(len(dev.leds))
        base = len(self.client.devices)
        for k, ex in enumerate(self.extras):
            matrix = getattr(ex, "matrix", None)
            if matrix and len(matrix) > 1:
                self._auto_rows(f"{ex.display} :: {ex.zone_name}", matrix)
            add_zone(base + k, ex.display, ex.zone_name, ex.leds, 0, True, fixed=True, matrix=matrix)
            counts.append(ex.leds)
        info = list(self.ogb_info) + [{"name": ex.display, "location": "LightDeck driver", "slow": False,
                                       "bus": ex.bus, "ctrl": "driver"} for ex in self.extras]
        with self.lock:
            self.zones, self.dev_led_counts = zones, counts
            self.dev_info = info
            self.states = {}
        total = sum(counts)
        extra = f" (+ {', '.join(e.display for e in self.extras)})" if self.extras else ""
        self.status = f"Connected: {len(counts)} devices, {total} LEDs{extra}"

    def _auto_rows(self, hw_key, matrix):
        """A keyboard or other grid: split it into its key rows the first time it shows up."""
        seen = self.cfg.setdefault("auto_rows", [])
        if hw_key not in seen:
            seen.append(hw_key)
            self.cfg["layouts"].setdefault(hw_key, {"strips": len(matrix), "order": ORDER_ROWS, "zigzag": False})

    def _disconnect(self):
        try:
            if self.client:
                self.client.disconnect()
        except Exception:
            pass
        self.client = None

    # ---------- main loop ----------
    def start(self):
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)   # precise frame timing on Windows
        except Exception:
            pass
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        for ex in self.extras:
            try:
                ex.close()
            except Exception:
                pass
        self._disconnect()
        try:
            import ctypes
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

    def _render_frame(self, t, dt):
        from openrgb.utils import RGBColor

        with self.lock:
            bright = max(0, min(100, self.cfg["brightness"])) / 100.0
            disabled = set(self.cfg["disabled"])
            overrides = set(self.cfg["overrides"])
            ident_keys, ident_until = self.identify
            identifying = time.perf_counter() < ident_until
            groups = {GLOBAL: []}
            for z in self.zones:
                if z.key in disabled or z.leds == 0:
                    continue
                groups.setdefault(z.key if z.key in overrides else GLOBAL, []).append(z)

            frames = [[(0, 0, 0)] * n for n in self.dev_led_counts]
            preview = {}
            for target, zones in groups.items():
                if not zones:
                    continue
                eff = self.get_effect(target)
                for i, z in enumerate(zones):
                    z.index, z.count = i, len(zones)
                    state = self.states.setdefault((target, z.key), {})
                    colors = [(0, 0, 0)] * z.leds
                    if eff is not None:
                        try:
                            colors = list(eff.render(t, dt, z.leds, z, state))[:z.leds]
                            colors += [(0, 0, 0)] * (z.leds - len(colors))
                        except Exception:
                            self.last_error = f"{eff.name}: {traceback.format_exc(limit=1).strip().splitlines()[-1]}"
                    if bright < 1.0:
                        colors = [(int(c[0] * bright), int(c[1] * bright), int(c[2] * bright)) for c in colors]
                    frame = frames[z.dev_idx]
                    for idx, c in zip(z.indices, colors):
                        if idx is not None:
                            frame[idx] = c
            if identifying:
                on = (255, 255, 255) if int(t * 4) % 2 else (0, 0, 0)
                for z in self.zones:
                    if z.key in ident_keys or z.hw_key in ident_keys or z.device in ident_keys:
                        frame = frames[z.dev_idx]
                        for idx in z.indices:
                            if idx is not None:
                                frame[idx] = on
            # "Show LED order": one dot walks through the header's LEDs in wiring order
            o_key, o_start, o_secs = self.order_test
            if o_key and time.perf_counter() - o_start < o_secs:
                z = next((z for z in self.zones if z.hw_key == o_key), None)
                if z is not None and z.hw_leds:
                    frame = frames[z.dev_idx]
                    pos = int((time.perf_counter() - o_start) / o_secs * z.hw_leds)
                    for k in range(z.hw_leds):
                        d = pos - k
                        frame[z.hw_start + k] = ((255, 255, 255) if d == 0 else (0, 60, 255) if 0 < d <= 3
                                                 else (0, 0, 0))
            elif o_key:
                self.order_test = ("", 0.0, 0.0)
            # devices that can only show one color: the whole device gets the frame's average
            for i, (kind, _mode) in enumerate(self.dev_ctrl):
                if kind == CTRL_SINGLE and i < len(frames) and frames[i]:
                    f = frames[i]
                    avg = tuple(sum(c[ch] for c in f) // len(f) for ch in range(3))
                    frames[i] = [avg] * len(f)
            black = (0, 0, 0)
            preview = {z.key: [frames[z.dev_idx][idx] if idx is not None else black for idx in z.indices]
                       for z in self.zones}
            self.preview = preview
            client = self.client
            ctrl = list(self.dev_ctrl)
            rates = [self.device_fps(d["name"]) for d in self.dev_info]

        now = time.perf_counter()
        for i, (dev, frame) in enumerate(zip(client.devices, frames)):
            kind, mode = ctrl[i] if i < len(ctrl) else (CTRL_DIRECT, None)
            if kind == CTRL_NONE or not frame:
                continue
            last_frame, last_time = self._last_sent[i] if i < len(self._last_sent) else (None, 0.0)
            since = now - last_time
            slow = i < len(self.dev_info) and self.dev_info[i]["slow"]
            min_gap = 1.0 / rates[i] if i < len(rates) else 0.0
            if kind == CTRL_SINGLE:
                # one color: skip tiny changes and never re-send the same color (each send changes the mode)
                changed = last_frame is None or max(abs(a - b) for a, b in zip(frame[0], last_frame[0])) \
                    >= SINGLE_MIN_CHANGE or (frame != last_frame and since >= 2.0)
                keepalive = None
            else:
                changed = frame != last_frame
                keepalive = KEEPALIVE_SLOW if (slow or kind == CTRL_PERLED) else KEEPALIVE_FAST
            # only send when the colors changed (and not faster than the device allows),
            # plus an occasional refresh in case an update got garbled on the way
            if (changed and since >= min_gap * 0.95) or (keepalive is not None and since >= keepalive):
                if kind == CTRL_SINGLE:
                    mode.colors = [RGBColor(*frame[0])] * mode.colors_max
                    send_mode(dev, mode)
                else:
                    send_leds(dev, frame)
                name = self.dev_info[i]["name"] if i < len(self.dev_info) else dev.name
                self._packet_count[name] = self._packet_count.get(name, 0) + 1
                self.total_packets += 1
                if i < len(self._last_sent):
                    self._last_sent[i] = (frame, now)
        base = len(client.devices)
        for k, ex in enumerate(self.extras):
            if base + k < len(frames):
                ex.submit(frames[base + k])

    def _loop(self):
        last = time.perf_counter()
        fps_count, fps_time = 0, last
        next_frame = last
        while not self._stop.is_set():
            if self._reconnect.is_set():
                self._reconnect.clear()
                self._disconnect()
            if self.client is None:
                try:
                    self._connect()
                except Exception as e:
                    self._disconnect()
                    self.status = f"Not connected ({e}) - retrying..."
                    self._stop.wait(3)
                    continue
                next_frame = time.perf_counter()
            try:
                self._check_device_changes()
            except Exception as e:
                self.status = f"Lost connection ({e}) - reconnecting..."
                self._disconnect()
                continue
            self._scan_others()
            if self._scan_extras():
                self._rebuild.set()
            if self._rebuild.is_set():
                self._rebuild.clear()
                self._build_zones()
            now = time.perf_counter()
            real_dt = now - last
            if real_dt > 0:
                self.inst_fps = 1 / real_dt if self.inst_fps == 0 else self.inst_fps * 0.85 + (1 / real_dt) * 0.15
            dt, last = min(real_dt, 0.1), now
            try:
                self._render_frame(now - self._t0, dt)
                spent = (time.perf_counter() - now) * 1000
                self.frame_ms = spent if self.frame_ms == 0 else self.frame_ms * 0.9 + spent * 0.1
            except Exception as e:
                self.status = f"Lost connection ({e}) - reconnecting..."
                self._disconnect()
                continue
            fps_count += 1
            if now - fps_time >= 1.0:
                self.actual_fps = fps_count / (now - fps_time)
                self.packets_per_sec = {k: v / (now - fps_time) for k, v in self._packet_count.items()}
                self._packet_count = {}
                fps_count, fps_time = 0, now
            # steady pacing: aim at a fixed schedule; time.sleep is precise, Event.wait is not on Windows
            frame_time = 1.0 / max(FPS_MIN, min(FPS_MAX, self.cfg["fps"]))
            next_frame += frame_time
            delay = next_frame - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_frame = time.perf_counter()   # fell behind: don't try to catch up
