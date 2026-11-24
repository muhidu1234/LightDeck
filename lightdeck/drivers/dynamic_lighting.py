"""Windows Dynamic Lighting devices: anything that speaks the USB "LampArray" lighting standard.

Many newer keyboards, mice, headsets and light strips (Razer, Logitech, ASUS, Corsair, HyperX, ...)
support Windows 11's Dynamic Lighting. They all describe and accept lighting the same way, set by
the USB HID standard (usage page 0x59, "Lighting And Illumination"):

  LampArrayAttributesReport     how many lamps, kind of device, fastest update interval
  LampAttributesRequest/Response where each lamp sits (micrometers) and which colors it can show
  LampMultiUpdateReport         new colors for up to N lamps at once (N set by the device)
  LampArrayControlReport        AutonomousMode: 0 = the computer drives the lamps, 1 = the device's own lighting

LightDeck talks to the device directly (no Windows app API, so it also works in the background).
Windows' report parser packs the bits, so it works whatever report numbers a device uses.
When LightDeck stops, the device is handed back to its own lighting (AutonomousMode = 1).
"""
import winhid
from driver_base import Driver

PAGE = 0x59
LAMP_ARRAY = 0x01
ATTRIBUTES, LAMP_COUNT, BOX_W, BOX_H, BOX_D, KIND, MIN_INTERVAL = 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08
REQUEST, LAMP_ID, RESPONSE = 0x20, 0x21, 0x22
POS_X, POS_Y, POS_Z, PURPOSES, LATENCY = 0x23, 0x24, 0x25, 0x26, 0x27
RED_LEVELS, GREEN_LEVELS, BLUE_LEVELS, INTENSITY_LEVELS, PROGRAMMABLE = 0x28, 0x29, 0x2A, 0x2B, 0x2C
MULTI, RED, GREEN, BLUE, INTENSITY, FLAGS = 0x50, 0x51, 0x52, 0x53, 0x54, 0x55
CONTROL, AUTONOMOUS = 0x70, 0x71
UPDATE_COMPLETE = 0x01

KINDS = {1: "Keyboard", 2: "Mouse", 3: "Game controller", 4: "Peripheral", 5: "Scene", 6: "Notification",
         7: "Chassis", 8: "Wearable", 9: "Furniture", 10: "Art"}
ZONE_NAMES = {1: "Keys", 2: "Mouse lights", 7: "Case lights"}
KEY_PITCH = 19050          # one standard key, in micrometers


class Lamp:
    def __init__(self, lamp_id, x, y, z, levels, programmable):
        self.id, self.x, self.y, self.z = lamp_id, x, y, z
        self.levels = levels                    # (red, green, blue, intensity) level counts
        self.programmable = programmable

    def value(self, color):
        """(r, g, b) 0-255 -> the (red, green, blue, intensity) values this lamp takes."""
        rl, gl, bl, il = self.levels
        if max(rl, gl, bl) > 0:
            return (round(color[0] * rl / 255), round(color[1] * gl / 255), round(color[2] * bl / 255), il)
        return (0, 0, 0, round(max(color) * il / 255))      # a lamp that only has brightness


def plan_layout(lamps, kind):
    """Order the lamps for effects. Keyboards get a key map (rows of frame positions, None = gap)
    so effects line up across the keys; everything else becomes one line along its longest side.
    Returns (lamp ids in frame order, matrix or None)."""
    if kind == 1 and len(lamps) > 8:
        rows = []
        for lamp in sorted(lamps, key=lambda l: (l.y, l.x)):
            if rows and lamp.y - rows[-1][0].y <= KEY_PITCH * 0.45:
                rows[-1].append(lamp)
            else:
                rows.append([lamp])
        if len(rows) >= 2:
            min_x = min(l.x for l in lamps)
            order, cells = [], []
            for row in rows:
                placed = {}
                for lamp in sorted(row, key=lambda l: l.x):
                    col = max(0, round((lamp.x - min_x) / (KEY_PITCH / 2)))    # half-key steps
                    while col in placed:
                        col += 1
                    placed[col] = len(order)
                    order.append(lamp.id)
                cells.append(placed)
            width = max(max(p) for p in cells) + 1
            matrix = [[p.get(c) for c in range(width)] for p in cells]
            return order, matrix
    span_x = max(l.x for l in lamps) - min(l.x for l in lamps)
    span_y = max(l.y for l in lamps) - min(l.y for l in lamps)
    key = (lambda l: (l.x, l.y, l.id)) if span_x >= span_y else (lambda l: (l.y, l.x, l.id))
    return [l.id for l in sorted(lamps, key=key)], None


