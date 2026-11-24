from effect_base import *

C = NIGHT_CITY_LED   # LED-tuned: vivid hues, no white

PALETTES = {
    "Rain Window": [C["deep"], C["blue"], C["cyan"], C["violet"], C["blue"]],
    "Neon Glow": [C["deep"], C["blue"], C["violet"], C["pink"], C["purple"], C["cyan"]],
    "Deep Night": [C["navy"], C["deep"], C["blue"], C["deep"], (30, 0, 120)],
    "Custom Palette": None,
}


class NightCityAurora(Effect):
    name = "Night City Aurora"
    description = ("Slow aurora waves in vivid Night City colors: electric blue, cyan and violet, "
                   "with hot-pink neon reflections and quick cyan glints like rain on glass. "
                   "Dark gaps between the waves keep the contrast high on real LEDs.")
    params = {
        "speed": Param("Speed", "number", 25, 1, 100),
        "palette": Param("Colors", "choice", "Rain Window", options=list(PALETTES)),
        "custom": Param("Custom Palette", "palette", ["#001282", "#003cff", "#00b4ff", "#5a00ff"],
                    show_if={"palette": "Custom Palette"}),
        "accent": Param("Reflection Color", "color", "#ff008c"),
        "scale": Param("Wave Size", "number", 45, 5, 100),
        "brightness": Param("Brightness", "number", 100, 10, 100),
        "intensity": Param("Color Intensity", "number", 85, 0, 100),
        "contrast": Param("Contrast", "number", 35, 0, 100),
        "pink": Param("Neon Reflections", "number", 45, 0, 100),
        "shimmer": Param("Rain Shimmer", "number", 25, 0, 100),
        "depth": Param("Dark Gaps Between Waves", "number", 65, 0, 100),
    }

    def render(self, t, dt, n, zone, state):
        sp = t * self.v("speed") / 60
        sc = 100 / self.v("scale")
        b = self.v("brightness") / 100
        depth = self.v("depth") / 100
        pal = PALETTES[self.v("palette")] or self.colors("custom")
        accent = hex_to_rgb(self.v("accent"))
        pink_amt = self.v("pink") / 100
        shimmer = self.v("shimmer") / 100
        sat, con = self.v("intensity") / 100, self.v("contrast") / 100
        off = zone.index * 0.9 + zone_random(zone, "aurora") * 3

        # a neon "reflection" drifts slowly along the strip
        pink_center = (math.sin(sp * 0.37 + off) * 0.5 + 0.5) * n
        pink_width = max(2.0, n * 0.18)

        out = []
        for i in range(n):
            x = i / max(n, 1) * sc + off
            w = (math.sin(x * 2.1 + sp * 1.3) + math.sin(x * 3.7 - sp * 0.9) * 0.6 +
                 math.sin(x * 1.1 + sp * 0.4)) / 2.6
            # sharpen the wave so peaks glow and the gaps go properly dark
            crest = max(0.0, (w + 1) / 2) ** 1.3
            level = (1 - depth) + depth * crest
            col = palette(pal, x * 0.15 + sp * 0.08 + w * 0.15)
            if pink_amt:
                d = abs(i - pink_center) / pink_width
                if d < 1:
                    col = mix(col, accent, pink_amt * (1 - d) ** 2)
            if shimmer and random.random() < shimmer * 0.04:
                col = mix(col, C["ice"], random.uniform(0.4, 0.9))
                level = max(level, 0.9)
            out.append(vivid(scale(col, level * b), sat, con))
        return out
