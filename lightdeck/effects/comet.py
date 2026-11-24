from effect_base import *


class Comet(Effect):
    name = "Comet Chase"
    description = "Bright comets with fading tails chase around each strip."
    params = {
        "speed": Param("Speed", "number", 50, 1, 100),
        "count": Param("Number of Comets", "number", 2, 1, 10),
        "tail": Param("Tail Length (% of strip)", "number", 30, 5, 100),
        "color_mode": Param("Color Mode", "choice", "Palette", options=["Palette", "Rainbow", "Custom", "Shifting"]),
        "palette": Param("Comet Colors", "palette", ["#ff2a6d", "#00f0ff", "#fcee0a"],
                     show_if={"color_mode": "Palette"}),
        "tail_blend": Param("Tail Fades Through Palette", "bool", False, show_if={"color_mode": "Palette"}),
        "color": Param("Custom Color", "color", "#ff00ff", show_if={"color_mode": "Custom"}),
        "bounce": Param("Bounce Back and Forth", "bool", False),
    }

    def render(self, t, dt, n, zone, state):
        if n == 0:
            return []
        out = [(0, 0, 0)] * n
        count = int(self.v("count"))
        tail = max(1, self.v("tail") / 100 * n)
        travel = t * self.v("speed") / 100 * max(n, 10) * 0.8
        for c in range(count):
            p = travel + c * n / count + zone.index * n / 7
            if self.v("bounce"):
                p = p % (2 * n)
                head, d = (p, 1) if p < n else (2 * n - p, -1)
            else:
                head, d = p % n, 1
            mode = self.v("color_mode")
            pal = self.colors("palette")
            tail_cols = None
            if mode == "Palette":
                col = pal[c % len(pal)]
                if self.v("tail_blend") and len(pal) > 1:
                    start = c % len(pal)
                    tail_cols = pal[start:] + pal[:start]
            elif mode == "Custom":
                col = hex_to_rgb(self.v("color"))
            elif mode == "Shifting":
                col = hsv(t * 40 + c * 360 / count)
            else:
                col = hsv(c * 360 / count + zone.index * 50)
            for k in range(int(tail) + 1):
                i = int(head - k * d)
                if not self.v("bounce"):
                    i %= n
                if 0 <= i < n:
                    seg = gradient(tail_cols, k / (tail + 1)) if tail_cols else col
                    out[i] = add(out[i], scale(seg, (1 - k / (tail + 1)) ** 2))
        return out
