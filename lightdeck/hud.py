"""Animated HUD pieces for LightDeck: title, neon stripe, telemetry panel.

Everything here only draws on tkinter Canvases and reads numbers from the engine,
so it never slows down the lights themselves.
"""
import colorsys
import math
import random
import time
from collections import deque

MA_PER_CHANNEL = 20.0   # a typical ARGB LED draws ~20 mA per color channel at full brightness


def hex_rgb(h):
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def rgb_hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def blend(a, b, f):
    a, b = hex_rgb(a), hex_rgb(b)
    return rgb_hex([a[i] + (b[i] - a[i]) * f for i in range(3)])


def stripe_color(cols, x):
    """Color at position x (0..1, wraps) along a looping gradient of hex colors."""
    n = len(cols)
    x = (x % 1.0) * n
    i = int(x) % n
    return blend(cols[i], cols[(i + 1) % n], x - int(x))


class AnimatedTitle:
    """Title with chromatic glitch copies that jitter now and then, and a blinking cursor."""

    def __init__(self, canvas, T):
        self.c, self.T = canvas, T
        self.font = (T["font_head"], 24)
        self.next_glitch = time.time() + 2
        self.glitch_until = 0
        x, y = 2, 4
        self.x, self.y = x, y
        self.g = []
        if T["glitch"]:
            self.g.append(canvas.create_text(x - 2, y + 1, text=T["title"], anchor="nw", font=self.font, fill=T["glitch"][0]))
            self.g.append(canvas.create_text(x + 2, y - 1, text=T["title"], anchor="nw", font=self.font, fill=T["glitch"][1]))
        self.main = canvas.create_text(x, y, text=T["title"], anchor="nw", font=self.font, fill=T["head"])
        self.tag = None
        if T["tag"]:
            self.tag = canvas.create_text(x + 1, y + 38, text=T["tag"] + " ▌", anchor="nw",
                                          font=(T["font_mono"], 8), fill=T["muted"])
        # "LIVE" indicator
        bx = 250
        self.dot = canvas.create_oval(bx, y + 12, bx + 9, y + 21, fill=T["btn_press"], outline="")
        self.live = canvas.create_text(bx + 14, y + 16, text="LIVE", anchor="w", font=(T["font_head"], 10),
                                       fill=T["btn_press"])

    def animate(self, t):
        T, c = self.T, self.c
        now = time.time()
        # pulsing LIVE dot
        pulse = (math.sin(t * 4) + 1) / 2
        c.itemconfig(self.dot, fill=blend(T["panel"], T["btn_press"], 0.35 + 0.65 * pulse))
        # blinking cursor after the tag line
        if self.tag:
            c.itemconfig(self.tag, text=T["tag"] + (" ▌" if int(t * 2) % 2 else "  "))
        if not self.g:
            return
        if now > self.next_glitch:
            self.glitch_until = now + random.uniform(0.08, 0.25)
            self.next_glitch = now + random.uniform(2.5, 6)
        if now < self.glitch_until:
            dx = random.choice([-5, -4, 4, 5])
            c.coords(self.g[0], self.x - dx, self.y + random.randint(-2, 2))
            c.coords(self.g[1], self.x + dx, self.y + random.randint(-2, 2))
            c.coords(self.main, self.x + random.randint(-1, 1), self.y)
        else:
            c.coords(self.g[0], self.x - 2, self.y + 1)
            c.coords(self.g[1], self.x + 2, self.y - 1)
            c.coords(self.main, self.x, self.y)


class NeonStripe:
    """Thin gradient line whose colors slowly flow sideways."""

    STEPS = 90

    def __init__(self, canvas, T):
        self.c, self.T = canvas, T
        self.items = []
        canvas.bind("<Configure>", lambda e: self.layout())

    def layout(self):
        self.c.delete("all")
        w = max(self.c.winfo_width(), 10)
        self.items = [self.c.create_rectangle(i * w / self.STEPS, 0, (i + 1) * w / self.STEPS + 1, 3,
                                              outline="", fill=self.T["accent"]) for i in range(self.STEPS)]

    def animate(self, t):
        cols = self.T["stripe"]
        if len(cols) == 1:
            pulse = (math.sin(t * 2) + 1) / 2
            col = blend(self.T["panel"], cols[0], 0.5 + 0.5 * pulse)
            for it in self.items:
                self.c.itemconfig(it, fill=col)
            return
        shift = t * 0.06
        for i, it in enumerate(self.items):
            self.c.itemconfig(it, fill=stripe_color(cols, i / self.STEPS * 0.8 - shift))


