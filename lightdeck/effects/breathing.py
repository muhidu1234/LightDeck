from effect_base import *


class Breathing(Effect):
    name = "Breathing"
    description = "Slowly fades in and out. Each zone can breathe a little after the previous one."
    params = {
        "color": Param("Color", "color", "#00aaff", show_if={"use_palette": False, "rainbow": False}),
        "speed": Param("Speed", "number", 30, 1, 100),
        "low": Param("Lowest Brightness", "number", 5, 0, 90),
        "stagger": Param("Delay Between Zones", "number", 25, 0, 100),
        "rainbow": Param("Change Color Each Breath", "bool", False, show_if={"use_palette": False},
                       hint="Goes through the rainbow, one color per breath."),
        "use_palette": Param("Cycle Through Palette Instead", "bool", False),
        "palette": Param("Breath Colors", "palette", ["#3082dd", "#da5daa", "#65bef7"], show_if={"use_palette": True}),
    }

    def render(self, t, dt, n, zone, state):
        phase = t * self.v("speed") * 0.06 - zone.index * self.v("stagger") / 100 * math.pi
        level = (math.sin(phase) + 1) / 2
        low = self.v("low") / 100
        level = low + (1 - low) * level * level
        breath = math.floor((phase + math.pi / 2) / (2 * math.pi))
        if self.v("use_palette"):
            pal = self.colors("palette")
            base = pal[breath % len(pal)]
        elif self.v("rainbow"):
            base = hsv(breath * 67)
        else:
            base = hex_to_rgb(self.v("color"))
        return [scale(base, level)] * n
