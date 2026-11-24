from effect_base import *


class Sparkle(Effect):
    name = "Starfield Sparkle"
    description = "Random LEDs twinkle like stars over a dim background."
    params = {
        "rate": Param("Sparkles per Second (per 60 LEDs)", "number", 15, 1, 100),
        "fade": Param("Fade Speed", "number", 40, 5, 100),
        "color_mode": Param("Color Mode", "choice", "White", options=["White", "Palette", "Rainbow", "Custom"]),
        "palette": Param("Star Colors", "palette", ["#ffffff", "#bdeaff", "#ffd080"],
                     show_if={"color_mode": "Palette"}),
        "color": Param("Custom Color", "color", "#ffd080", show_if={"color_mode": "Custom"}),
        "background": Param("Background Color", "color", "#000814"),
    }

    def render(self, t, dt, n, zone, state):
        lv = state.get("lv")
        if lv is None or len(lv) != n:
            lv = state["lv"] = [0.0] * n
            state["col"] = [(255, 255, 255)] * n
        cols = state["col"]
        expected = self.v("rate") * dt * max(n, 1) / 60
        while expected > 0:
            if n and random.random() < expected:
                i = random.randrange(n)
                lv[i] = 1.0
                mode = self.v("color_mode")
                if mode == "Rainbow":
                    cols[i] = hsv(random.uniform(0, 360))
                elif mode == "Palette":
                    cols[i] = random.choice(self.colors("palette"))
                elif mode == "Custom":
                    cols[i] = hex_to_rgb(self.v("color"))
                else:
                    cols[i] = (255, 255, 255)
            expected -= 1
        bg = hex_to_rgb(self.v("background"))
        decay = self.v("fade") / 100 * 3 * dt
        out = []
        for i in range(n):
            lv[i] = max(0.0, lv[i] - decay)
            out.append(mix(bg, cols[i], lv[i]))
        return out
