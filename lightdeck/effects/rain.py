from effect_base import *


class Rain(Effect):
    name = "Rain Drops"
    description = "Drops with glowing tails fall along each strip, each at its own speed."
    params = {
        "speed": Param("Fall Speed", "number", 40, 1, 100),
        "density": Param("Drops per 60 LEDs", "number", 4, 1, 30),
        "tail": Param("Tail Length (LEDs)", "number", 8, 1, 40),
        "color_mode": Param("Color Mode", "choice", "Blue", options=["Blue", "Palette", "Rainbow", "Custom"]),
        "palette": Param("Drop Colors", "palette", ["#00e5ff", "#3082dd", "#9eaaeb"],
                     show_if={"color_mode": "Palette"}),
        "color": Param("Custom Color", "color", "#00ffff", show_if={"color_mode": "Custom"}),
        "white_head": Param("Bright White Head", "bool", True),
        "glow": Param("Background Glow", "number", 4, 0, 30),
        "reverse": Param("Fall the Other Way", "bool", False),
    }

    def _drop(self, n, anywhere):
        return {
            "pos": random.uniform(0, n) if anywhere else -random.uniform(0, n * 0.5),
            "v": random.uniform(0.6, 1.5),
            "hue": random.uniform(0, 360),
        }

    def _color(self, d):
        mode = self.v("color_mode")
        if mode == "Rainbow":
            return hsv(d["hue"])
        if mode == "Palette":
            pal = self.colors("palette")
            return pal[int(d["hue"]) % len(pal)]
        if mode == "Custom":
            return hex_to_rgb(self.v("color"))
        return hsv(200 + (d["hue"] % 40) - 20)

    def render(self, t, dt, n, zone, state):
        want = max(1, round(self.v("density") * max(n, 1) / 60))
        drops = state.setdefault("drops", [])
        while len(drops) < want:
            drops.append(self._drop(n, True))
        del drops[want:]

        g = self.v("glow") / 100
        out = [hsv(215, 0.8, g)] * n
        tail = self.v("tail")
        for d in drops:
            d["pos"] += dt * self.v("speed") * 0.6 * d["v"] * max(n, 10) / 30
            if d["pos"] - tail > n:
                d.update(self._drop(n, False))
                continue
            col = self._color(d)
            head = int(d["pos"])
            for k in range(int(tail) + 1):
                i = head - k
                if 0 <= i < n:
                    fade = (1 - k / (tail + 1)) ** 2
                    out[i] = add(out[i], scale(col, fade))
            if self.v("white_head") and 0 <= head < n:
                out[head] = (255, 255, 255)
        if self.v("reverse"):
            out.reverse()
        return out
