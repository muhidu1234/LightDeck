"""Royal Kludge N80 keyboard (USB 258a:0187, wired) per-key lighting.

The protocol was recorded from RK's own software (RK Keyboard 4.6) with USBPcap.
LightDeck only sends the exact message RK's app sends for live per-key colors:

    HID feature report #9 on interface 1, 520 bytes:
    09 08 00 00 01 00 7a 01 | 378 bytes of colors | zero padding
    colors: 126 slots x 3 bytes in the order (G, R, B). Slots are a 21 x 6 grid stored column by column:
    slot = column * 6 + row   (Esc = column 0 row 0 = slot 0, F1 = column 2 row 0 = slot 12)
"""
import winhid
from driver_base import Driver

VID, PID = 0x258A, 0x0187
REPORT_LEN = 520
COLS, ROWS = 21, 6
SLOTS = COLS * ROWS            # 126
HEADER = bytes([0x09, 0x08, 0x00, 0x00, 0x01, 0x00, 0x7A, 0x01])


def find_path():
    """Path of the N80's lighting interface (feature reports of 520 bytes), or None."""
    found = winhid.devices(VID, PID, interface=1, feature_len=REPORT_LEN)
    return found[0].path if found else None


def slot(col, row):
    return col * ROWS + row


def frame_bytes(colors):
    """126 (r, g, b) colors indexed by slot -> the 520-byte report."""
    data = bytearray(HEADER)
    for r, g, b in colors[:SLOTS]:
        # the N80 stores each key as GREEN, RED, BLUE (confirmed with a live test)
        data += bytes((g & 255, r & 255, b & 255))
    return bytes(data) + bytes(REPORT_LEN - len(data))


class RKN80(Driver):
    name = "RK N80"
    maker = "Royal Kludge"
    usb_ids = [(VID, PID)]     # wired only: lighting doesn't go over its 2.4 GHz receiver (258a:0150)
    zone_name = "Keys"
    leds = SLOTS
    bus = "HID"
    keepalive = 0          # stream non-stop: if frames stop it falls back to the lighting saved in RK's app
    rows = ["F-key row", "Number row", "Q row", "A row", "Z row", "Space row"]
    rows_stored = "across"   # the frame is in slot order: column by column, one key of every row each
    note = ("Keyboard over USB 1.1: it accepts about 7 updates per second (the same as RK's own app), "
            "so LightDeck keeps sending it the newest frame as fast as it can. Slow, flowing effects look "
            "best on it. If RK's app is running it will fight with LightDeck - close it.")

    @classmethod
    def find(cls):
        path = find_path()
        return [path] if path else []

    def connect(self, found):
        self.h = winhid.open_path(found)
        if not self.h:
            raise RuntimeError("Could not open the RK N80 (is RK's own app still running?)")

    def send(self, colors):
        winhid.set_feature(self.h, frame_bytes(colors))

    def disconnect(self):
        winhid.close(self.h)
