from effect_base import *


class Aurora(Effect):
    name = "Aurora"
    description = "Soft, slowly drifting northern-lights colors."
    params = {
        "speed": Param("Speed", "number", 25, 1, 100),
        "palette": Param("Colors", "choice", "Northern Lights",
                         options=["Custom Palette", "Northern Lights", "Ocean", "Sunset", "Vaporwave"]),
        "custom": Param("Custom Palette", "palette", ["#00ff78", "#00b4ff", "#8c00ff", "#00ffc8"],
                    show_if={"palette": "Custom Palette"}),
        "scale": Param("Wave Size", "number", 40, 5, 100),
        "brightness": Param("Brightness", "number", 90, 10, 100),
    }

    PALETTES = {
        "Northern Lights": [(0, 255, 120), (0, 180, 255), (140, 0, 255), (0, 255, 200)],
        "Ocean": [(0, 40, 255), (0, 200, 255), (0, 255, 180), (0, 90, 200)],
        "Sunset": [(255, 60, 0), (255, 0, 90), (255, 160, 0), (160, 0, 200)],
        "Vaporwave": [(255, 0, 200), (0, 230, 255), (140, 0, 255), (255, 80, 160)],
    }

    def _sample(self, x):
        choice = self.v("palette")
        pal = self.colors("custom") if choice == "Custom Palette" else self.PALETTES[choice]
        x = x % len(pal)
        i = int(x)
        return mix(pal[i], pal[(i + 1) % len(pal)], x - i)

    def render(self, t, dt, n, zone, state):
        sp = t * self.v("speed") / 60
        sc = 100 / self.v("scale")
        b = self.v("brightness") / 100
        out = []
        for i in range(n):
            x = i / max(n, 1) * sc + zone.index * 0.7
            w = (math.sin(x * 2.1 + sp * 1.3) + math.sin(x * 3.7 - sp * 0.9) + math.sin(x * 1.3 + sp * 0.5)) / 3
            level = 0.25 + 0.75 * (w + 1) / 2
            out.append(scale(self._sample(x * 0.6 + sp * 0.4 + w), level * b))
        return out
