"""Building blocks for LightDeck effects.

Every effect is a class that subclasses `Effect`, declares its settings in
`params`, and implements `render()`. Drop a new .py file in the `effects`
folder and LightDeck picks it up automatically (no restart needed).

render() is called once per frame for every zone (a strip of LEDs) that uses
the effect, and must return a list of (r, g, b) tuples, one per LED.
"""
import colorsys
import math
import random
import zlib


class Param:
    """One setting shown in the app.

    kind: "number" -> slider (min/max/step)
          "color"  -> color picker, value is "#rrggbb"
          "choice" -> dropdown, value is one of `options`
          "bool"   -> checkbox
          "palette"-> list of colors you can add, remove and change,
                      value is ["#rrggbb", ...]; read it with self.colors(key)

    Optional:
      show_if  only show this setting when other settings have certain values, e.g.
               show_if={"color_mode": "Palette"} or {"color_mode": ["Palette", "Shifting"]}
               or {"use_palette": True}. Hidden settings keep their value.
      hint     one short line shown under the setting to explain it.
    """

    def __init__(self, label, kind="number", default=50, min=0, max=100, step=1, options=None,
                 show_if=None, hint=None):
        self.label = label
        self.kind = kind
        self.default = default
        self.min = min
        self.max = max
        self.step = step
        self.options = options or []
        self.show_if = show_if or {}
        self.hint = hint

    def visible(self, values):
        """Should this setting be shown, given the effect's current values?"""
        for key, allowed in self.show_if.items():
            if not isinstance(allowed, (list, tuple, set)):
                allowed = [allowed]
            if values.get(key) not in allowed:
                return False
        return True


class Effect:
    name = "Unnamed effect"
    description = ""
    params = {}

    def __init__(self, values=None):
        self.values = {k: (list(p.default) if p.kind == "palette" else p.default)
                       for k, p in self.params.items()}
        if values:
            for k, v in values.items():
                if k in self.params:
                    p = self.params[k]
                    if p.kind == "palette":
                        v = [c for c in (v or []) if isinstance(c, str) and len(c) == 7] or list(p.default)
                    elif p.kind == "choice" and v not in p.options:
                        v = p.default      # option was renamed or removed in a newer version
                    self.values[k] = v

    def v(self, key):
        """Current value of a setting."""
        return self.values[key]

    def colors(self, key):
        """A palette setting as a list of (r, g, b) colors (never empty)."""
        cols = [hex_to_rgb(c) for c in self.values.get(key) or []]
        return cols or [(255, 255, 255)]

    def render(self, t, dt, n, zone, state):
        """Return n colors.

        t      seconds since the effect started
        dt     seconds since the last frame
        n      number of LEDs in this zone
        zone   ZoneInfo: .index, .count (zones using this effect), .key, .name
        state  dict that persists between frames for this zone only
        """
        return [(0, 0, 0)] * n


# ---------- helpers effects can use ----------

def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def hsv(h, s=1.0, v=1.0):
    """h in degrees (any value, wraps), s and v from 0 to 1 -> (r, g, b) 0-255."""
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, clamp(s), clamp(v))
    return (int(r * 255), int(g * 255), int(b * 255))


def hex_to_rgb(value):
    value = value.lstrip("#")
    if len(value) != 6:
        return (255, 255, 255)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def scale(color, amount):
    amount = clamp(amount)
    return (int(color[0] * amount), int(color[1] * amount), int(color[2] * amount))


def mix(a, b, f):
    f = clamp(f)
    return (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f), int(a[2] + (b[2] - a[2]) * f))


def add(a, b):
    return (min(255, a[0] + b[0]), min(255, a[1] + b[1]), min(255, a[2] + b[2]))


def gradient(colors, f):
    """Blend through a list of colors: f=0 gives the first, f=1 the last."""
    if len(colors) == 1:
        return colors[0]
    f = clamp(f) * (len(colors) - 1)
    i = min(int(f), len(colors) - 2)
    return mix(colors[i], colors[i + 1], f - i)


def palette(colors, x):
    """Like gradient(), but wraps around: x=0..1 goes through all colors and back to the first."""
    n = len(colors)
    x = (x % 1.0) * n
    i = int(x) % n
    return mix(colors[i], colors[(i + 1) % n], x - int(x))