class Telemetry:
    """Scientific readouts and live graphs about what the engine is doing."""

    W, H = 430, 316
    HISTORY = 150

    def __init__(self, canvas, engine, T):
        self.c, self.eng, self.T = canvas, engine, T
        self.fps_hist = deque(maxlen=self.HISTORY)
        self.amp_hist = deque(maxlen=self.HISTORY)
        canvas.config(width=self.W, height=self.H)

    # -- helpers --
    def _txt(self, x, y, text, size=8, color=None, anchor="nw", mono=True, bold=False):
        T = self.T
        font = (T["font_mono"] if mono else T["font_head"], size)
        return self.c.create_text(x, y, text=text, anchor=anchor, font=font, fill=color or T["muted"], tags="dyn")

    def _frame(self, x0, y0, x1, y1, title):
        T, c = self.T, self.c
        c.create_rectangle(x0, y0, x1, y1, outline=T["border"], tags="dyn")
        # corner brackets
        for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            c.create_line(x, y, x + 7 * dx, y, fill=T["sub"], tags="dyn")
            c.create_line(x, y, x, y + 7 * dy, fill=T["sub"], tags="dyn")
        self._txt(x0 + 5, y0 + 3, title, 7, T["sub"])

    def _graph(self, x0, y0, x1, y1, data, vmax, color, title, unit, target=None):
        T, c = self.T, self.c
        self._frame(x0, y0, x1, y1, title)
        gx0, gy0, gx1, gy1 = x0 + 4, y0 + 16, x1 - 4, y1 - 4
        for k in range(1, 4):   # grid
            gy = gy0 + (gy1 - gy0) * k / 4
            c.create_line(gx0, gy, gx1, gy, fill=T["field"], tags="dyn")
        for k in range(1, 6):
            gx = gx0 + (gx1 - gx0) * k / 6
            c.create_line(gx, gy0, gx, gy1, fill=T["field"], tags="dyn")
        vmax = max(vmax, 1e-6)
        if target:
            ty = gy1 - (gy1 - gy0) * min(target / vmax, 1)
            c.create_line(gx0, ty, gx1, ty, fill=T["muted"], dash=(3, 3), tags="dyn")
        if len(data) > 1:
            pts = []
            for i, v in enumerate(data):
                px = gx0 + (gx1 - gx0) * i / (self.HISTORY - 1)
                py = gy1 - (gy1 - gy0) * min(v / vmax, 1)
                pts += [px, py]
            c.create_line(*pts, fill=blend(T["panel"], color, 0.35), width=4, tags="dyn")   # glow
            c.create_line(*pts, fill=color, width=1.5, tags="dyn")
            c.create_oval(pts[-2] - 2.5, pts[-1] - 2.5, pts[-2] + 2.5, pts[-1] + 2.5, fill=color, outline="", tags="dyn")
            self._txt(x1 - 5, y0 + 3, f"{data[-1]:.2f} {unit}" if vmax < 10 else f"{data[-1]:.0f} {unit}",
                      7, color, anchor="ne")

    def update(self, t):
        T, c, eng = self.T, self.c, self.eng
        c.delete("dyn")
        cols = [col for colors in eng.preview.values() for col in colors]
        n = len(cols)
        amps = sum(r + g + b for r, g, b in cols) / 255 * MA_PER_CHANNEL / 1000
        luma = (sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in cols) / (255 * n) * 100) if n else 0
        self.fps_hist.append(eng.inst_fps)
        self.amp_hist.append(amps)
        pkts = sum(eng.packets_per_sec.values())
        up = int(time.time() - eng.started_at)

        # --- readouts ---
        stats = [
            ("FPS", f"{eng.inst_fps:5.1f}", f"/ {eng.cfg['fps']}"),
            ("FRAME", f"{eng.frame_ms:5.2f}", "ms"),
            ("PACKETS", f"{pkts:5.0f}", "/s"),
            ("LEDS", f"{n:5d}", f"{len(eng.dev_info)} dev"),
            ("EST. CURRENT", f"{amps:5.2f}", "A"),
            ("AVG LUMA", f"{luma:5.1f}", "%"),
            ("TOTAL PKTS", f"{eng.total_packets:,}", ""),
            ("UPTIME", f"{up // 3600:02d}:{up // 60 % 60:02d}:{up % 60:02d}", ""),
        ]
        cw = self.W / 4
        for i, (label, value, unit) in enumerate(stats):
            x = 4 + (i % 4) * cw
            y = 2 + (i // 4) * 32
            self._txt(x, y, label, 7, T["muted"])
            vid = self._txt(x, y + 11, value, 11, T["head"] if i % 2 == 0 else T["accent_hover"])
            bx = c.bbox(vid)
            if unit and bx:
                self._txt(bx[2] + 3, y + 15, unit, 7, T["muted"])

        # --- graphs ---
        target = eng.cfg["fps"]
        self._graph(2, 68, self.W / 2 - 3, 150, self.fps_hist, max(target * 1.25, max(self.fps_hist or [1])),
                    T["accent_hover"], "LOOP RATE", "fps", target=target)
        self._graph(self.W / 2 + 3, 68, self.W - 2, 150, self.amp_hist, max(0.5, max(self.amp_hist or [0]) * 1.2),
                    T["btn_press"], "LED POWER (EST.)", "A")

        # --- color spectrum of everything the LEDs show right now ---
        y0, y1 = 158, 214
        self._frame(2, y0, self.W - 2, y1, "OUTPUT SPECTRUM  ·  HUE 0-360°")
        bins = [0.0] * 36
        for r, g, b in cols:
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if v > 0.03:
                bins[int(h * 36) % 36] += s * v
        top = max(bins) or 1
        bx0, bw = 8, (self.W - 16) / 36
        for i, val in enumerate(bins):
            hgt = (y1 - y0 - 20) * (val / top)
            r, g, b = colorsys.hsv_to_rgb((i + 0.5) / 36, 1, 1)
            col = rgb_hex((r * 255, g * 255, b * 255))
            c.create_rectangle(bx0 + i * bw + 1, y1 - 4 - max(1, hgt), bx0 + (i + 1) * bw - 1, y1 - 4,
                               fill=col if val else T["field"], outline="", tags="dyn")

        # --- data links per device ---
        y = 222
        self._frame(2, y, self.W - 2, self.H - 2, "DATA LINKS  ·  UPDATES SENT PER SECOND")
        rows = eng.dev_info[:5]
        maxrate = max([eng.cfg["fps"]] + list(eng.packets_per_sec.values()))
        for i, d in enumerate(rows):
            ry = y + 16 + i * 14
            rate = eng.packets_per_sec.get(d["name"], 0.0)
            bus = d.get("bus") or ("I2C" if d["slow"] else "USB")
            name = eng.display_name(d["name"], d["name"])
            name = name if len(name) <= 22 else name[:21] + "…"
            self._txt(8, ry, f"{bus:3s} {name}", 7, T["fg"])
            bar0, bar1 = 200, self.W - 60
            c.create_rectangle(bar0, ry + 2, bar1, ry + 9, fill=T["field"], outline="", tags="dyn")
            fill = bar0 + (bar1 - bar0) * min(rate / maxrate, 1)
            # little moving "packets" inside the bar
            col = T["accent_hover"] if not d["slow"] else T["sub"]
            c.create_rectangle(bar0, ry + 2, fill, ry + 9, fill=blend(T["panel"], col, 0.6), outline="", tags="dyn")
            if fill > bar0 + 6:
                px = bar0 + ((t * 80 + i * 37) % max(1, fill - bar0))
                c.create_rectangle(px, ry + 2, px + 4, ry + 9, fill=col, outline="", tags="dyn")
            self._txt(self.W - 8, ry, f"{rate:5.1f}", 7, T["head"], anchor="ne")
