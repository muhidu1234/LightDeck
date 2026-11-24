"""Template for a new LightDeck driver (files starting with "_" are ignored).

Copy this file, rename it (e.g. my_keyboard.py) and fill in the parts marked TODO.
How to find the bytes to send: record what the device's own lighting app sends with USBPcap
(see the tools folder), then copy that message here. Test with slow, simple colors first.
"""
import winhid
from driver_base import Driver

VID, PID = 0x0000, 0x0000          # TODO: the device's USB vendor and product ID


class MyDevice(Driver):
    name = "My device"             # TODO: shown in the Lights list
    maker = ""
    usb_ids = [(VID, PID)]
    zone_name = "LEDs"
    leds = 0                       # TODO: how many colors one frame holds
    max_fps = 30                   # TODO: lower it if the device can't keep up
    note = ""                      # optional: shown on the device's page in the app

    @classmethod
    def find(cls):
        # TODO: pick the interface that takes the lighting commands (interface / usage_page / report size)
        return [d.path for d in winhid.devices(VID, PID, usage_page=0xFF00)]

    def connect(self, found):
        self.h = winhid.open_path(found)
        if not self.h:
            raise RuntimeError(f"Could not open the {self.name} (is its own app still running?)")

    def send(self, colors):
        # TODO: build the message the device expects; colors is a list of (r, g, b), 0-255
        data = bytearray([0x00])                     # report number
        for r, g, b in colors:
            data += bytes((r, g, b))
        winhid.write(self.h, data, 65)               # or winhid.set_feature(self.h, data, length)

    def disconnect(self):
        winhid.close(self.h)
