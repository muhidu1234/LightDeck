"""LightDeck's Night City window: a side bar with pages, drawn on tkinter canvases (+ Pillow for glow).

Pages: Lights (every light, on/off, live colors) · Light settings (effect, colors, speed... for one light or
all) · Preview (every LED, live) · Effects (gallery with live samples) · Settings (app options).
Everything is drawn on canvases so it can animate: rain and a skyline behind the pages, a glitching title,
sliding menu, pages that glitch in. The classic window is still there (Settings > Classic window);
it is also where splitting cables, LED counts, Wi-Fi lights and device recording live for now.
"""
import colorsys
import math
import os
import random
import subprocess
import sys
import time
import types
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, simpledialog

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

import apps
import report
import startup
from effect_base import PALETTE_PRESETS
from engine import APP_DIR, DRIVERS_DIR, EFFECTS_DIR, FPS_MAX, FPS_MIN, GLOBAL, VERSION

NAVY, PANEL, CARD, CARD_HI, EDGE = "#060a1c", "#0b1230", "#0e1640", "#15205a", "#1f3a7a"
CYAN, BLUE, LAV, PINK, RED, WHITE, DIM = "#3ee0ff", "#2f6bff", "#a78bff", "#ff4f9a", "#ff3355", "#f2f6ff", "#8fa6e6"
OFF = "#3a4677"
SIDE, TICK = 210, 26
SLIDE_DIST, SLIDE_TIME = 48.0, 0.34        # page change: how far the new page glides in (px) and for how long (s)
PAGES = [("lights", "Lights"), ("settings", "Light settings"), ("preview", "Preview"), ("effects", "Effects"),
         ("app", "Settings")]


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def hexc(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def chamfer(x, y, w, h, c=12):
    return [x, y, x + w - c, y, x + w, y + c, x + w, y + h, x + c, y + h, x, y + h - c]


NAVY_RGB, CARD_RGB = rgb(NAVY), rgb(CARD)


class NightCity:
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine
        engine.start()
        fams = set(tkfont.families(root))
        self.font = "Bahnschrift" if "Bahnschrift" in fams else "Segoe UI"
        self.mono = "Consolas" if "Consolas" in fams else "Courier New"
        self.cache = {}
        self.page = "lights"
        self.target = GLOBAL
        self.n = 0
        self.leds = []            # live LEDs on the page: (core items, halo items, light key, last colors)
        self.gallery = []         # effect samples on the Effects page
        self.toggles = []
        self.slide = 0.0
        self.bars = []
        self.trans = None
        self._job = None
        self.hover_items = {}
        self.lights_sig = None
        self.save_timer = 0
        self.message = ""
        self.start = time.perf_counter()
        self.last_frame = self.start

        root.title(f"LightDeck {VERSION}")
        try:
            icon = APP_DIR / "lightdeck.ico"
            if icon.exists():
                root.iconbitmap(default=str(icon))
        except Exception:
            pass
        root.configure(bg=NAVY)
        root.geometry("1280x820")
        root.minsize(1100, 700)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.side = tk.Canvas(root, width=SIDE, bg=PANEL, highlightthickness=0)
        self.side.place(x=0, y=0, width=SIDE, relheight=1, height=-TICK)
        self.tick = tk.Canvas(root, height=TICK, bg="#050916", highlightthickness=0)
        self.tick.place(x=0, rely=1, y=-TICK, relwidth=1, height=TICK)
        self.view = tk.Canvas(root, bg=NAVY, highlightthickness=0, yscrollincrement=24)
        self.view.place(x=SIDE, y=0, relwidth=1, width=-SIDE, relheight=1, height=-TICK)
        self.view.bind("<Configure>", self.on_resize)
        self.view.bind_all("<MouseWheel>", self.on_wheel)
        self.vw, self.vh = 1070, 794
        self.top = 0.0
        self.build_side()
        self.build_ticker()
        self.build_backdrop()
        self.show("lights", instant=True)
        startup.refresh()
        if startup.started_by_windows():
            root.iconify()
        self.frame()
        self.slow()

    # ================= small helpers =================
    def uid(self):
        self.n += 1
        return f"w{self.n}"

    def f(self, size, bold=False):
        return (self.font, size, "bold" if bold else "normal")

    def text(self, x, y, s, size=11, color=WHITE, anchor="w", bold=False, width=0, tags=()):
        return self.view.create_text(x, y, text=s, anchor=anchor, fill=color, font=self.f(size, bold),
                                     width=width or 0, tags=("page",) + tuple(tags))

    def bind_click(self, tag, fn, hover=None):
        v = self.view
        v.tag_bind(tag, "<Button-1>", lambda e: fn())
        v.tag_bind(tag, "<Enter>", lambda e: (v.config(cursor="hand2"), hover and hover(True)))
        v.tag_bind(tag, "<Leave>", lambda e: (v.config(cursor=""), hover and hover(False)))

    def card(self, x, y, w, h, tags=(), pulse=True, fill=CARD):
        v = self.view
        poly = v.create_polygon(chamfer(x, y, w, h, 14), fill=fill, outline=EDGE, tags=("page",) + tuple(tags))
        if pulse:
            v.create_rectangle(x, y + 3, x + 3, y + h - 14, fill=PINK, outline="", tags=("page", "pulse") + tuple(tags))
        return poly

    def button(self, x, y, label, cmd, accent=False, small=False):
        """A chamfered button; returns its width."""
        v, tag = self.view, self.uid()
        w = int(len(label) * (7 if small else 8.2)) + (22 if small else 30)
        h = 26 if small else 32
        fill, fg = (PINK, NAVY) if accent else (CARD_HI, WHITE)
        poly = v.create_polygon(chamfer(x, y, w, h, 8), fill=fill, outline=PINK if accent else EDGE,
                                tags=("page", tag))
        v.create_text(x + w / 2, y + h / 2, text=label, fill=fg, font=self.f(9 if small else 10), tags=("page", tag))

        def hover(on):
            v.itemconfig(poly, outline=CYAN if on else (PINK if accent else EDGE),
                         fill=(PINK if accent else ("#1d2c74" if on else CARD_HI)))
        self.bind_click(tag, cmd, hover)
        return w

    def chip(self, x, y, label, selected, cmd):
        v, tag = self.view, self.uid()
        w = int(len(label) * 7.6) + 24
        rect = v.create_rectangle(x, y, x + w, y + 28, fill=PINK if selected else CARD, outline=PINK if selected else EDGE,
                                  tags=("page", tag))
        v.create_text(x + w / 2, y + 14, text=label, fill=NAVY if selected else DIM, font=self.f(10), tags=("page", tag))
        if not selected:
            self.bind_click(tag, cmd, lambda on: v.itemconfig(rect, outline=CYAN if on else EDGE))
        return w

    def chips(self, x, y, labels, selected, cmd, width):
        """A wrapping row of chips. Returns the y below them."""
        cx, cy = x, y
        for lab in labels:
            w = int(len(lab) * 7.6) + 24
            if cx + w > x + width and cx > x:
                cx, cy = x, cy + 36
            self.chip(cx, cy, lab, lab == selected, lambda lab=lab: cmd(lab))
            cx += w + 8
        return cy + 36

    def slider(self, x, y, w, lo, hi, step, value, on_change, fmt=str):
        v, tag = self.view, self.uid()
        v.create_line(x, y, x + w, y, fill=EDGE, width=4, tags=("page", tag))
        fill = v.create_line(x, y, x, y, fill=PINK, width=4, tags="page")
        knob = v.create_polygon(0, 0, 0, 0, fill=WHITE, outline=PINK, width=2, tags=("page", tag))
        lbl = v.create_text(x + w + 16, y, text="", anchor="w", fill=WHITE, font=self.f(10), tags="page")
        is_int = float(step).is_integer()

        def place(val):
            f = 0 if hi == lo else (val - lo) / (hi - lo)
            kx = x + f * w + self.slide_offset()
            ox = self.slide_offset()
            v.coords(fill, x + ox, y, kx, y)
            v.coords(knob, kx, y - 10, kx + 9, y, kx, y + 10, kx - 9, y)
            v.itemconfig(lbl, text=fmt(int(val) if is_int else round(val, 3)))

        def drag(e):
            f = max(0.0, min(1.0, (v.canvasx(e.x) - x - self.slide_offset()) / w))
            val = lo + round(f * (hi - lo) / step) * step
            val = int(val) if is_int else round(val, 3)
            place(val)
            on_change(val)

        for ev in ("<Button-1>", "<B1-Motion>"):
            v.tag_bind(tag, ev, drag)
        v.tag_bind(tag, "<Enter>", lambda e: v.config(cursor="sb_h_double_arrow"))
        v.tag_bind(tag, "<Leave>", lambda e: v.config(cursor=""))
        place(value)

    def slide_offset(self):
        return self.slide

    def toggle(self, x, y, on, on_change):
        v, tag = self.view, self.uid()
        bg = v.create_rectangle(x, y, x + 46, y + 22, fill=PINK if on else EDGE, outline="", tags=("page", tag))
        knob = v.create_oval(0, 0, 0, 0, fill=WHITE, outline="", tags=("page", tag))
        t = {"bg": bg, "knob": knob, "x": x, "y": y, "pos": 1.0 if on else 0.0, "on": on}
        self.toggles.append(t)

        def click():
            t["on"] = not t["on"]
            on_change(t["on"])
        self.bind_click(tag, click)
        self.place_toggle(t)

    def place_toggle(self, t):
        ox = self.slide
        kx = t["x"] + ox + 11 + t["pos"] * 24
        self.view.coords(t["knob"], kx - 8, t["y"] + 3, kx + 8, t["y"] + 19)
        self.view.itemconfig(t["bg"], fill=hexc(mix(rgb(EDGE), rgb(PINK), t["pos"])))

    def strip(self, x, y, w, key, max_leds=None, h=14):
        """A row of live LEDs showing what light `key` shows right now (a soft halo behind each)."""
        prev = self.engine.preview.get(key) or []
        n = len(prev) or (max_leds or 30)
        if max_leds:
            n = min(n, max_leds)
        step = w / max(1, n)
        lw = max(2, min(16, step - 2))
        cores = []
        v = self.view
        for i in range(n):                         # one shape per LED: the fill is the LED, its wide border the glow
            cx = x + i * step + step / 2
            cores.append(v.create_rectangle(cx - lw / 2, y, cx + lw / 2, y + h, fill=OFF, outline=CARD, width=3,
                                            tags="page"))
        self.leds.append([cores, None, key, [None] * n])

    def glow_box(self, w, h, color):
        key = ("box", w, h, color)
        if key not in self.cache:
            pad = 18
            img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
            ImageDraw.Draw(img).polygon(chamfer(pad, pad, w, h, 10), fill=rgb(color) + (190,))
            self.cache[key] = ImageTk.PhotoImage(img.filter(ImageFilter.GaussianBlur(9)))
        return self.cache[key]

    # ================= side bar, ticker, backdrop =================
    def build_side(self):
        s = self.side
        s.create_line(SIDE - 1, 0, SIDE - 1, 3000, fill=EDGE)
        self.title = [s.create_text(24, 42, text="LIGHTDECK", anchor="w", fill=c, font=self.f(21, True))
                      for c in (PINK, LAV, CYAN)]
        s.create_text(26, 70, text=f"// NIGHT CITY RGB  ·  {VERSION}", anchor="w", fill=PINK, font=self.f(9))
        self.nav_glow = s.create_image(0, 0, image=self.glow_box(170, 40, CYAN), anchor="nw")
        self.marker = s.create_rectangle(6, 112, 10, 152, fill=PINK, outline="")
        self.nav = {}
        for i, (key, label) in enumerate(PAGES):
            y = 112 + i * 52
            tag = f"nav{i}"
            poly = s.create_polygon(chamfer(18, y, 172, 40), fill="#14204d", outline="", tags=tag)
            txt = s.create_text(36, y + 20, text="◆  " + label, anchor="w", fill=DIM, font=self.f(11), tags=tag)
            self.nav[key] = {"poly": poly, "text": txt, "y": y, "dx": 0.0, "hover": False}
            s.tag_bind(tag, "<Button-1>", lambda e, k=key: self.show(k))
            s.tag_bind(tag, "<Enter>", lambda e, k=key: (self.nav[k].update(hover=True), s.config(cursor="hand2")))
            s.tag_bind(tag, "<Leave>", lambda e, k=key: (self.nav[k].update(hover=False), s.config(cursor="")))
        self.link_dot = s.create_oval(26, 400, 34, 408, fill=CYAN, outline="")
        self.link_text = s.create_text(42, 404, text="Connecting...", anchor="w", fill=DIM, font=self.f(9))
        self.fps_text = s.create_text(26, 428, text="", anchor="w", fill=LAV, font=(self.mono, 9))

    def build_ticker(self):
        t = self.tick
        t.create_line(0, 0, 4000, 0, fill=PINK)
        self.tick_text = t.create_text(1300, TICK / 2, text=self.ticker_text(), anchor="w", fill=CYAN,
                                       font=(self.mono, 9))

    def build_backdrop(self):
        """The city behind the pages. Painted once as ONE picture (skyline, lit windows, neon haze, screen
        lines): redrawing one picture is far cheaper for Windows than hundreds of little shapes. Only the
        rain and a handful of flickering windows are separate shapes."""
        v = self.view
        v.delete("bg")
        self.windows, self.drops = [], []
        w, h = max(200, self.vw), max(200, self.vh)
        rnd = random.Random(7)
        img = Image.new("RGB", (w, h), NAVY_RGB)
        d = ImageDraw.Draw(img)
        for y in range(h):                                                    # a little lighter toward the horizon
            f = max(0.0, (y / h - .45) / .55)
            d.line([(0, y), (w, y)], fill=tuple(int(c) for c in mix(NAVY_RGB, (16, 24, 70), f * .8)))
        haze = Image.new("RGB", (w, h), (0, 0, 0))                            # neon glow behind the skyline
        hd = ImageDraw.Draw(haze)
        hd.ellipse((-w * .1, h * .62, w * .55, h * 1.15), fill=(70, 20, 60))
        hd.ellipse((w * .45, h * .58, w * 1.1, h * 1.12), fill=(10, 50, 80))
        img = ImageChops.add(img, haze.filter(ImageFilter.GaussianBlur(60)))
        d = ImageDraw.Draw(img)
        x, lit = 0, []
        while x < w:
            bw, bh = rnd.randint(30, 90), rnd.randint(70, int(h * .38))
            d.rectangle((x, h - bh, x + bw, h), fill=(10, 18, 54))
            d.line([(x, h - bh), (x + bw, h - bh)], fill=(26, 44, 110))
            for _ in range(bw * bh // 600):
                wx, wy = x + rnd.randint(4, bw - 8), h - bh + rnd.randint(6, bh - 10)
                col = rnd.choice([(28, 95, 117), (106, 37, 80), (43, 58, 138), (10, 18, 54)])
                d.rectangle((wx, wy, wx + 3, wy + 2), fill=col)
                lit.append((wx, wy, col))
            x += bw + 4
        for y in range(0, h, 4):                                              # screen lines
            d.line([(0, y), (w, y)], fill=tuple(int(c * .82) for c in img.getpixel((min(w - 1, 5), y))))
        self.backdrop = ImageTk.PhotoImage(img)
        v.create_image(0, 0, image=self.backdrop, anchor="nw", tags=("bg", "fixed"))
        for wx, wy, col in rnd.sample(lit, min(14, len(lit))):                # a few windows flicker
            c = hexc(col if col != (10, 18, 54) else (106, 37, 80))
            item = v.create_rectangle(wx, wy, wx + 3, wy + 2, outline="", fill=c, tags=("bg", "fixed"))
            self.windows.append((item, c, rnd.random() * 40))
        for _ in range(int(w * h / 18000)):
            x, y, ln = random.uniform(0, w), random.uniform(0, h), random.uniform(10, 24)
            self.drops.append([v.create_line(x, y, x - 3, y + ln, fill="#22366e", tags="bg"), x, y, ln,
                               random.uniform(7, 13)])
        self.top = 0.0
        v.tag_lower("bg")

    def on_resize(self, e):
        if abs(e.width - self.vw) < 4 and abs(e.height - self.vh) < 4:
            return
        self.vw, self.vh = e.width, e.height
        if getattr(self, "_resize_job", None):
            self.root.after_cancel(self._resize_job)

        def redo():
            self._resize_job = None
            self.build_backdrop()
            self.show(self.page, instant=True, keep_scroll=True)
        self._resize_job = self.root.after(150, redo)

    def on_wheel(self, e):
        if self.page_h > self.vh:
            self.view.yview_scroll(int(-e.delta / 120) * 2, "units")

    # ================= pages =================
    def show(self, page, instant=False, keep_scroll=False):
        v = self.view
        y_frac = v.yview()[0] if keep_scroll else 0.0
        if page != self.page and not getattr(self, "_keep_message", False):
            self.message = ""                    # a notice belongs to the page it was shown on
        self._keep_message = False
        self.page = page
        v.delete("page")
        self.leds, self.gallery, self.toggles = [], [], []
        self.slide = 0.0
        self.x0 = 34
        self.cw = min(self.vw - 68, 1000)
        y = getattr(self, "page_" + page)()
        self.page_h = max(self.vh, int(y + 40))
        v.configure(scrollregion=(0, 0, self.vw, self.page_h))
        v.yview_moveto(y_frac)
        for k, b in self.nav.items():
            on = k == page
            self.side.itemconfig(b["poly"], fill=CYAN if on else "#14204d")
            self.side.itemconfig(b["text"], fill=NAVY if on else DIM)
        for item in self.bars:
            v.delete(item)
        self.bars = []
        self.trans = None
        if not instant:
            # "scan wipe": the new page sits in place under a dark curtain, and a glowing cyan edge sweeps
            # left to right uncovering it (time-based, so it is equally smooth on any PC)
            top = v.canvasy(0)
            curtain = v.create_rectangle(0, top, self.vw + 40, top + self.vh, fill=NAVY, outline="")
            glow = v.create_line(-5, top, -5, top + self.vh, fill=LAV, width=8)
            edge = v.create_line(0, top, 0, top + self.vh, fill=CYAN, width=2)
            self.bars = [curtain, glow, edge]
            self.trans = time.perf_counter()
            self.frame_now()

    def rerender(self):
        self.show(self.page, instant=True, keep_scroll=True)

    def head(self, title, sub, y=34):
        t = self.text(self.x0, y, title, 17, WHITE, bold=True)
        x = self.view.bbox(t)[2] + 12
        self.text(x, y + 1, "// " + sub, 11, PINK)
        if self.message:
            self.text(self.x0, y + 26, self.message, 10, CYAN, width=self.cw)
            return y + 56
        return y + 34

    def target_name(self, target=None):
        target = self.target if target is None else target
        if target == GLOBAL:
            return "All lights"
        z = self.zone(target)
        return self.label(z) if z else target

    def label(self, z):
        """A light's name; lights with the same name (e.g. two RAM sticks) get their device's name added."""
        eng = self.engine
        name = eng.light_name(z)
        twins = [o for o in eng.zones if o.leds > 0 and eng.light_name(o) == name]
        if len(twins) > 1:
            dev = eng.display_name(z.device, z.device)
            name = f"{name} · {dev}" if dev != name else f"{name} {twins.index(z) + 1}"
            if [self.label_raw(o) for o in twins].count(name) > 1:
                name = f"{eng.light_name(z)} {twins.index(z) + 1}"
        return name

    def label_raw(self, z):
        eng = self.engine
        dev = eng.display_name(z.device, z.device)
        name = eng.light_name(z)
        return f"{name} · {dev}" if dev != name else name

    def zone(self, key):
        return next((z for z in self.engine.zones if z.key == key), None)

    def effect_text(self, z):
        eng = self.engine
        if not eng.is_enabled(z.key):
            return "Off"
        if eng.uses_own_effect(z.key):
            e = eng.get_effect(z.key)
            return e.name if e else "-"
        g = eng.get_effect(GLOBAL)
        return f"All lights · {g.name if g else '-'}"

    # ---------- Lights ----------
    def page_lights(self):
        eng = self.engine
        zones = [z for z in eng.zones if z.leds > 0]
        y = self.head("YOUR LIGHTS", f"{len(zones)} online" if zones else "looking for lights")
        x, w = self.x0, self.cw
        g = eng.get_effect(GLOBAL)
        tag = self.uid()
        self.card(x, y, w, 66, tags=(tag,), fill=CARD_HI)
        self.text(x + 24, y + 22, "ALL LIGHTS", 13, CYAN, bold=True, tags=(tag,))
        self.text(x + 24, y + 45, f"Effect: {g.name if g else '-'}  ·  click to change", 10, DIM, tags=(tag,))
        followers = [z for z in zones if not eng.uses_own_effect(z.key) and eng.is_enabled(z.key)] or zones
        if followers:
            self.strip(x + 380, y + 26, w - 420, max(followers, key=lambda z: z.leds).key, 40, 14)
        self.bind_click(tag, lambda: self.open_settings(GLOBAL))
        y += 86
        if not zones:
            self.text(x, y, eng.status or "Connecting to OpenRGB...", 11, DIM)
            return y + 30
        device = None
        for z in zones:
            if z.device != device:
                device = z.device
                self.text(x, y + 10, eng.display_name(device, device).upper(), 10, PINK, bold=True)
                y += 28
            on = eng.is_enabled(z.key)
            tag = self.uid()
            self.card(x, y, w, 54, tags=(tag,))
            self.text(x + 24, y + 27, eng.light_name(z), 12, WHITE if on else DIM, tags=(tag,), width=280)
            self.text(x + 316, y + 27, self.effect_text(z), 10, LAV if on else OFF, tags=(tag,), width=210)
            self.strip(x + 540, y + 20, max(40, w - 750), z.key, 30, 14)
            self.bind_click(tag, lambda k=z.key: self.open_settings(k))
            self.button(x + w - 186, y + 14, "Blink", lambda k=z.key: eng.identify_lights([k]), small=True)
            self.toggle(x + w - 70, y + 16, on, lambda val, k=z.key: (eng.set_enabled(k, val), self.root.after(250, self.rerender)))
            y += 62
        if eng.other_devices:
            y += 10
            self.text(x, y, f"Found, not controllable: {len(eng.other_devices)} device"
                            f"{'s' if len(eng.other_devices) != 1 else ''}. Open the classic window "
                            f"(Settings) to report one or record it for a new driver.", 10, DIM, width=w)
            y += 30
        return y

    def open_settings(self, target):
        self.target = target
        self.show("settings")

    # ---------- Light settings ----------
    def page_settings(self):
        eng = self.engine
        x, w = self.x0, self.cw
        y = self.head("LIGHT SETTINGS", self.target_name())
        zones = [z for z in eng.zones if z.leds > 0]
        if self.target != GLOBAL and not self.zone(self.target):
            self.target = GLOBAL
        # which light
        self.text(x, y + 6, "LIGHT", 9, LAV)
        names = ["All lights"] + [self.label(z) for z in zones]
        keys = [GLOBAL] + [z.key for z in zones]
        y = self.chips(x, y + 22, names, self.target_name(), lambda n: self.open_target(keys[names.index(n)]), w)
        target = self.target
        following = target != GLOBAL and not eng.uses_own_effect(target)
        y += 8
        # this light
        if target != GLOBAL:
            self.card(x, y, w, 64)
            self.text(x + 24, y + 32, "On", 11)
            self.toggle(x + 60, y + 21, eng.is_enabled(target), lambda val: eng.set_enabled(target, val))
            bx = x + 140
            bx += self.button(bx, y + 16, "Blink to find it", lambda: eng.identify_lights([target])) + 10
            bx += self.button(bx, y + 16, "Rename", self.rename_target) + 10
            z = self.zone(target)
            self.text(x + w - 24, y + 32, f"{getattr(z, 'lit', z.leds)} LEDs", 10, DIM, anchor="e")
            y += 80
        # live strip
        followers = [z for z in zones if not eng.uses_own_effect(z.key) and eng.is_enabled(z.key)] or zones
        live = target if target != GLOBAL else (max(followers, key=lambda z: z.leds).key if followers else None)
        if live:
            self.text(x, y + 4, "LIVE", 9, LAV)
            self.strip(x, y + 20, w, live, 80, 16)
            y += 52
        # effect
        self.card(x, y, w, 10, pulse=False)
        top_card = y
        self.text(x + 24, y + 24, "EFFECT", 9, LAV)
        opts = (["Follow All lights"] if target != GLOBAL else []) + eng.effect_names()
        eff = None if following else eng.get_effect(target)
        current = "Follow All lights" if following else (eff.name if eff else "")
        y = self.chips(x + 24, y + 40, opts, current, self.choose_effect, w - 48)
        if following:
            g = eng.get_effect(GLOBAL)
            self.text(x + 24, y + 4, f"Runs the All lights effect ({g.name if g else '-'}). Pick an effect above to "
                                     f"give this light its own.", 10, DIM, width=w - 48)
            y += 30
        elif eff is not None:
            if eff.description:
                d = self.text(x + 24, y + 6, eff.description, 10, DIM, width=w - 48, anchor="nw")
                y = self.view.bbox(d)[3] + 12
            self.button(x + 24, y, "Reset to default", lambda: (eng.reset_effect(target), self.rerender()), small=True)
            y += 40
        self.resize_card(top_card, x, w, y - top_card)
        y += 16
        if eff is None or following:
            for err in eng.effect_errors:
                self.text(x, y, "⚠ " + err, 10, RED, width=w)
                y += 24
            return y
        # effect settings
        shown = [(k, p) for k, p in eff.params.items() if p.visible(eff.values)]
        self.controllers = {k for p in eff.params.values() for k in (p.show_if or {})}
        if shown:
            card_top = y
            self.card(x, y, w, 10, pulse=False)
            self.text(x + 24, y + 24, f"{eff.name.upper()} SETTINGS", 9, LAV)
            y += 48
            for key, p in shown:
                y = self.param_row(x + 24, y, w - 48, key, p, eff.values.get(key, p.default))
            self.resize_card(card_top, x, w, y - card_top + 6)
            y += 20
        for err in eng.effect_errors:
            self.text(x, y, "⚠ " + err, 10, RED, width=w)
            y += 24
        return y

    def resize_card(self, top, x, w, h):
        """Stretch the card that starts at `top` to its final height (cards are drawn before their content)."""
        v = self.view
        for item in v.find_withtag("page"):
            if v.type(item) == "polygon":
                c = v.coords(item)
                if len(c) == 12 and abs(c[1] - top) < .5 and abs(c[0] - x) < .5:
                    v.coords(item, *chamfer(x, top, w, h, 14))
                    v.tag_lower(item)
                    v.tag_lower("bg")
                    return

    def open_target(self, key):
        self.target = key
        self.show("settings", instant=True)

    def choose_effect(self, name):
        eng, target = self.engine, self.target
        if name == "Follow All lights":
            eng.set_override(target, False)
        else:
            if target != GLOBAL:
                eng.set_override(target, True)
            eng.set_effect(target, name)
        self.rerender()

    def rename_target(self):
        if self.target == GLOBAL:
            return
        z = self.zone(self.target)
        new = simpledialog.askstring("Rename", "New name (empty = original name):",
                                     initialvalue=self.engine.light_name(z), parent=self.root)
        if new is not None:
            self.engine.rename(z.key if z.part else z.hw_key, new)
            self.rerender()

    def set_value(self, key, value):
        eff = self.engine.get_effect(self.target)
        if eff is not None and key in eff.values:
            eff.values[key] = value
            if key in getattr(self, "controllers", ()):
                self.root.after(10, self.rerender)

    def param_row(self, x, y, w, key, p, value):
        v = self.view
        self.text(x, y + 13, p.label, 11, WHITE, width=200)
        cx, cw = x + 220, w - 220
        if p.kind == "number":
            self.slider(cx, y + 13, cw - 70, p.min, p.max, p.step, value, lambda val, k=key: self.set_value(k, val))
            y += 30
        elif p.kind == "color":
            tag = self.uid()
            v.create_rectangle(cx, y, cx + 70, y + 26, fill=value, outline=EDGE, width=2, tags=("page", tag))
            self.text(cx + 82, y + 13, value, 10, DIM)

            def pick(k=key, cur=value):
                res = colorchooser.askcolor(color=cur, title=p.label, parent=self.root)
                if res and res[1]:
                    self.set_value(k, res[1])
                    self.rerender()
            self.bind_click(tag, pick)
            y += 34
        elif p.kind == "choice":
            y = self.chips(cx, y, list(p.options), value, lambda val, k=key: (self.set_value(k, val), self.rerender()), cw) - 4
        elif p.kind == "bool":
            self.toggle(cx, y + 2, bool(value), lambda val, k=key: self.set_value(k, val))
            y += 32
        elif p.kind == "palette":
            y = self.palette_row(cx, y, cw, key, p, list(value or p.default))
        if getattr(p, "hint", None):
            t = self.text(x + 220, y + 2, p.hint, 9, DIM, width=w - 220, anchor="nw")
            y = self.view.bbox(t)[3] + 6
        return y + 10

    def palette_row(self, x, y, w, key, p, colors):
        v = self.view

        def commit(cols):
            self.set_value(key, list(cols))
            self.rerender()

        for i, col in enumerate(colors):
            tag = self.uid()
            sx = x + i * 36
            v.create_polygon(sx + 15, y, sx + 30, y + 15, sx + 15, y + 30, sx, y + 15, fill=col, outline="",
                             tags=("page", tag))

            def edit(i=i):
                res = colorchooser.askcolor(color=colors[i], title=f"{p.label} - color {i + 1}", parent=self.root)
                if res and res[1]:
                    cols = list(colors)
                    cols[i] = res[1]
                    commit(cols)

            def remove(_e=None, i=i):
                if len(colors) > 1:
                    commit(colors[:i] + colors[i + 1:])
            self.bind_click(tag, edit)
            v.tag_bind(tag, "<Button-3>", remove)
        ax = x + len(colors) * 36
        if len(colors) < 16:
            def add():
                res = colorchooser.askcolor(color=colors[-1], title=f"{p.label} - add a color", parent=self.root)
                if res and res[1]:
                    commit(colors + [res[1]])
            self.button(ax, y + 2, "+", add, small=True)
        y += 40
        steps = 60                                                            # the blend between them
        for k in range(steps):
            f = k / (steps - 1) * (len(colors) - 1)
            i = min(int(f), max(len(colors) - 2, 0))
            col = colors[0] if len(colors) == 1 else hexc(mix(rgb(colors[i]), rgb(colors[i + 1]), f - i))
            v.create_rectangle(x + k * w / steps, y, x + (k + 1) * w / steps + 1, y + 6, fill=col, outline="",
                               tags="page")
        y += 16
        self.text(x, y + 6, "Click a color to change it  ·  right-click to remove it", 9, DIM)
        y += 24
        y = self.chips(x, y, list(PALETTE_PRESETS), None, lambda n: commit(list(PALETTE_PRESETS[n])), w)

        def vivid():
            out = []
            for col in colors:
                r, g, b = (int(col[k:k + 2], 16) / 255 for k in (1, 3, 5))
                h, s, val = colorsys.rgb_to_hsv(r, g, b)
                if s < .08:
                    out.append(col)
                    continue
                r, g, b = colorsys.hsv_to_rgb(h, max(s, .97), max(val, .9))
                out.append(hexc((r * 255, g * 255, b * 255)))
            commit(out)
        self.button(x, y, "Make vivid", vivid, small=True)
        return y + 34

    # ---------- Preview ----------
    def page_preview(self):
        eng = self.engine
        x, w = self.x0, self.cw
        y = self.head("PREVIEW", "every LED, live")
        zones = [z for z in eng.zones if z.leds > 0]
        if not zones:
            self.text(x, y, "No lights yet.", 11, DIM)
            return y + 30
        self.text(x, y, "What every light shows right now. Lights you switched off stay dark.", 10, DIM)
        y += 30
        label_w = 240
        device = None
        for z in zones:
            if z.device != device:
                device = z.device
                self.text(x, y + 8, eng.display_name(device, device).upper(), 9, PINK, bold=True)
                y += 24
            self.text(x + 8, y + 9, eng.light_name(z), 10, WHITE if eng.is_enabled(z.key) else OFF, width=label_w - 16)
            self.strip(x + label_w, y + 2, w - label_w, z.key, None, 14)
            y += 28
        return y

    # ---------- Effects ----------
    def page_effects(self):
        eng = self.engine
        x, w = self.x0, self.cw
        y = self.head("EFFECTS", f"click one to use it on: {self.target_name()}")
        names = eng.effect_names()
        cols = max(2, min(4, int(w // 240)))
        cw = (w - (cols - 1) * 14) / cols
        current = None if (self.target != GLOBAL and not eng.uses_own_effect(self.target)) else \
            (eng.get_effect(self.target).name if eng.get_effect(self.target) else None)
        for k, name in enumerate(names):
            cx, cy = x + (k % cols) * (cw + 14), y + (k // cols) * 150
            tag = self.uid()
            self.card(cx, cy, cw, 136, tags=(tag,), fill=CARD_HI if name == current else CARD)
            self.text(cx + 22, cy + 26, name, 12, PINK if name == current else WHITE, bold=True, tags=(tag,))
            cls = eng.effect_classes.get(name)
            desc = (getattr(cls, "description", "") or "")[:70]
            self.text(cx + 22, cy + 98, desc + ("…" if len(getattr(cls, "description", "") or "") > 70 else ""), 9, DIM,
                      width=cw - 40, anchor="nw", tags=(tag,))
            n = 14
            items = []
            step = (cw - 44) / n
            for i in range(n):
                lx = cx + 22 + i * step
                items.append(self.view.create_rectangle(lx + 1, cy + 54, lx + step - 5, cy + 72, fill=OFF,
                                                        outline=CARD, width=3, tags=("page", tag)))
            try:
                inst = cls(None)
            except Exception:
                inst = None
            zone = types.SimpleNamespace(key=f"gallery {name}", index=k, leds=n, name=name, hw_name=name,
                                         hw_key=name, device="gallery", part=None, matrix=None, kind="strip", lit=n)
            self.gallery.append([inst, zone, {}, items])
            self.bind_click(tag, lambda nm=name: self.use_effect(nm))
        return y + ((len(names) + cols - 1) // cols) * 150

    def use_effect(self, name):
        eng = self.engine
        if self.target != GLOBAL:
            eng.set_override(self.target, True)
        eng.set_effect(self.target, name)
        self.message = f"{name} is now on {self.target_name()}."
        self._keep_message = True
        self.show("settings")
        self.root.after(4000, self.clear_message)

    def clear_message(self):
        if self.message:
            self.message = ""
            if self.page == "settings":
                self.rerender()

    # ---------- Settings ----------
    def page_app(self):
        eng = self.engine
        x, w = self.x0, self.cw
        y = self.head("SETTINGS", "system")

        def row(title, hint, h=72):
            nonlocal y
            self.card(x, y, w, h)
            self.text(x + 24, y + 24, title, 12, WHITE, bold=True)
            if hint:
                self.text(x + 24, y + 48, hint, 9, DIM, width=w - 360)
            top = y
            y += h + 12
            return top

        top = row("Start with Windows", "Opens minimized when you sign in, so your lights come on by themselves.")
        self.toggle(x + w - 80, top + 24, startup.is_enabled(), lambda val: startup.set_enabled(val))
        top = row("Smoothness", "Frames per second sent to the lights. Slow devices are capped on their own.")
        self.slider(x + w - 330, top + 34, 230, FPS_MIN, FPS_MAX, 1, eng.cfg.get("fps", 60),
                    lambda val: eng.set_fps(val), fmt=lambda v: f"{v} fps")
        top = row("Devices", "Look for new lights now (also happens by itself every few seconds).")
        self.button(x + w - 200, top + 20, "Rescan devices", lambda: (eng.rescan(), self.say("Looking for devices...")))
        running = apps.running_rgb_apps()
        h = 72 + 30 * len(running)
        top = row("Other RGB apps", "" if running else "No other RGB app is running.", h)
        ry = top + 56
        for name, how, tip in running:
            word = {"bridge": "works with LightDeck", "ok": "fine", "close": "close it"}[how]
            self.text(x + 24, ry, f"{name}  ·  {word}", 10, RED if how == "close" else CYAN)
            if how == "close":
                self.button(x + w - 140, ry - 13, "Close it", lambda n=name: self.close_app(n), small=True)
            ry += 30
        top = row("Report a device", "A device that doesn't light up? Saves a short list of what LightDeck sees "
                                     "(names and USB IDs, nothing personal) and opens the request form.")
        self.button(x + w - 200, top + 20, "Report a device", self.make_report)
        top = row("Folders", "Add your own effects and drivers: they load by themselves.")
        bx = x + w - 340
        bx += self.button(bx, top + 20, "Effects folder", lambda: os.startfile(EFFECTS_DIR)) + 10
        self.button(bx, top + 20, "Drivers folder", lambda: os.startfile(DRIVERS_DIR))
        top = row("Classic window", "Splitting cables, LED counts, Wi-Fi lights and recording a device are in the "
                                    "classic window for now. LightDeck restarts in it (your lights blink once).")
        self.button(x + w - 230, top + 20, "Open classic window", lambda: switch_ui(self, "classic"), accent=True)
        return y

    def say(self, msg):
        self.message = msg
        self.rerender()
        self.root.after(5000, self.clear_message_any)

    def clear_message_any(self):
        if self.message:
            self.message = ""
            self.rerender()

    def close_app(self, name):
        ok = apps.close_app(name)
        self.say(f"Closed {name}." if ok else f"Windows didn't let LightDeck close {name}: close it from its tray "
                                              f"icon (next to the clock) or turn its lighting off.")

    def make_report(self):
        try:
            path, text = report.save(self.engine)
        except OSError as e:
            self.say(f"Could not save the report: {e}")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        url = report.issue_url()
        if url:
            webbrowser.open(url)
            self.say(f"Report saved as {path.name} and copied. The form opened in your browser: paste it (Ctrl+V).")
        else:
            os.startfile(str(path))
            self.say(f"Report saved as {path.name} and copied.")

    # ================= animation =================
    def frame(self):
        self._job = None
        try:
            busy = self.animate()
        except tk.TclError:
            return
        # 60 frames a second while something moves (page change, menu, switches), 30 when calm
        self._job = self.root.after(16 if busy else 33, self.frame)

    def frame_now(self):
        """Start the fast frames right away (a click shouldn't wait for the next calm frame)."""
        if getattr(self, "_job", None):
            self.root.after_cancel(self._job)
            self._job = self.root.after(1, self.frame)

    def animate(self):
        v, s = self.view, self.side
        now = time.perf_counter()
        dt, self.last_frame = min(.1, now - self.last_frame), now
        k30 = dt * 30                                                          # "frames" at 30 fps
        busy = False
        t = now - self.start
        top = v.canvasy(0)
        if top != self.top:
            v.move("fixed", 0, top - self.top)
            self.top = top
        g = (t % 3.7) > 3.45                                                  # title glitch
        jx = random.randint(-4, 4) if g else 0
        s.coords(self.title[0], 24 + jx, 42)
        s.coords(self.title[1], 24 - jx, 42 + (random.randint(-2, 2) if g else 0))
        s.coords(self.title[2], 24 + (random.randint(-2, 2) if g else 0), 42)
        ease_nav = 1 - math.exp(-dt * 16)
        for k, b in self.nav.items():                                          # menu slide
            target = 8.0 if b["hover"] and k != self.page else 0.0
            diff = target - b["dx"]
            if abs(diff) > .05:
                busy = True
                b["dx"] = target if abs(diff) < .3 else b["dx"] + diff * ease_nav
                s.coords(b["poly"], *chamfer(18 + b["dx"], b["y"], 172, 40))
                s.coords(b["text"], 36 + b["dx"], b["y"] + 20)
        ty = self.nav[self.page]["y"]
        my = s.coords(self.marker)[1]
        if abs(ty - my) > .3:                                                  # marker + glow glide
            busy = True
            ny = my + (ty - my) * (1 - math.exp(-dt * 13))
        else:
            ny = ty
        s.coords(self.marker, 6, ny, 10, ny + 40)
        s.coords(self.nav_glow, 0, ny - 18)
        x0 = self.tick.coords(self.tick_text)[0] - 1.8 * k30                 # ticker
        bb = self.tick.bbox(self.tick_text)
        if bb[2] < 0:
            self.tick.itemconfig(self.tick_text, text=self.ticker_text())
            x0 = self.root.winfo_width()
        self.tick.coords(self.tick_text, x0, TICK / 2)
        if self.trans is not None:                                             # page change: scan wipe
            busy = True
            p = min(1.0, (now - self.trans) / SLIDE_TIME)
            e = 1 - (1 - p) ** 3                                               # ease-out: quick start, soft landing
            curtain, glow, edge = self.bars
            ex = e * (self.vw + 30)
            v.coords(curtain, ex, top, self.vw + 40, top + self.vh)
            v.coords(glow, ex - 5, top, ex - 5, top + self.vh)
            v.coords(edge, ex, top, ex, top + self.vh)
            v.itemconfig(glow, fill=hexc(mix(rgb(LAV), NAVY_RGB, .55 + .45 * p)))
            if p >= 1:
                for item in self.bars:
                    v.delete(item)
                self.bars, self.trans = [], None
            # everything else waits for the ~third of a second the wipe takes: Windows then only has to
            # redraw the thin strip the edge passes over, which keeps the wipe silky
        else:
            self.animate_page(v, t, dt, top, k30)
        ease_tg = 1 - math.exp(-dt * 18)
        for tg in self.toggles:                                                # toggle switches
            goal = 1.0 if tg["on"] else 0.0
            if abs(goal - tg["pos"]) > .01:
                busy = True
                tg["pos"] += (goal - tg["pos"]) * ease_tg
                self.place_toggle(tg)
        return busy

    def animate_page(self, v, t, dt, top, k30):
        """Rain, flickering windows, pulsing card edges, live LEDs and effect samples."""
        for d in self.drops:                                                   # rain
            d[2] += d[4] * k30
            d[1] -= .6 * k30
            if d[2] > self.vh:
                d[1], d[2] = random.uniform(0, self.vw + 100), -30
            v.coords(d[0], d[1], top + d[2], d[1] - 3, top + d[2] + d[3])
        for item, col, ph in self.windows[int(t * 10) % 3::3]:                 # flickering windows
            v.itemconfig(item, fill=col if math.sin(t * 2 + ph) > -.6 else "#0a1236")
        v.itemconfig("pulse", fill=hexc(mix(rgb("#3a1530"), rgb(PINK), (math.sin(t * 3) + 1) / 2)))
        prev = self.engine.preview                                             # live LEDs
        for cores, _, key, last in self.leds:
            cols = prev.get(key)
            if not cols:
                continue
            n = len(cores)
            stride = len(cols) / n
            for i in range(n):
                c = cols[int(i * stride)]
                if c != last[i]:
                    last[i] = c
                    bright = max(c) / 255
                    v.itemconfig(cores[i], fill=hexc(c) if bright > .04 else OFF,
                                 outline=hexc(mix(CARD_RGB, c, .4 * bright)))
        for inst, zone, state, items in self.gallery:                          # effect samples
            if inst is None:
                continue
            try:
                cols = list(inst.render(t, dt, len(items), zone, state))
            except Exception:
                continue
            for item, c in zip(items, cols):
                c = tuple(max(0, min(255, int(x))) for x in c[:3])
                v.itemconfig(item, fill=hexc(c), outline=hexc(mix(CARD_RGB, c, .4 * max(c) / 255)))

    def ticker_text(self):
        eng = self.engine
        zones = [z for z in eng.zones if z.leds > 0]
        parts = ["SYS ONLINE" if eng.client else "CONNECTING", f"{len(zones)} LIGHTS",
                 f"{sum(z.leds for z in zones)} LEDS", f"{eng.actual_fps:.0f} FPS"]
        clash = apps.conflicts()
        parts += [f"CLOSE {n.upper()}: IT FIGHTS LIGHTDECK" for n, _, _ in clash] or ["NO RGB CONFLICTS"]
        if eng.last_error:
            parts.append("WARNING: " + eng.last_error)
        g = eng.get_effect(GLOBAL)
        parts.append(f"ALL LIGHTS: {g.name.upper() if g else '-'}")
        parts.append("RAIN OVER NIGHT CITY")
        return "  //  ".join(parts) + "  //"

    def slow(self):
        """Every half second: status, device changes, hot-reloaded effects, autosave."""
        eng = self.engine
        try:
            ok = bool(eng.client)
            self.side.itemconfig(self.link_dot, fill=CYAN if ok and int(time.time() * 2) % 2 else
                                 ("#1f6f86" if ok else RED))
            self.side.itemconfig(self.link_text, text="OpenRGB linked" if ok else "Connecting...")
            self.side.itemconfig(self.fps_text, text=f"{eng.actual_fps:5.0f} fps" if ok else "")
            if eng.reload_if_changed() and self.page in ("settings", "effects"):
                self.rerender()
            sig = (tuple((z.key, z.leds) for z in eng.zones), tuple(eng.cfg["disabled"]), tuple(eng.cfg["overrides"]),
                   tuple(sorted(eng.cfg["names"].items())), len(eng.other_devices))
            if sig != self.lights_sig:
                first = self.lights_sig is None
                self.lights_sig = sig
                if not first and self.page in ("lights", "preview", "settings"):
                    self.rerender()
            self.save_timer += 1
            if self.save_timer % 4 == 0:
                self.tick.itemconfig(self.tick_text, text=self.ticker_text())
            if self.save_timer >= 20:
                self.save_timer = 0
                try:
                    eng.save_config()
                except Exception:
                    pass
        except tk.TclError:
            return
        self.root.after(500, self.slow)

    def on_close(self):
        try:
            self.engine.save_config()
        finally:
            self.engine.stop()
            self.root.destroy()


def switch_ui(ui, name):
    """Remember which window to use and restart LightDeck in it."""
    eng = ui.engine
    eng.cfg["ui"] = name
    try:
        eng.save_config()
    finally:
        eng.stop()
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")]
        subprocess.Popen(cmd, cwd=os.path.dirname(cmd[-1]))
        ui.root.destroy()
