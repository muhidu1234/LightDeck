from effect_base import *


class Solid(Effect):
    name = "Solid Color"
    description = "One steady color on everything."
    params = {
        "color": Param("Color", "color", "#ff0080"),
    }

    def render(self, t, dt, n, zone, state):
        return [hex_to_rgb(self.v("color"))] * n
