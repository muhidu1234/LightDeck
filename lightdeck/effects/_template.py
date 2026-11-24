"""TEMPLATE - copy this file, rename the copy (no underscore at the start,
e.g. my_effect.py), change `name`, and save. It shows up in LightDeck
within a second, and every time you save it reloads live.

Files starting with "_" are ignored, so this template never shows up itself.
"""
from effect_base import *


class MyEffect(Effect):
    name = "My Effect"                       # what the dropdown shows
    description = "Describe what it does."

    # Each Param becomes a control in the app. Read it with self.v("key").
    params = {
        "speed": Param("Speed", "number", 50, 1, 100),                 # slider
        "color": Param("Color", "color", "#ff0066"),                   # color picker
        "style": Param("Style", "choice", "Smooth", options=["Smooth", "Sharp"]),  # dropdown
        "reverse": Param("Reverse", "bool", False),                   # checkbox
    }

    def render(self, t, dt, n, zone, state):
        # t     = seconds since start      dt = seconds since last frame
        # n     = LEDs in this strip        zone.index / zone.count = which strip this is
        # state = a dict you can keep things in between frames (per strip)
        base = hex_to_rgb(self.v("color"))
        out = []
        for i in range(n):
            pos = (n - 1 - i) if self.v("reverse") else i
            wave = math.sin(pos * 0.3 - t * self.v("speed") / 10 + zone.index)
            level = (wave + 1) / 2 if self.v("style") == "Smooth" else (1.0 if wave > 0 else 0.0)
            out.append(scale(base, level))
        return out        # one (r, g, b) per LED, each 0-255
