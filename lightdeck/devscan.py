"""Find gaming devices (keyboards, mice, LED controllers...) that nothing in LightDeck can light yet.

Only reads device names and types from Windows; never sends anything to a device.
They are listed in the app so you can see what was found and why it isn't controllable.
"""
import ctypes
import re

import winhid as _h

# Makers of RGB gaming gear (USB vendor IDs)
RGB_VENDORS = {
    0x046D: "Logitech", 0x1532: "Razer", 0x1B1C: "Corsair", 0x1038: "SteelSeries",
    0x0951: "HyperX", 0x03F0: "HyperX / HP", 0x258A: "SinoWealth (RK, Aula, ...)",
    0x0C45: "Sonix (Redragon, ...)", 0x04D9: "Holtek", 0x2516: "Cooler Master",
    0x1E7D: "ROCCAT / Turtle Beach", 0x3434: "Keychron", 0x320F: "Evision", 0x3554: "Compx (VXE, ATK)",
    0x0B05: "ASUS", 0x1462: "MSI", 0x048D: "ITE", 0x26CE: "ASRock", 0x1E71: "NZXT",
    0x3633: "Glorious", 0x342D: "Glorious", 0x2F68: "Hator / Akko", 0x1EA7: "SHARKOON",
    0x05AC: None,   # Apple: never RGB
}
KEYWORDS = re.compile(r"rgb|led|aura|mystic|polychrome|fusion|light|argb|gaming|keyboard|mouse", re.I)

# Devices we know something specific about
NOTES = {
    (0x258A, 0x0150): "This is the RK N80's 2.4 GHz wireless receiver. The N80's lighting is controlled "
                      "through its USB cable, where LightDeck already drives it.",
    (0x046D, 0xC099): "Logitech G502 X (wired). This model has no RGB lighting (only the G502 X PLUS does).",
}

_hid = _h._hid


def ids_in(text):
    """All (vid, pid) pairs mentioned in a device path / location string."""
    return {(int(v, 16), int(p, 16)) for v, p in re.findall(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", text or "", re.I)}


def _string(fn, h):
    buf = ctypes.create_unicode_buffer(128)
    return buf.value.strip() if fn(h, buf, ctypes.sizeof(buf)) else ""


def other_gaming_devices(handled=()):
    """[{vid, pid, name, maker, kinds, note}] for gaming devices not in `handled` (a set of (vid, pid))."""
    found = {}
    for path in _h.hid_paths():
        ids = ids_in(path)
        if not ids:
            continue
        vid, pid = next(iter(ids))
        if (vid, pid) in handled or vid not in RGB_VENDORS or RGB_VENDORS[vid] is None:
            continue
        h = _h.open_path(path)
        if not h:
            continue
        try:
            entry = found.setdefault((vid, pid), {"vid": vid, "pid": pid, "name": "", "maker": RGB_VENDORS[vid],
                                                  "kinds": set()})
            if not entry["name"]:
                entry["name"] = _string(_hid.HidD_GetProductString, h)
            pre = ctypes.c_void_p()
            if _hid.HidD_GetPreparsedData(h, ctypes.byref(pre)):
                caps = _h.HIDP_CAPS()
                _hid.HidP_GetCaps(pre, ctypes.byref(caps))
                _hid.HidD_FreePreparsedData(pre)
                if caps.UsagePage == 1 and caps.Usage == 6:
                    entry["kinds"].add("keyboard")
                elif caps.UsagePage == 1 and caps.Usage == 2:
                    entry["kinds"].add("mouse")
                elif caps.UsagePage >= 0xFF00:
                    entry["kinds"].add("vendor-specific")   # where lighting commands usually go
        finally:
            _h._k32.CloseHandle(h)
    out = []
    for (vid, pid), e in sorted(found.items()):
        looks_gaming = bool(e["kinds"] & {"keyboard", "mouse"}) or bool(KEYWORDS.search(e["name"]))
        if not looks_gaming and (vid, pid) not in NOTES:
            continue
        e["kinds"] = sorted(e["kinds"])
        e["name"] = e["name"] or f"{e['maker']} device"
        e["note"] = NOTES.get((vid, pid), "")
        out.append(e)
    return out


if __name__ == "__main__":
    for d in other_gaming_devices():
        print(f"{d['vid']:04x}:{d['pid']:04x}  {d['name']!r:30} {d['maker']:28} {d['kinds']}  {d['note'][:60]}")
