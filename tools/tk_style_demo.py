"""What plain tkinter (+ Pillow for the glow) can do: a Night City style LightDeck window.
A demo only: it doesn't talk to any lights. Run: pythonw tools/tk_style_demo.py  (Esc closes it)."""
import math
import random
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

W, H = 1040, 640
NAVY, PANEL, CARD, EDGE = "#060a1c", "#0b1230", "#0e1640", "#1f3a7a"
CYAN, BLUE, LAV, PINK, RED, WHITE, DIM = "#3ee0ff", "#2f6bff", "#a78bff", "#ff4f9a", "#ff3355", "#f2f6ff", "#8fa6e6"
COLORS = [CYAN, BLUE, LAV, PINK, RED, WHITE]
EFFECTS = ["Rain", "Wave", "Breathe", "Ripple", "Glitch", "Static"]
FONT = "Bahnschrift"
LEVELS = 10
X0 = 215                                   # left edge of the page area


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hexc(c):
    return "#%02x%02x%02x" % c


def chamfer(x, y, w, h, c=12):
    return [x, y, x + w - c, y, x + w, y + c, x + w, y + h, x + c, y + h, x, y + h - c]


def level(e, t, i, n):
    """How bright LED i of n is at time t for effect e (0..1)."""
    if e == "Breathe":
        return (math.sin(t * 2) + 1) / 2
    if e == "Wave":
        return (math.sin(t * 3 - i * .55) + 1) / 2
    if e == "Static":
        return 1.0
    if e == "Ripple":
        return max(0.0, 1 - abs((t * 9) % (n + 6) - i) / 3)
    if e == "Glitch":
        return 1.0 if math.sin(i * 91 + math.floor(t * 9) * 7) > .55 else .08
    return ((math.sin(i * 12.9 + math.floor(t * 6 + i * .7)) + 1) / 2) ** 4


