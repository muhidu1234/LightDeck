"""Building blocks for LightDeck's own device drivers (for lights OpenRGB can't control).

Every file in the `drivers` folder can hold one or more `Driver` classes. LightDeck looks for
their devices at start-up and every 10 seconds, and runs each connected device on its own
thread, so a slow device never holds up the others. Files starting with "_" are ignored.

A driver only has to say which USB device it is for and how to send one frame of colors:

    from driver_base import Driver
    import winhid

    class MyStrip(Driver):
        name = "My LED strip"
        usb_ids = [(0x1234, 0x5678)]
        leds = 30

        @classmethod
        def find(cls):
            return [d.path for d in winhid.devices(0x1234, 0x5678, usage_page=0xFF00)]

        def connect(self, found):
            self.h = winhid.open_path(found)
            if not self.h:
                raise RuntimeError("could not open it (is its own app running?)")

        def send(self, colors):          # colors: `leds` (r, g, b) tuples
            data = [0x00, 0x01] + [x for c in colors for x in c]
            winhid.write(self.h, data, 65)

        def disconnect(self):
            winhid.close(self.h)
"""
import importlib.util
import threading
import time
import traceback


class Driver:
    # ---- describe the device (class attributes) ----
    name = "Unnamed device"       # shown in the Lights list
    maker = ""
    usb_ids = []                  # [(vendor id, product id), ...] this driver handles
    zone_name = "LEDs"            # name of its light in the list
    leds = 0                      # colors sent in every frame
    bus = "USB"
    note = ""                     # shown in the app instead of the speed slider: speed, conflicts...
    max_fps = 60                  # never send faster than this
    keepalive = 1.0               # re-send an unchanged frame after this many seconds (None = never)
    rows = None                   # e.g. ["F-key row", "Number row", ...]: the first time the device shows
                                  # up its light is split into these rows (leds = columns x rows)
    rows_stored = "along"         # how the frame holds the grid: "along" = row by row,
                                  # "across" = column by column (one LED of every row, then the next column)
    matrix = None                 # or a key map: rows of frame positions (None = gap), like OpenRGB keyboards.
                                  # Set it in connect(); the light is split into its rows the first time.

    # ---- Wi-Fi / network lights: found by searching the network and added in Settings ----
    network = False               # True for a network driver
    kind_name = ""                # e.g. "WLED", "Philips Hue" (shown in Settings)
    needs_pairing = False         # the light must give LightDeck a key first (e.g. press the Hue Bridge button)
    pair_hint = ""                # what to do before pairing / adding
    store = {}                    # this driver's saved settings in config.json (set by LightDeck)

    @classmethod
    def saved(cls):
        """Network lights added in Settings: [{"address", "name", "id", ...}] (kept in config.json)."""
        return cls.store.setdefault("devices", [])

    @classmethod
    def discover(cls):
        """Network drivers: look for lights on the network. [{"address", "name", "id"}]"""
        return []

    @classmethod
    def pair(cls, entry):
        """Network drivers that need it: get a key from the light. Returns what to save with it
        (e.g. {"token": ...}); raises RuntimeError("what to do") if the light isn't ready."""
        return {}

    @classmethod
    def label(cls, found):
        """Name shown for a device find() returned (e.g. its product name)."""
        if isinstance(found, dict):
            return found.get("name") or f"{cls.kind_name or cls.name} {found.get('address', '')}".strip()
        return cls.name

    @classmethod
    def ids_of(cls, found):
        """USB (vendor, product) IDs of a device find() returned: used to skip devices OpenRGB already drives."""
        if isinstance(found, dict):
            return set()                                            # network lights have no USB IDs
        if hasattr(found, "vid") and hasattr(found, "pid"):        # a winhid.HidInterface
            return {(found.vid, found.pid)}
        import winhid
        return winhid.ids_in(getattr(found, "path", str(found)))

    # ---- what a driver implements ----
    @classmethod
    def find(cls):
        """Return one value per connected device (usually its HID path); [] when none is plugged in.
        Network drivers: the lights added in Settings."""
        return list(cls.saved()) if cls.network else []

    def connect(self, found):
        """Open the device that find() returned `found` for. Raise an error if that fails."""

    def send(self, colors):
        """Send one frame: a list of `leds` (r, g, b) tuples. Raise OSError if the device is gone."""
        raise NotImplementedError

    def disconnect(self):
        """Close the device."""

    # ---- run by LightDeck (no need to touch) ----
    def __init__(self, found, on_sent=None, display_name=None):
        self.found = found
        self.display = display_name or self.name
        self.on_sent = on_sent
        self.latest = None
        self.alive = True
        self.error = ""
        try:
            self.connect(found)
        except Exception:
            try:
                self.disconnect()          # don't leave a half-opened device behind
            except Exception:
                pass
            raise
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"driver {self.display}")
        self._thread.start()

    @property
    def vid(self):
        return self.usb_ids[0][0] if self.usb_ids else 0

    @property
    def pid(self):
        return self.usb_ids[0][1] if self.usb_ids else 0

    def submit(self, frame):
        """Hand over the newest frame; the driver's thread sends it when the device is ready."""
        self.latest = frame

    def _run(self):
        last, last_time = None, 0.0
        gap = 1.0 / max(1, self.max_fps)
        while self.alive:
            frame = self.latest
            now = time.perf_counter()
            due = frame is not None and now - last_time >= gap and (
                frame is not last or (self.keepalive is not None and now - last_time >= self.keepalive))
            if not due:
                time.sleep(0.005)
                continue
            try:
                self.send(frame)
                last, last_time = frame, now
                if self.on_sent:
                    self.on_sent(self.display)
            except OSError as e:
                self.error = f"{self.display} stopped responding ({e}) - unplugged?"
                self.alive = False
            except Exception:
                self.error = f"{self.display}: {traceback.format_exc(limit=1).strip().splitlines()[-1]}"
                self.alive = False

    def close(self):
        self.alive = False
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=1)
        try:
            self.disconnect()
        except Exception:
            pass


def load_drivers(folder):
    """Import every drivers/*.py file and collect the Driver classes in it."""
    classes, errors = [], []
    for path in sorted(folder.glob("*.py")) if folder.exists() else []:
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"lightdeck_driver_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for obj in vars(module).values():
                if isinstance(obj, type) and issubclass(obj, Driver) and obj is not Driver \
                        and obj.__module__ == module.__name__:
                    classes.append(obj)
        except Exception:
            errors.append(f"{path.name}: {traceback.format_exc(limit=2).strip().splitlines()[-1]}")
    return classes, errors
