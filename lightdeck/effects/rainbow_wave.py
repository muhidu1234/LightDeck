from effect_base import *


class RainbowWave(Effect):
    name = "Rainbow Wave"
    description = "A smooth rainbow flowing along every strip, all in sync."
    params = {
        "speed": Param("Speed", "number", 40, 0, 100),
        "width": Param("Rainbows per Strip (x10)", "number", 10, 1, 50),
        "saturation": Param("Saturation", "number", 100, 0, 100),
        "reverse": Param("Reverse Direction", "bool", False),
        "zone_shift": Param("Color Shift Between Zones", "number", 0, 0, 180),
        "use_palette": Param("Use My Palette Instead of Rainbow", "bool", False),
        "palette": Param("Wave Colors", "palette", ["#3082dd", "#65bef7", "#9eaaeb", "#da5daa"],
                       show_if={"use_palette": True}),
    }

    def render(self, t, dt, n, zone, state):
        d = -1 if self.v("reverse") else 1
        spread = 360 * self.v("width") / 10
        base = t * self.v("speed") * 3 * d + zone.index * self.v("zone_shift")
        s = self.v("saturation") / 100
        if self.v("use_palette"):
            pal = self.colors("palette")
            return [palette(pal, (base - (i / max(1, n)) * spread * d) / 360) for i in range(n)]
        return [hsv(base - (i / max(1, n)) * spread * d, s) for i in range(n)]
