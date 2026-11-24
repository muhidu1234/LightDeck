from effect_base import *


class RainbowStrips(Effect):
    name = "Rainbow Strips"
    description = "Every strip runs its own rainbow at its own speed and direction, with its own pulse."
    params = {
        "speed": Param("Overall Speed", "number", 40, 1, 100),
        "hue_spread": Param("Color Difference Between Zones", "number", 50, 0, 180),
        "stretch": Param("Rainbow Width", "number", 40, 1, 100),
        "variety": Param("Speed Difference Between Zones", "number", 70, 0, 100),
        "pulse": Param("Brightness Pulse", "number", 15, 0, 60),
        "alternate": Param("Alternate Directions", "bool", True),
        "use_palette": Param("Use My Palette Instead of Rainbow", "bool", False),
        "palette": Param("Strip Colors", "palette", ["#3082dd", "#65bef7", "#9eaaeb", "#da5daa"],
                       show_if={"use_palette": True}),
    }

    def render(self, t, dt, n, zone, state):
        r = zone_random(zone, "speed")
        speed_mult = 1 + (r * 1.5 - 0.6) * self.v("variety") / 100
        direction = -1 if (self.v("alternate") and zone.index % 2) else 1
        base = zone.index * self.v("hue_spread") + t * self.v("speed") * 3 * speed_mult * direction
        pulse_rate = 0.6 + zone_random(zone, "pulse") * 1.2
        level = 1 - self.v("pulse") / 100 * (0.5 + 0.5 * math.sin(t * pulse_rate * 2 + zone.index))
        per_led = 360 * self.v("stretch") / 40 / max(1, n)
        if self.v("use_palette"):
            pal = self.colors("palette")
            return [scale(palette(pal, (base + i * per_led) / 360), level) for i in range(n)]
        return [hsv(base + i * per_led, 1, level) for i in range(n)]
