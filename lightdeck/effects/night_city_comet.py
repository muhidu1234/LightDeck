from effect_base import *

C = NIGHT_CITY_LED   # LED-tuned: vivid hues, no white

# tail colors for each kind of comet: head -> end of tail
TAILS = {
    "blue": [C["ice"], C["cyan"], C["blue"], C["deep"], C["navy"]],
    "violet": [(150, 80, 255), C["violet"], (40, 0, 200), C["deep"], C["navy"]],
    "pink": [(255, 40, 170), C["pink"], C["red"], (70, 0, 25), C["navy"]],
}
MIXES = {
    "Blue only": ["blue"],
    "Blue + Violet": ["blue", "violet", "blue"],
    "Full Night City": ["blue", "violet", "pink", "blue"],
    "Custom Palette": [],
}


def tail_for(col):
    """Head -> tail colors for a comet of any color: brighter head, the color, darker, navy."""
    return [mix(col, (255, 255, 255), 0.2), col, scale(col, 0.4), C["navy"]]


class NightCityComet(Effect):
    name = "Night City Comet"
    description = ("Comet chase in vivid Night City colors: bright cyan heads with electric-blue tails, "
                   "some violet or hot pink, over deep darkness. Pink sparks fly off the heads. "
                   "Raise Color Intensity / Contrast if it looks washed out on your LEDs.")
    params = {
        "speed": Param("Speed", "number", 45, 1, 100),
        "count": Param("Number of Comets", "number", 3, 1, 10),
        "tail": Param("Tail Length (% of strip)", "number", 35, 5, 100),
        "colors": Param("Comet Colors", "choice", "Full Night City", options=list(MIXES)),
        "palette": Param("Custom Palette", "palette", ["#00b4ff", "#5a00ff", "#ff008c"],
                     show_if={"colors": "Custom Palette"}),
        "intensity": Param("Color Intensity", "number", 85, 0, 100),
        "contrast": Param("Contrast", "number", 60, 0, 100),
        "sparks": Param("Pink Sparks", "number", 25, 0, 100),
        "glow": Param("Background Glow", "number", 3, 0, 40),
        "bounce": Param("Bounce Back and Forth", "bool", False),
        "reverse": Param("Reverse Direction", "bool", False),
    }

    def render(self, t, dt, n, zone, state):
        if n == 0:
            return []
        # faint deep-blue glow that slowly breathes, like city light through rain
        g = self.v("glow") / 100 * (0.75 + 0.25 * math.sin(t * 0.8 + zone.index))
        out = [scale(C["deep"], g)] * n

        count = int(self.v("count"))
        tail = max(2.0, self.v("tail") / 100 * n)
        kinds = MIXES[self.v("colors")]
        travel = t * self.v("speed") / 100 * max(n, 10) * 0.8
        speed_var = 0.85 + 0.3 * zone_random(zone, "comet")   # each strip slightly different
        heads = []
        for c in range(count):
            p = travel * speed_var + c * n / count + zone.index * n / 5
            if self.v("bounce"):
                p %= 2 * n
                head, d = (p, 1) if p < n else (2 * n - p, -1)
            else:
                head, d = p % n, 1
            heads.append(head)
            if kinds:
                colors = TAILS[kinds[c % len(kinds)]]
            else:
                pal = self.colors("palette")
                colors = tail_for(pal[c % len(pal)])
            for k in range(int(tail) + 1):
                i = int(head - k * d)
                if not self.v("bounce"):
                    i %= n
                if 0 <= i < n:
                    f = k / tail
                    out[i] = add(out[i], scale(gradient(colors, f), (1 - f) ** 1.6))

        # pink sparks that pop off near the comet heads and fade
        sparks = state.setdefault("sparks", [])
        if heads and random.random() < self.v("sparks") / 100 * dt * 12:
            h = random.choice(heads)
            sparks.append([int(h + random.uniform(-3, 3)) % n, 1.0, random.choice([C["pink"], C["red"], C["purple"]])])
        for s in sparks:
            out[s[0]] = add(out[s[0]], scale(s[2], s[1]))
            s[1] -= dt * 2.5
        state["sparks"] = [s for s in sparks if s[1] > 0]

        sat, con = self.v("intensity") / 100, self.v("contrast") / 100
        out = [vivid(col, sat, con) for col in out]
        if self.v("reverse"):
            out.reverse()
        return out