class Demo:
    def __init__(self, root):
        self.root = root
        self.c = tk.Canvas(root, width=W, height=H, bg=NAVY, highlightthickness=0)
        self.c.pack()
        self.cache = {}
        self.page, self.eff, self.pick, self.speed = "lights", "Rain", 0, 55
        self.start = time.perf_counter()
        self.leds, self.anims, self.bars = [], [], []
        self.slide = 0.0
        self.spin = 0.0
        self.toggle_on, self.knob = True, 1.0
        self.city()
        self.rain()
        for y in range(0, H, 4):                                       # faint screen lines
            self.c.create_line(0, y, W, y, fill="#08102a")
        self.nav()
        self.ticker()
        self.show("lights", instant=True)
        root.bind("<Escape>", lambda e: root.destroy())
        self.frame()

    # ---------- glowing LEDs: Pillow draws each brightness once, tkinter just swaps pictures ----------
    def sprite(self, color, lv, w, h, dot):
        key = (color, lv, w, h, dot)
        if key not in self.cache:
            v = lv / (LEVELS - 1)
            pad = max(7, min(w, h))
            img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
            halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(halo)
            box = (pad - 4, pad - 4, pad + w + 3, pad + h + 3)
            (draw.ellipse if dot else draw.rectangle)(box, fill=rgb(color) + (int(230 * v * v),))
            img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(pad * .55)))
            draw = ImageDraw.Draw(img)
            core = mix((22, 30, 74), rgb(color), .12 + .88 * v)
            (draw.ellipse if dot else draw.rectangle)((pad, pad, pad + w - 1, pad + h - 1), fill=core + (255,))
            if v > .7 and dot:
                hot = mix(core, (255, 255, 255), .5)
                draw.ellipse((pad + w * .3, pad + h * .3, pad + w * .7, pad + h * .7), fill=hot + (255,))
            self.cache[key] = ImageTk.PhotoImage(img)
        return self.cache[key]

    def led(self, x, y, i, n, w=10, h=10, dot=True, color=None, effect=None):
        item = self.c.create_image(x, y, image=self.sprite(color or COLORS[self.pick], 0, w, h, dot), tags="page")
        self.leds.append((item, i, n, w, h, dot, color, effect))

    def glow_box(self, w, h, color):
        key = ("box", w, h, color)
        if key not in self.cache:
            pad = 18
            img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
            ImageDraw.Draw(img).polygon(chamfer(pad, pad, w, h, 10), fill=rgb(color) + (200,))
            self.cache[key] = ImageTk.PhotoImage(img.filter(ImageFilter.GaussianBlur(9)))
        return self.cache[key]

    # ---------- background: skyline with flickering windows, rain ----------
    def city(self):
        self.windows = []
        x = 0
        while x < W:
            w, h = random.randint(30, 80), random.randint(80, 260)
            self.c.create_rectangle(x, H - h, x + w, H, fill="#0b143a", outline="")
            for _ in range(w * h // 600):
                wx, wy = x + random.randint(4, w - 8), H - h + random.randint(6, h - 10)
                item = self.c.create_rectangle(wx, wy, wx + 4, wy + 3, outline="",
                                               fill=random.choice(["#1f6f86", "#7a2a55"]))
                self.windows.append((item, self.c.itemcget(item, "fill"), random.random() * 40))
            x += w + 4

    def rain(self):
        self.drops = []
        for _ in range(120):
            x, y, ln = random.uniform(0, W), random.uniform(0, H), random.uniform(10, 24)
            self.drops.append([self.c.create_line(x, y, x - 3, y + ln, fill="#2c4384"), x, y, ln,
                               random.uniform(7, 13)])

    # ---------- side bar ----------
    def nav(self):
        c = self.c
        c.create_rectangle(0, 0, 195, H, fill=PANEL, outline="")
        c.create_line(195, 0, 195, H, fill=EDGE)
        self.title = [c.create_text(24, 40, text="LIGHTDECK", anchor="w", fill=col, font=(FONT, 22, "bold"))
                      for col in (PINK, LAV, CYAN)]
        c.create_text(26, 68, text="// NIGHT CITY RGB", anchor="w", fill=PINK, font=(FONT, 9))
        self.nav_glow = c.create_image(0, 0, image=self.glow_box(165, 38, CYAN), anchor="nw")
        self.marker = c.create_rectangle(6, 110, 10, 148, fill=PINK, outline="")
        self.buttons = {}
        for i, (key, label) in enumerate([("lights", "Lights"), ("settings", "Light settings"),
                                          ("preview", "Preview"), ("effects", "Effects"), ("app", "Settings")]):
            y = 110 + i * 50
            poly = c.create_polygon(chamfer(18, y, 165, 38), fill="#14204d", outline="", tags=f"nav{i}")
            text = c.create_text(36, y + 19, text="◆  " + label, anchor="w", fill=DIM, font=(FONT, 11), tags=f"nav{i}")
            self.buttons[key] = {"poly": poly, "text": text, "y": y, "dx": 0.0, "hover": False}
            c.tag_bind(f"nav{i}", "<Enter>", lambda e, k=key: self.hover(k, True))
            c.tag_bind(f"nav{i}", "<Leave>", lambda e, k=key: self.hover(k, False))
            c.tag_bind(f"nav{i}", "<Button-1>", lambda e, k=key: self.show(k))
            c.tag_bind(f"nav{i}", "<Enter>", lambda e: c.config(cursor="hand2"), add="+")
            c.tag_bind(f"nav{i}", "<Leave>", lambda e: c.config(cursor=""), add="+")
        self.dot = c.create_oval(26, 380, 34, 388, fill=CYAN, outline="")
        c.create_text(42, 384, text="OpenRGB linked", anchor="w", fill=DIM, font=(FONT, 9))

    def hover(self, key, on):
        self.buttons[key]["hover"] = on

    def ticker(self):
        self.c.create_rectangle(195, H - 26, W, H, fill="#050916", outline="")
        self.c.create_line(195, H - 26, W, H - 26, fill=PINK)
        msg = ("SYS ONLINE // 5 DEVICES // 202 LEDS // 60 FPS // RAIN OVER NIGHT CITY // ASUS X870-A OK // "
               "RX 9070 XT OK // KLEVV RAM OK // RK N80 OK // NO RGB CONFLICTS //")
        self.tick_text = self.c.create_text(W, H - 13, text=msg, anchor="w", fill=CYAN, font=("Consolas", 9))

    # ---------- pages ----------
    def show(self, page, instant=False):
        self.page = page
        self.c.delete("page")
        self.leds, self.anims = [], []
        getattr(self, "page_" + page)()
        self.c.tag_raise(self.tick_text)
        for k, b in self.buttons.items():
            on = k == page
            self.c.itemconfig(b["poly"], fill=CYAN if on else "#14204d")
            self.c.itemconfig(b["text"], fill=NAVY if on else DIM)
        if not instant:
            self.slide = 60.0
            self.c.move("page", 60, 0)
            for _ in range(5):                                              # glitch slices
                y = random.randint(30, H - 60)
                self.bars.append([self.c.create_rectangle(X0, y, W - 20, y + random.randint(2, 9),
                                                          fill=random.choice([PINK, CYAN, LAV]), outline=""), 6])

    def text(self, x, y, s, size=11, color=WHITE, anchor="w", bold=False, tags=()):
        return self.c.create_text(x, y, text=s, anchor=anchor, fill=color,
                                  font=(FONT, size, "bold" if bold else "normal"), tags=("page",) + tuple(tags))

    def card(self, x, y, w, h, tags=()):
        c = self.c
        c.create_polygon(chamfer(x, y, w, h, 14), fill=CARD, outline=EDGE, tags=("page", "card") + tuple(tags))
        c.create_rectangle(x, y + 3, x + 3, y + h - 14, fill=PINK, outline="", tags=("page", "pulse") + tuple(tags))

    def head(self, a, b):
        t = self.text(X0 + 10, 40, a, 16, WHITE, bold=True)
        x = self.c.bbox(t)[2] + 10
        self.text(x, 41, "// " + b, 11, PINK)

    def clickable(self, tag, fn):
        self.c.tag_bind(tag, "<Button-1>", lambda e: fn())
        self.c.tag_bind(tag, "<Enter>", lambda e: self.c.config(cursor="hand2"))
        self.c.tag_bind(tag, "<Leave>", lambda e: self.c.config(cursor=""))

    def page_lights(self):
        self.head("YOUR LIGHTS", "5 online")
        devs = [("ASUS X870-A board", "Rain", CYAN), ("ARGB header 1", "Wave", PINK), ("RX 9070 XT", "Breathe", LAV),
                ("KLEVV RAM x2", "Rain", BLUE), ("RK N80 keyboard", "Ripple", CYAN)]
        for i, (name, eff, col) in enumerate(devs):
            y = 75 + i * 70
            self.card(X0 + 10, y, 770, 56, tags=(f"dev{i}",))
            self.led(X0 + 42, y + 28, i, 5, 12, 12, True, col, "Breathe")
            self.text(X0 + 70, y + 28, name, 13, WHITE, tags=(f"dev{i}",))
            self.text(X0 + 700, y + 28, eff + "  ›", 11, LAV, anchor="e", tags=(f"dev{i}",))
            self.clickable(f"dev{i}", lambda: self.show("settings"))

    def page_settings(self):
        self.head("LIGHT SETTINGS", "ASUS X870-A")
        self.card(X0 + 10, 70, 770, 90)
        self.text(X0 + 30, 92, "EFFECT", 9, LAV)
        x = X0 + 30
        for e in EFFECTS:
            w = 22 + len(e) * 8
            sel = e == self.eff
            self.c.create_rectangle(x, 108, x + w, 136, fill=PINK if sel else CARD, outline=PINK if sel else EDGE,
                                    tags=("page", f"fx{e}"))
            self.text(x + w / 2, 122, e, 10, NAVY if sel else DIM, anchor="center", tags=(f"fx{e}",))
            self.clickable(f"fx{e}", lambda e=e: (setattr(self, "eff", e), self.show("settings", True)))
            x += w + 8
        self.card(X0 + 10, 175, 770, 90)
        self.text(X0 + 30, 197, "COLOR", 9, LAV)
        self.diamonds = []
        for i, col in enumerate(COLORS):
            cx, cy = X0 + 50 + i * 52, 232
            if i == self.pick:
                self.led(cx, cy, 0, 1, 26, 26, True, col, "Static")
            d = self.c.create_polygon(0, 0, 0, 0, fill=col, outline="", tags=("page", f"sw{i}"))
            self.diamonds.append((d, cx, cy, i == self.pick))
            self.clickable(f"sw{i}", lambda i=i: (setattr(self, "pick", i), self.show("settings", True)))
        self.card(X0 + 10, 280, 770, 80)
        self.speed_label = self.text(X0 + 30, 302, f"SPEED  {self.speed}%", 9, LAV)
        self.c.create_line(X0 + 30, 333, X0 + 760, 333, fill=EDGE, width=4, tags=("page", "track"))
        self.fill = self.c.create_line(X0 + 30, 333, X0 + 30, 333, fill=PINK, width=4, tags="page")
        self.knob_item = self.c.create_polygon(0, 0, 0, 0, fill=WHITE, outline=PINK, width=2, tags=("page", "knob"))
        for tag in ("track", "knob"):
            self.c.tag_bind(tag, "<Button-1>", self.drag)
            self.c.tag_bind(tag, "<B1-Motion>", self.drag)
        self.place_knob()
        self.text(X0 + 20, 385, "LIVE STRIP", 9, LAV)
        for i in range(30):
            self.led(X0 + 30 + i * 25, 415, i, 30, 11, 11, True)

    def drag(self, e):
        self.speed = int(max(0, min(100, (e.x - (X0 + 30)) / 7.3)))
        self.c.itemconfig(self.speed_label, text=f"SPEED  {self.speed}%")
        self.place_knob()

    def place_knob(self):
        x = X0 + 30 + self.speed * 7.3
        self.c.coords(self.fill, X0 + 30, 333, x, 333)
        self.c.coords(self.knob_item, x, 323, x + 10, 333, x, 343, x - 10, 333)

    def page_preview(self):
        self.head("PREVIEW", self.eff)
        c, ox, oy = self.c, X0 + 120, 70
        line = dict(outline=EDGE, width=2, tags="page")
        c.create_rectangle(ox, oy, ox + 300, oy + 330, **line)                       # case
        c.create_rectangle(ox + 70, oy + 50, ox + 230, oy + 170, **line)             # board
        c.create_rectangle(ox + 40, oy + 220, ox + 260, oy + 255, **line)            # graphics card
        for i in range(16):                                                           # strips on both sides
            self.led(ox + 18, oy + 18 + i * 19, i, 16, 9, 12, False)
            self.led(ox + 282, oy + 18 + i * 19, 15 - i, 16, 9, 12, False)
        for i in range(8):                                                            # RAM
            self.led(ox + 95 + i * 15, oy + 95, i + 3, 16, 7, 40, False)
        for i in range(14):                                                           # GPU edge
            self.led(ox + 55 + i * 15, oy + 238, i, 14, 10, 8, False)
        for i in range(3):                                                            # fans
            self.led(ox + 400, oy + 60 + i * 100, i * 4, 12, 44, 44, True)
            c.create_oval(ox + 370, oy + 30 + i * 100, ox + 430, oy + 90 + i * 100, outline=EDGE, width=2, tags="page")
        c.create_rectangle(X0 + 40, 430, X0 + 760, 520, **line)                       # keyboard
        for r in range(4):
            for i in range(26):
                self.led(X0 + 62 + i * 27, 447 + r * 20, i + r * 2, 26, 20, 14, False)

    def page_effects(self):
        self.head("EFFECTS", "pick one")
        for k, e in enumerate(EFFECTS):
            x, y = X0 + 10 + (k % 3) * 260, 75 + (k // 3) * 150
            self.card(x, y, 245, 130, tags=(f"ec{e}",))
            for i in range(10):
                self.led(x + 30 + i * 20, y + 50, i, 10, 9, 9, True, None, e)
            self.text(x + 122, y + 98, e, 13, PINK if e == self.eff else WHITE, anchor="center", tags=(f"ec{e}",))
            self.clickable(f"ec{e}", lambda e=e: (setattr(self, "eff", e), self.show("preview")))

    def page_app(self):
        self.head("SETTINGS", "system")
        rows = ["Start with Windows", "Theme", "Wi-Fi lights", "Other RGB apps", "Report a device"]
        for i, r in enumerate(rows):
            y = 75 + i * 70
            self.card(X0 + 10, y, 770, 56)
            self.text(X0 + 30, y + 28, r, 13)
        y = 75
        self.c.create_rectangle(X0 + 690, y + 18, X0 + 750, y + 38, fill=EDGE, outline="", tags=("page", "tg"))
        self.toggle_knob = self.c.create_oval(0, 0, 0, 0, fill=WHITE, outline="", tags=("page", "tg"))
        self.toggle_bg = self.c.find_withtag("tg")[0]
        self.clickable("tg", lambda: setattr(self, "toggle_on", not self.toggle_on))
        for j, t in enumerate(["Night City", "Neon pink", "Ice"]):
            x = X0 + 470 + j * 100
            self.c.create_rectangle(x, 163, x + 92, 189, fill=PINK if j == 0 else CARD, outline=PINK if j == 0 else EDGE,
                                    tags="page")
            self.text(x + 46, 176, t, 10, NAVY if j == 0 else DIM, anchor="center")
        self.text(X0 + 750, 75 + 3 * 70 + 28, "none running", 11, CYAN, anchor="e")

    # ---------- animation ----------
    def frame(self):
        c = self.c
        now = time.perf_counter() - self.start
        t = now * (.3 + self.speed / 45)
        for d in self.drops:                                                         # rain
            d[2] += d[4]
            d[1] -= .6
            if d[2] > H:
                d[1], d[2] = random.uniform(0, W + 100), -30
            c.coords(d[0], d[1], d[2], d[1] - 3, d[2] + d[3])
        for item, col, ph in self.windows[::3] if int(now * 10) % 2 else self.windows[1::3]:
            c.itemconfig(item, fill=col if math.sin(now * 2 + ph) > -.6 else "#0b143a")
        g = (now % 3.5) > 3.25                                                       # title glitch
        jx = random.randint(-4, 4) if g else 0
        c.coords(self.title[0], 24 + jx, 40)
        c.coords(self.title[1], 24 - jx, 40 + (random.randint(-2, 2) if g else 0))
        c.coords(self.title[2], 24 + (random.randint(-2, 2) if g else 0), 40)
        for k, b in self.buttons.items():                                           # side bar slide
            target = 8.0 if b["hover"] and k != self.page else 0.0
            step = (target - b["dx"]) * .3
            if abs(step) > .05:
                b["dx"] += step
                c.coords(b["poly"], *chamfer(18 + b["dx"], b["y"], 165, 38))
                c.coords(b["text"], 36 + b["dx"], b["y"] + 19)
        ty = self.buttons[self.page]["y"]
        mx = c.coords(self.marker)
        ny = mx[1] + (ty - mx[1]) * .25
        c.coords(self.marker, 6, ny, 10, ny + 38)
        c.coords(self.nav_glow, 0, ny - 18)
        c.itemconfig(self.dot, fill=CYAN if int(now * 2) % 2 else "#1f6f86")
        x0 = c.coords(self.tick_text)[0] - 1.6                                       # ticker
        bb = c.bbox(self.tick_text)
        c.coords(self.tick_text, x0 if bb[2] > 195 else W, H - 13)
        pulse = hexc(mix(rgb("#3a1530"), rgb(PINK), (math.sin(now * 3) + 1) / 2))
        c.itemconfig("pulse", fill=pulse)
        if self.slide > .5:                                                          # page slide-in
            step = self.slide * .28
            c.move("page", -step, 0)
            self.slide -= step
        for bar in self.bars[:]:
            bar[1] -= 1
            if bar[1] <= 0:
                c.delete(bar[0])
                self.bars.remove(bar)
        for item, i, n, w, h, dot, col, eff in self.leds:                            # LEDs
            v = level(eff or self.eff, t, i, n)
            c.itemconfig(item, image=self.sprite(col or COLORS[self.pick], int(v * (LEVELS - 1) + .5), w, h, dot))
        if self.page == "settings":                                                  # spinning picked diamond
            self.spin += .06
            for d, cx, cy, sel in self.diamonds:
                a = math.pi / 4 + (self.spin if sel else 0)
                r = 15 if sel else 12
                c.coords(d, *[v for k in range(4) for v in (cx + r * math.cos(a + k * math.pi / 2),
                                                             cy + r * math.sin(a + k * math.pi / 2))])
        if self.page == "app":                                                       # toggle switch
            self.knob += ((1.0 if self.toggle_on else 0.0) - self.knob) * .3
            kx = X0 + 700 + self.knob * 40
            c.coords(self.toggle_knob, kx - 9, 75 + 19, kx + 9, 75 + 37)
            c.itemconfig(self.toggle_bg, fill=hexc(mix(rgb(EDGE), rgb(PINK), self.knob)))
        self.root.after(30, self.frame)


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.title("LightDeck - tkinter style demo")
    root.configure(bg=NAVY)
    root.resizable(False, False)
    Demo(root)
    root.update_idletasks()
    root.geometry(f"+{(root.winfo_screenwidth() - W) // 2}+{max(0, (root.winfo_screenheight() - H) // 2 - 30)}")
    root.mainloop()
