from effect_base import *


class Fire(Effect):
    name = "Fire"
    description = "Flickering flames rising along each strip (classic heat simulation)."
    params = {
        "cooling": Param("Cooling (shorter flames)", "number", 55, 20, 100),
        "sparking": Param("Sparking (more flames)", "number", 120, 50, 200),
        "speed": Param("Speed", "number", 60, 10, 100),
        "palette": Param("Flame Color", "choice", "Fire",
                         options=["Fire", "Blue Fire", "Green Fire", "Purple Fire", "Custom Palette"]),
        "custom": Param("Flame Palette", "palette", ["#3082dd", "#9eaaeb", "#da5daa", "#ffffff"],
                    show_if={"palette": "Custom Palette"}, hint="From the coolest color to the hottest."),
        "reverse": Param("Flip Direction", "bool", False),
    }

    PALETTES = {"Fire": 0, "Blue Fire": 200, "Green Fire": 100, "Purple Fire": 275, "Custom Palette": None}

    def _heat_color(self, h):
        shift = self.PALETTES[self.v("palette")]
        if shift is None:
            return gradient([(0, 0, 0)] + self.colors("custom"), h)
        if shift == 0:
            # black -> red -> orange -> yellow -> white
            if h < 0.33:
                return (int(h / 0.33 * 255), 0, 0)
            if h < 0.66:
                return (255, int((h - 0.33) / 0.33 * 200), 0)
            return (255, 200 + int((h - 0.66) / 0.34 * 55), int((h - 0.66) / 0.34 * 200))
        return hsv(shift + h * 40, 1 - max(0, h - 0.75) * 3, min(1, h * 1.4))

    def render(self, t, dt, n, zone, state):
        if n == 1:
            # single-LED zones just flicker
            return [self._heat_color(0.45 + 0.4 * random.random())]
        heat = state.get("heat")
        if heat is None or len(heat) != n:
            heat = state["heat"] = [0.0] * n
        state["acc"] = state.get("acc", 0) + dt * self.v("speed")
        while state["acc"] >= 1.5:
            state["acc"] -= 1.5
            cool = self.v("cooling") / 100 * 10 / max(n, 1)
            for i in range(n):
                heat[i] = max(0.0, heat[i] - random.uniform(0, cool))
            for i in range(n - 1, 1, -1):
                heat[i] = (heat[i - 1] + heat[i - 2] * 2) / 3
            if n and random.random() * 255 < self.v("sparking"):
                j = random.randint(0, min(n - 1, 4))
                heat[j] = min(1.0, heat[j] + random.uniform(0.6, 1.0))
        out = [self._heat_color(h) for h in heat]
        if self.v("reverse"):
            out.reverse()
        return out