# Ready-made palettes, in groups. Colors are saturated on purpose: pastels look white on real LEDs.
PALETTE_GROUPS = {
    "Classic": {
        "Night City": ["#00b4ff", "#003cff", "#5a00ff", "#ff008c"],
        "Rain Window": ["#001282", "#003cff", "#00b4ff", "#5a00ff"],
        "Neon Pink": ["#ff008c", "#ff0028", "#9600ff", "#003cff"],
        "Rainbow": ["#ff0000", "#ff8800", "#ffee00", "#00ff44", "#00ccff", "#3355ff", "#aa00ff"],
        "Fire": ["#ff2000", "#ff6a00", "#ffb300", "#ffee88"],
        "Ocean": ["#002a8f", "#0077ff", "#00d5ff", "#00ffcc"],
        "Vaporwave": ["#ff00c8", "#00e6ff", "#8c00ff", "#ff5ca0"],
        "Toxic": ["#39ff14", "#00ff9c", "#d4ff00", "#00b36b"],
        "Arasaka Red": ["#ff003c", "#b2314b", "#ff5a5a", "#5a0010"],
        "Ice": ["#ffffff", "#bdeaff", "#65bef7", "#3082dd"],
    },
    # one for each part of the city
    "City districts": {
        "Watson Market": ["#ff0066", "#ff7a00", "#00d5ff", "#7a00ff"],
        "Japantown Lanterns": ["#ff0030", "#ff006a", "#ffae00", "#ff3d00"],
        "Kabuki Alleys": ["#ff00b4", "#b400ff", "#00ffd5", "#ff0050"],
        "Corpo Plaza": ["#001a8c", "#003cff", "#0096ff", "#00e1ff"],
        "Heywood Murals": ["#ffd000", "#ff00a0", "#00b4ff", "#00ff6a"],
        "Pacifica Sunset": ["#6a00ff", "#ff0080", "#ff2a00", "#ff6a00"],
        "Afterlife Bar": ["#ff0028", "#8c00ff", "#ff0064", "#3c00b4"],
        "Badlands Dust": ["#ff2800", "#ff5a00", "#ffa000", "#c83c00"],
    },
    # moods from around the city
    "Night City moods": {
        "Netrunner": ["#00ff3c", "#00ff9c", "#00ffd0", "#0078ff"],
        "Chrome Clinic": ["#00f0ff", "#0050ff", "#a000ff", "#00ffa0"],
        "Glitch Yellow": ["#ffe600", "#00e5ff", "#ff003c", "#ff9d00"],
        "Police Lights": ["#ff0014", "#0028ff", "#ff0050", "#0078ff"],
        "Acid Rain": ["#b4ff00", "#00ff78", "#00b4ff", "#5a00ff"],
        "Blackwall": ["#ff0014", "#5a0000", "#ff3c00", "#8c0028"],
    },
}

# every ready-made palette by name (the palette editor's "Presets")
PALETTE_PRESETS = {name: cols for group in PALETTE_GROUPS.values() for name, cols in group.items()}

PALETTE_SLOTS = 8          # how many of your own palettes LightDeck keeps ("My palettes")
SHARE_PREFIX = "LightDeck palette:"


def palette_param(effect):
    """The key of the effect's palette setting, or None if it has no palette."""
    for key, p in getattr(effect, "params", {}).items():
        if p.kind == "palette":
            return key
    return None


def apply_palette(effect, colors):
    """Put `colors` into the effect's palette setting and switch the effect over to using it (e.g. color mode
    "Palette", "Custom Palette", "Use My Palette"). Returns the key that was set, or None."""
    key = palette_param(effect)
    if key is None:
        return None
    effect.values[key] = list(colors)
    for ctl, want in (effect.params[key].show_if or {}).items():
        if ctl in effect.values:
            effect.values[ctl] = want[0] if isinstance(want, (list, tuple)) else want
    return key


def share_code(name, colors):
    """A line of text a friend can paste into their own LightDeck."""
    return f"{SHARE_PREFIX} {name.replace('|', ' ')} | {' '.join(colors)}"


def parse_share_code(text):
    """(name, colors) from a share_code() line, or None if it isn't one."""
    text = (text or "").strip()
    if not text.startswith(SHARE_PREFIX) or "|" not in text:
        return None
    name, _, cols = text[len(SHARE_PREFIX):].rpartition("|")
    out = []
    for c in cols.split():
        c = c.strip().lower()
        if len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdef" for ch in c[1:]):
            out.append(c)
    name = " ".join(name.split())[:28] or "Shared palette"
    return (name, out[:16]) if out else None

# Colors from a rainy Night City scene (matches the Cyberpunk theme)
NIGHT_CITY = {
    "navy": (3, 6, 25),
    "deep": (13, 62, 149),
    "blue": (48, 130, 221),
    "cyan": (101, 190, 247),
    "ice": (214, 246, 255),
    "lavender": (158, 170, 235),
    "pink": (218, 93, 170),
    "red": (178, 49, 75),
}


# The same Night City colors, tuned for real LEDs. Screens show pastels nicely, but an LED makes
# light colors by mixing red+green+blue, which looks white. These keep the hues but push the
# saturation up and leave out the white, so they stay vivid on the hardware.
NIGHT_CITY_LED = {
    "navy": (0, 2, 16),
    "deep": (0, 18, 130),
    "blue": (0, 60, 255),
    "cyan": (0, 180, 255),
    "ice": (30, 215, 255),      # brightest comet heads: bright cyan, not white
    "violet": (90, 0, 255),     # the lavender, made vivid
    "purple": (150, 0, 255),
    "pink": (255, 0, 140),
    "red": (255, 0, 40),
}


def vivid(col, saturation=0.8, contrast=0.6):
    """Make a color punchier on LEDs.

    saturation 0..1: how much to pull washed-out colors toward their pure hue
    contrast   0..1: how much darker the dim parts get (gamma 1.0 -> 2.5), so bright parts stand out
    """
    r, g, b = col
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v <= 0:
        return (0, 0, 0)
    s = s + (1 - s) * saturation * s ** 0.35   # boosts colors, leaves true greys mostly alone
    v = v ** (1 + contrast * 1.5)
    return hsv(h * 360, s, v)


def zone_random(zone, salt=0):
    """A stable pseudo-random number 0..1 for a zone, so each strip gets its own personality."""
    return random.Random(zlib.crc32(f"{zone.key}|{salt}".encode())).random()


__all__ = ["Param", "Effect", "clamp", "hsv", "hex_to_rgb", "scale", "mix", "add",
           "gradient", "palette", "NIGHT_CITY", "NIGHT_CITY_LED", "vivid", "PALETTE_PRESETS",
           "PALETTE_GROUPS",
           "zone_random", "math", "random"]