class DynamicLighting(Driver):
    name = "Dynamic Lighting device"
    zone_name = "Lights"
    bus = "HID"
    keepalive = None           # the device keeps its colors; only changed lamps are sent
    note = ("This device uses Windows' Dynamic Lighting standard, and LightDeck drives it directly. If Windows' "
            "own Dynamic Lighting is also switched on for it (Settings > Personalization > Dynamic Lighting), "
            "turn it off there, or Windows and LightDeck will take turns. When LightDeck closes, the device goes "
            "back to its own lighting.")

    @classmethod
    def find(cls):
        return winhid.devices(usage_page=PAGE, usage=LAMP_ARRAY)

    @classmethod
    def label(cls, found):
        h = winhid.open_path(found.path)
        try:
            return (winhid.product_string(h) if h else "") or cls.name
        finally:
            winhid.close(h)

    # ---------- talking to the device ----------
    def _new(self, coll):
        rtype = self.r.report_type(coll)
        return rtype, self.r.new(rtype, self.r.report_id(rtype, coll))

    def _send(self, rtype, buf):
        if rtype == winhid.FEATURE:
            winhid.set_feature(self.h, buf.raw)
        else:
            winhid.set_output_report(self.h, buf.raw)

    def _read(self, coll):
        rtype, buf = self._new(coll)
        winhid.get_feature_into(self.h, buf)
        return buf

    def _get(self, buf, coll, usage):
        vals = self.r.get(winhid.FEATURE, buf, coll, PAGE, usage)
        return vals[0] if vals else 0

    def _autonomous(self, on):
        rtype, buf = self._new(self.coll[CONTROL])
        self.r.set(rtype, buf, self.coll[CONTROL], PAGE, AUTONOMOUS, [1 if on else 0])
        self._send(rtype, buf)

    # ---------- driver ----------
    def connect(self, found):
        self.r = None
        self.h = winhid.open_path(found.path)
        if not self.h:
            raise RuntimeError("could not open it (another lighting app may be using it)")
        self.usb_ids = [(found.vid, found.pid)]
        self.r = winhid.Reports(self.h)
        self.coll = {u: self.r.collection(PAGE, u) for u in (ATTRIBUTES, REQUEST, RESPONSE, MULTI, CONTROL)}
        missing = [hex(u) for u, c in self.coll.items() if c is None]
        if missing:
            raise RuntimeError(f"incomplete Dynamic Lighting description (missing {', '.join(missing)})")

        attrs = self._read(self.coll[ATTRIBUTES])
        count = self._get(attrs, self.coll[ATTRIBUTES], LAMP_COUNT)
        self.kind = self._get(attrs, self.coll[ATTRIBUTES], KIND)
        interval = self._get(attrs, self.coll[ATTRIBUTES], MIN_INTERVAL)       # microseconds
        if count <= 0:
            raise RuntimeError("the device reports no lamps")

        lamps = []
        req = self.coll[REQUEST]
        for lamp_id in range(count):
            rtype, buf = self._new(req)
            self.r.set(rtype, buf, req, PAGE, LAMP_ID, [lamp_id])
            self._send(rtype, buf)
            resp = self._read(self.coll[RESPONSE])
            c = self.coll[RESPONSE]
            levels = tuple(self._get(resp, c, u) for u in (RED_LEVELS, GREEN_LEVELS, BLUE_LEVELS, INTENSITY_LEVELS))
            lamps.append(Lamp(self._get(resp, c, LAMP_ID), self._get(resp, c, POS_X), self._get(resp, c, POS_Y),
                              self._get(resp, c, POS_Z), levels, bool(self._get(resp, c, PROGRAMMABLE))))
        usable = [l for l in lamps if l.programmable] or lamps
        self.lamps = {l.id: l for l in usable}
        self.order, self.matrix = plan_layout(usable, self.kind)
        self.leds = len(self.order)
        self.zone_name = ZONE_NAMES.get(self.kind, "Lights")
        if interval:
            self.max_fps = max(1, min(60, int(1_000_000 / interval)))
        m = self.coll[MULTI]
        self.multi_type = self.r.report_type(m)
        self.per_report = min(self.r.count(self.multi_type, m, PAGE, u) for u in (LAMP_ID, RED, GREEN, BLUE))
        if self.per_report <= 0:
            raise RuntimeError("the device's update report has no room for lamps")
        self.sent = {}
        self._autonomous(False)

    def send(self, colors):
        changed = []
        for pos, color in enumerate(colors[:self.leds]):
            lamp = self.lamps[self.order[pos]]
            v = lamp.value(color)
            if self.sent.get(lamp.id) != v:
                changed.append((lamp.id, v))
        if not changed:
            return
        m, rtype, k = self.coll[MULTI], self.multi_type, self.per_report
        chunks = [changed[i:i + k] for i in range(0, len(changed), k)]
        for ci, chunk in enumerate(chunks):
            buf = self.r.new(rtype, self.r.report_id(rtype, m))
            self.r.set(rtype, buf, m, PAGE, LAMP_COUNT, [len(chunk)])
            self.r.set(rtype, buf, m, PAGE, FLAGS, [UPDATE_COMPLETE if ci == len(chunks) - 1 else 0])
            self.r.set(rtype, buf, m, PAGE, LAMP_ID, [lid for lid, _ in chunk])
            for ch, usage in enumerate((RED, GREEN, BLUE, INTENSITY)):
                self.r.set(rtype, buf, m, PAGE, usage, [v[ch] for _, v in chunk])
            self._send(rtype, buf)
        for lid, v in changed:
            self.sent[lid] = v

    def disconnect(self):
        try:
            if self.r and self.h:
                self._autonomous(True)          # give the lamps back to the device's own lighting
        finally:
            if self.r:
                self.r.close()
            winhid.close(self.h)
