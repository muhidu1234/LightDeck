"""LightDeck - a lightweight RGB controller on top of OpenRGB."""
import colorsys
import math
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import colorchooser, simpledialog, ttk
import tkinter.font as tkfont

import time

import hud
import report
import usbcapture
import startup
from effect_base import PALETTE_PRESETS
from engine import EFFECTS_DIR, FIRST_RUN, FPS_MAX, FPS_MIN, GLOBAL, VERSION, Engine

FOLLOW = "Same as All lights"
# settings text uses a clean, readable font; headings and buttons keep the theme's font
UI_FONTS = ("Segoe UI Variable Text", "Segoe UI")

# ---------- themes ----------
# Every color and font the window uses comes from the active theme.
THEMES = {
    # Colors taken from a rainy Night City scene: deep navy, electric blue, glowing cyan,
    # lavender highlights, a pink rim light and thin red accents.
    "Cyberpunk": {
        "bg": "#030619",          # window background (darkest navy)
        "panel": "#060b21",       # panels
        "field": "#0c1638",       # inputs, slider tracks
        "fg": "#d6e6ff",          # normal text (blue-white)
        "muted": "#5a6fa8",       # hints
        "accent": "#3082dd",      # selection, slider knobs (electric blue)
        "accent_fg": "#ffffff",   # text on top of accent
        "accent_hover": "#65bef7",
        "head": "#7fcbff",        # big headings (glowing cyan)
        "sub": "#9eaaeb",         # section headings (lavender)
        "btn_bg": "#0b1a45",
        "btn_fg": "#7fcbff",
        "btn_press": "#da5daa",   # pink rim light
        "err": "#e0405f",         # red accent
        "border": "#18306b",      # panel outlines
        "stripe": ["#b2314b", "#da5daa", "#9eaaeb", "#3082dd", "#65bef7", "#0d3e95"],
        "glitch": ("#da5daa", "#1f5fd0"),   # offset copies behind the title
        "title": "LIGHTDECK",
        "tag": "// NEURAL RGB INTERFACE  ·  v2.077",
        "font": "Bahnschrift",
        "font_head": "Bahnschrift SemiBold Condensed",
        "font_mono": "Cascadia Mono",
        "upper": True,            # uppercase buttons and headings
        "titlebar": ("#030619", "#3082dd"),   # Windows title bar color, window border
        "led_gap": 2,
    },
    "Cyberpunk Classic": {
        "bg": "#06070b",          # window background
        "panel": "#0c0f17",       # panels
        "field": "#141a26",       # inputs, slider tracks
        "fg": "#d6f6ff",          # normal text
        "muted": "#5f8193",       # hints
        "accent": "#fcee0a",      # selection, slider knobs (Cyberpunk yellow)
        "accent_fg": "#06070b",   # text on top of accent
        "accent_hover": "#fff56b",
        "head": "#fcee0a",        # big headings
        "sub": "#00f0ff",         # section headings (neon cyan)
        "btn_bg": "#0d1d27",
        "btn_fg": "#00f0ff",
        "btn_press": "#ff2a6d",   # hot pink
        "err": "#ff003c",
        "border": "#123544",      # panel outlines
        "stripe": ["#ff003c", "#ff2a6d", "#fcee0a", "#00f0ff", "#0a3c52"],
        "glitch": ("#ff2a6d", "#00f0ff"),   # offset copies behind the title
        "title": "LIGHTDECK",
        "tag": "// NEURAL RGB INTERFACE  ·  v2.077",
        "font": "Bahnschrift",
        "font_head": "Bahnschrift SemiBold Condensed",
        "font_mono": "Cascadia Mono",
        "upper": True,            # uppercase buttons and headings
        "titlebar": ("#06070b", "#fcee0a"),   # Windows title bar color, window border
        "led_gap": 2,
    },
    "Midnight": {
        "bg": "#121318", "panel": "#1b1d25", "field": "#252833", "fg": "#e8e8ee", "muted": "#8b8e9c",
        "accent": "#8a5cff", "accent_fg": "#ffffff", "accent_hover": "#a684ff",
        "head": "#e8e8ee", "sub": "#e8e8ee", "btn_bg": "#252833", "btn_fg": "#e8e8ee", "btn_press": "#6a3ce0",
        "err": "#ff7a7a", "border": "#1b1d25", "stripe": ["#8a5cff"], "glitch": None,
        "title": "LightDeck", "tag": "",
        "font": "Segoe UI", "font_head": "Segoe UI Semibold", "font_mono": "Segoe UI",
        "upper": False, "titlebar": ("#121318", "#1b1d25"), "led_gap": 1,
    },
}
DEFAULT_THEME = "Cyberpunk"
T = dict(THEMES[DEFAULT_THEME])   # the active theme


class App:
    def __init__(self, root):
        self.root = root
        self.engine = Engine()
        self.engine.start()
        self.sel = GLOBAL          # selected tree item id
        self.tree_sig = None
        self.preview_sig = None
        self.preview_items = {}
        self.save_timer = 0
        self.sections_open = {}    # folded/unfolded sections in the details panel
        fams = set(tkfont.families(root))
        self.ui_family = next((f for f in UI_FONTS if f in fams), "TkDefaultFont")

        root.title(f"LightDeck {VERSION}")
        try:
            from engine import APP_DIR
            icon = APP_DIR / "lightdeck.ico"
            if icon.exists():
                root.iconbitmap(default=str(icon))
        except Exception:
            pass
        root.geometry("1300x930")
        root.minsize(1100, 760)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.apply_theme(self.engine.cfg.get("theme", DEFAULT_THEME))
        self.tick_fast()
        self.tick_slow()
        self.settings_win = None
        self.capture = None      # an ongoing device recording: {folder, vid, pid, name}
        startup.refresh()
        if startup.started_by_windows():
            self.root.iconify()          # started at sign-in: lights on, window waits in the taskbar
        else:
            self.root.after(300, self.bring_to_front)
        if FIRST_RUN:
            self.root.after(1500, self.show_welcome)

    def bring_to_front(self):
        """Windows sometimes starts a new app minimized or behind other windows - show it properly."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(400, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except tk.TclError:
            pass

    # ---------- themes ----------
    def apply_theme(self, name):
        """Switch theme: rebuild the whole window in the new colors (lights keep running)."""
        if name not in THEMES:
            name = DEFAULT_THEME
        T.clear()
        T.update(THEMES[name])
        T["font_ui"] = self.ui_family
        self.theme_name = name
        self.engine.cfg["theme"] = name
        for w in self.root.winfo_children():
            w.destroy()
        self.root.unbind_all("<MouseWheel>")
        self.tree_sig = None
        self.preview_sig = None
        self.preview_items = {}
        self.tick_bars = []
        self.frame_no = 0
        self.status_text = ""
        self.root.configure(bg=T["bg"])
        self._style()
        self._build()
        self.refresh_details()
        self._titlebar()

    def _titlebar(self):
        """Color the Windows title bar to match (Windows 11; ignored elsewhere)."""
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

            def dwm(attr, value):
                v = ctypes.c_int(value)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

            def colorref(h):
                return int(h[1:3], 16) | (int(h[3:5], 16) << 8) | (int(h[5:7], 16) << 16)

            caption, border = T["titlebar"]
            dwm(20, 1)                       # dark mode title bar
            dwm(35, colorref(caption))       # title bar color
            dwm(34, colorref(border))        # window border color
            dwm(36, colorref(T["head"]))     # title text color
        except Exception:
            pass

    def _decorate(self, widget):
        """Themes like Cyberpunk use UPPERCASE buttons and headings."""
        if not T["upper"]:
            return
        for w in widget.winfo_children():
            try:
                if isinstance(w, ttk.Button) or (isinstance(w, ttk.Label) and
                                                 str(w.cget("style")) in ("Head.TLabel", "Sub.TLabel", "Hud.TLabel",
                                                                         "Section.TLabel")):
                    w.configure(text=str(w.cget("text")).upper())
                elif isinstance(w, ttk.Treeview):
                    for col in ("#0",) + tuple(w["columns"]):
                        w.heading(col, text=str(w.heading(col, "text")).upper())
            except tk.TclError:
                pass
            self._decorate(w)

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        body = (T["font_ui"], 10)
        self.ui = body
        s.configure(".", background=T["bg"], foreground=T["fg"], fieldbackground=T["field"], bordercolor=T["border"],
                    lightcolor=T["panel"], darkcolor=T["panel"], troughcolor=T["field"], font=body,
                    selectbackground=T["accent"], selectforeground=T["accent_fg"])
        s.configure("TFrame", background=T["bg"])
        s.configure("Panel.TFrame", background=T["panel"], borderwidth=0, relief="flat")
        s.configure("Card.TFrame", background=T["panel"], bordercolor=T["border"], lightcolor=T["border"],
                    darkcolor=T["border"], relief="solid", borderwidth=1)
        s.configure("Panel.TLabel", background=T["panel"], foreground=T["fg"])
        s.configure("Muted.TLabel", background=T["panel"], foreground=T["muted"])
        s.configure("Err.TLabel", background=T["panel"], foreground=T["err"])
        s.configure("Status.TLabel", background=T["bg"], foreground=T["muted"], font=(T["font_mono"], 9))
        s.configure("Hud.TLabel", background=T["bg"], foreground=T["sub"], font=(T["font_head"], 10))
        s.configure("Value.TLabel", background=T["bg"], foreground=T["accent"], font=(T["font_mono"], 9))
        s.configure("Head.TLabel", background=T["panel"], foreground=T["head"], font=(T["font_head"], 15))
        s.configure("Sub.TLabel", background=T["panel"], foreground=T["sub"], font=(T["font_head"], 11))
        s.configure("TButton", background=T["btn_bg"], foreground=T["btn_fg"], borderwidth=1, padding=(10, 4),
                    bordercolor=T["border"], lightcolor=T["btn_bg"], darkcolor=T["btn_bg"],
                    font=(T["font_head"], 10))
        s.map("TButton", background=[("pressed", T["btn_press"]), ("active", T["accent"])],
              foreground=[("pressed", T["accent_fg"]), ("active", T["accent_fg"])],
              bordercolor=[("active", T["accent"])])
        s.configure("TCheckbutton", background=T["panel"], foreground=T["fg"], indicatorbackground=T["field"],
                    indicatorforeground=T["accent"])
        s.map("TCheckbutton", background=[("active", T["panel"])], foreground=[("active", T["accent"])],
              indicatorbackground=[("selected", T["field"])])
        s.configure("TCombobox", fieldbackground=T["field"], background=T["btn_bg"], foreground=T["fg"],
                    arrowcolor=T["sub"], bordercolor=T["border"])
        s.map("TCombobox", fieldbackground=[("readonly", T["field"])], foreground=[("readonly", T["fg"])],
              bordercolor=[("focus", T["accent"])])
        # in the "clam" theme a Scale's background is the knob color
        s.configure("Horizontal.TScale", background=T["accent"], troughcolor=T["field"], bordercolor=T["border"],
                    lightcolor=T["accent"], darkcolor=T["accent"], sliderlength=16)
        s.map("Horizontal.TScale", background=[("active", T["accent_hover"])])
        s.configure("Treeview", background=T["panel"], fieldbackground=T["panel"], foreground=T["fg"],
                    rowheight=27, borderwidth=0, font=body)
        s.map("Treeview", background=[("selected", T["accent"])], foreground=[("selected", T["accent_fg"])])
        s.configure("Treeview.Heading", background=T["field"], foreground=T["sub"], borderwidth=0,
                    font=(T["font_head"], 10))
        s.map("Treeview.Heading", background=[("active", T["field"])])
        s.configure("TSpinbox", fieldbackground=T["field"], foreground=T["fg"], arrowcolor=T["sub"],
                    background=T["btn_bg"], bordercolor=T["border"])
        s.configure("TEntry", fieldbackground=T["field"], foreground=T["fg"], insertcolor=T["accent"],
                    bordercolor=T["border"])
        s.configure("Vertical.TScrollbar", background=T["btn_bg"], troughcolor=T["panel"], arrowcolor=T["sub"],
                    bordercolor=T["border"], lightcolor=T["btn_bg"], darkcolor=T["btn_bg"])
        s.configure("TSeparator", background=T["border"])
        # settings panels: readable text, section headings, hints, numbers
        s.configure("Form.TLabel", background=T["panel"], foreground=T["fg"], font=body)
        s.configure("Hint.TLabel", background=T["panel"], foreground=T["muted"], font=(T["font_ui"], 9))
        s.configure("Num.TLabel", background=T["panel"], foreground=T["accent_hover"], font=(T["font_mono"], 10))
        s.configure("Section.TLabel", background=T["panel"], foreground=T["sub"], font=(T["font_head"], 12))
        s.configure("Fold.TLabel", background=T["panel"], foreground=T["muted"], font=(T["font_ui"], 9))
        s.configure("Form.TCheckbutton", font=body)
        s.configure("Form.TRadiobutton", background=T["panel"], foreground=T["fg"], font=body,
                    indicatorbackground=T["field"], indicatorforeground=T["accent"])
        s.map("Form.TRadiobutton", background=[("active", T["panel"])], foreground=[("active", T["accent"])],
              indicatorbackground=[("selected", T["field"])])
        self.root.option_add("*TCombobox*Listbox.background", T["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", T["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", T["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", T["accent_fg"])
        self.root.option_add("*TCombobox*Listbox.font", body)

    def _draw_stripe(self, canvas):
        """A thin neon line that fades through the theme's stripe colors."""
        canvas.delete("all")
        w = max(canvas.winfo_width(), 10)
        cols = T["stripe"]
        if len(cols) == 1:
            canvas.create_rectangle(0, 0, w, 3, fill=cols[0], outline="")
            return
        steps = 120
        for i in range(steps):
            f = i / (steps - 1) * (len(cols) - 1)
            a, b = cols[int(f)], cols[min(int(f) + 1, len(cols) - 1)]
            t = f - int(f)
            c = "#%02x%02x%02x" % tuple(int(int(a[k:k + 2], 16) + (int(b[k:k + 2], 16) - int(a[k:k + 2], 16)) * t)
                                        for k in (1, 3, 5))
            canvas.create_rectangle(i * w / steps, 0, (i + 1) * w / steps + 1, 3, fill=c, outline="")

    def _draw_title(self, canvas):
        canvas.delete("all")
        font = (T["font_head"], 24)
        x, y = 2, 4
        if T["glitch"]:
            # chromatic "glitch" copies slightly offset behind the title
            canvas.create_text(x - 2, y + 1, text=T["title"], anchor="nw", font=font, fill=T["glitch"][0])
            canvas.create_text(x + 2, y - 1, text=T["title"], anchor="nw", font=font, fill=T["glitch"][1])
        canvas.create_text(x, y, text=T["title"], anchor="nw", font=font, fill=T["head"])
        if T["tag"]:
            canvas.create_text(x + 1, y + 38, text=T["tag"], anchor="nw", font=(T["font_mono"], 8), fill=T["muted"])

    # ---------- layout ----------
    def _build(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=14, pady=(10, 4))
        title = tk.Canvas(top, width=340, height=56 if T["tag"] else 42, bg=T["bg"], highlightthickness=0)
        title.pack(side="left")
        self.title_anim = hud.AnimatedTitle(title, T)

        controls = ttk.Frame(top)
        controls.pack(side="right")
        row1 = ttk.Frame(controls)
        row1.pack(anchor="e")
        ttk.Button(row1, text="Settings", command=self.show_settings).pack(side="right")
        ttk.Button(row1, text="Effects folder", command=lambda: os.startfile(EFFECTS_DIR)).pack(side="right", padx=(0, 6))
        ttk.Button(row1, text="Rescan devices", command=self.engine.rescan).pack(side="right", padx=6)
        theme = ttk.Combobox(row1, values=list(THEMES), state="readonly", width=11)
        theme.set(self.theme_name)
        theme.pack(side="right", padx=(0, 6))
        theme.bind("<<ComboboxSelected>>", lambda e: self.root.after(10, lambda: self.apply_theme(theme.get())))
        ttk.Label(row1, text="Theme", style="Hud.TLabel").pack(side="right", padx=(0, 6))

        row2 = ttk.Frame(controls)
        row2.pack(anchor="e", pady=(6, 0))
        self.fps_var = tk.DoubleVar(value=self.engine.cfg["fps"])
        self.fps_lbl = ttk.Label(row2, text=f"{self.engine.cfg['fps']}", style="Value.TLabel", width=4)
        self.fps_lbl.pack(side="right")
        ttk.Scale(row2, from_=FPS_MIN, to=FPS_MAX, variable=self.fps_var, length=120,
                  command=self.on_fps).pack(side="right", padx=4)
        ttk.Label(row2, text="Max FPS", style="Hud.TLabel").pack(side="right", padx=(16, 0))
        self.bright_var = tk.DoubleVar(value=self.engine.cfg["brightness"])
        self.bright_lbl = ttk.Label(row2, text=f"{self.engine.cfg['brightness']}%", style="Value.TLabel", width=5)
        self.bright_lbl.pack(side="right")

        def bright(v):
            self.engine.cfg["brightness"] = int(float(v))
            self.bright_lbl.config(text=f"{int(float(v))}%")

        ttk.Scale(row2, from_=0, to=100, variable=self.bright_var, length=140, command=bright).pack(side="right", padx=4)
        ttk.Label(row2, text="Brightness", style="Hud.TLabel").pack(side="right")

        stripe = tk.Canvas(self.root, height=3, bg=T["bg"], highlightthickness=0)
        stripe.pack(fill="x", padx=14, pady=(2, 4))
        self.stripe_anim = hud.NeonStripe(stripe, T)

        # status line along the bottom of the window
        self.status = ttk.Label(self.root, text="", style="Status.TLabel")
        self.status.pack(side="bottom", fill="x", padx=16, pady=(0, 6))

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=14, pady=6)
        body.columnconfigure(0, weight=2, uniform="c")
        body.columnconfigure(1, weight=3, uniform="c")
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Card.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(left, text="Lights", style="Head.TLabel").pack(anchor="w")
        self._tick(left)
        ttk.Label(left, text="Click to edit · double-click to rename", style="Muted.TLabel").pack(anchor="w")
        self.tree = ttk.Treeview(left, columns=("leds", "uses"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Light")
        self.tree.heading("leds", text="LEDs")
        self.tree.heading("uses", text="Effect")
        self.tree.column("#0", width=240)
        self.tree.column("leds", width=50, anchor="center")
        self.tree.column("uses", width=120)
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

        # right panel scrolls when its content is taller than the window
        outer = ttk.Frame(body, style="Card.TFrame", padding=1)
        outer.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.details_canvas = tk.Canvas(outer, bg=T["panel"], highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.details_canvas.yview)
        self.details_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.details_canvas.pack(side="left", fill="both", expand=True)
        self.details = ttk.Frame(self.details_canvas, style="Panel.TFrame", padding=14)
        win = self.details_canvas.create_window(0, 0, window=self.details, anchor="nw")
        self.details.bind("<Configure>", lambda e: self.details_canvas.configure(
            scrollregion=self.details_canvas.bbox("all")))
        self.details_canvas.bind("<Configure>", lambda e: self.details_canvas.itemconfig(win, width=e.width))

        def wheel(e):
            # only scroll the panel when the mouse is over it and it is taller than the view
            w = self.root.winfo_containing(e.x_root, e.y_root)
            while w is not None and w is not outer:
                w = w.master
            if w is outer and self.details.winfo_height() > self.details_canvas.winfo_height():
                self.details_canvas.yview_scroll(int(-e.delta / 120), "units")

        self.root.bind_all("<MouseWheel>", wheel, add="+")

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=14, pady=(6, 6))
        prev = ttk.Frame(bottom, style="Card.TFrame", padding=10)
        prev.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(prev, text="Live preview  ·  LED scan", style="Sub.TLabel").pack(anchor="w")
        self._tick(prev)
        self.canvas = tk.Canvas(prev, height=hud.Telemetry.H - 22, bg=T["panel"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(2, 0))
        self.canvas.bind("<Configure>", lambda e: setattr(self, "preview_sig", None))

        tele = ttk.Frame(bottom, style="Card.TFrame", padding=8)
        tele.pack(side="right", fill="y", padx=(6, 0))
        ttk.Label(tele, text="Telemetry", style="Sub.TLabel").pack(anchor="w")
        self._tick(tele)
        tcanvas = tk.Canvas(tele, bg=T["panel"], highlightthickness=0)
        tcanvas.pack(pady=(2, 0))
        self.telemetry = hud.Telemetry(tcanvas, self.engine, T)
        self._decorate(self.root)

    def _tick(self, parent):
        """Short accent bar under a heading (HUD style)."""
        if T["glitch"]:
            bar = tk.Frame(parent, bg=T["panel"], height=3)
            bar.pack(anchor="w", pady=(2, 4), fill="x")
            a = tk.Frame(bar, bg=T["accent"], width=46, height=3)
            a.pack(side="left")
            b = tk.Frame(bar, bg=T["btn_press"], width=10, height=3)
            b.pack(side="left", padx=(4, 0))
            self.tick_bars.append((a, b, len(self.tick_bars)))

    def on_fps(self, v):
        fps = int(float(v))
        self.engine.set_fps(fps)
        self.fps_lbl.config(text=str(fps))

    # ---------- what is selected ----------
    def zones_by_key(self):
        return {z.key: z for z in self.engine.zones}

    def kind(self, iid):
        if iid == GLOBAL:
            return "global"
        if iid.startswith("dev::"):
            return "device"
        if iid.startswith("hw::"):
            return "split"
        if iid == "others":
            return "others"
        if iid.startswith("other::"):
            return "other"
        return "light"

    def rename_key(self, iid):
        """Config key a tree item's custom name is stored under."""
        if iid.startswith("dev::"):
            return iid[5:]
        if iid.startswith("hw::"):
            return iid[4:]
        return iid

    def current_name(self, iid):
        eng = self.engine
        if iid.startswith("dev::"):
            return eng.display_name(iid[5:], iid[5:])
        if iid.startswith("hw::"):
            z = next((z for z in eng.zones if z.hw_key == iid[4:]), None)
            return eng.display_name(iid[4:], z.hw_name if z else iid[4:])
        z = self.zones_by_key().get(iid)
        if z is None:
            return iid
        return eng.display_name(z.key, z.name if z.part else z.hw_name)

    # ---------- tree ----------
    def rebuild_tree(self):
        eng = self.engine
        open_state = {iid: self.tree.item(iid, "open") for iid in self._all_items()}
        self.tree.delete(*self.tree.get_children())
        g = eng.get_effect(GLOBAL)
        self.tree.insert("", "end", iid=GLOBAL, text="All lights", values=("", g.name if g else "-"))
        parents = {}
        for z in eng.zones:
            dev_iid = "dev::" + z.device
            if dev_iid not in parents:
                parents[dev_iid] = self.tree.insert("", "end", iid=dev_iid, text=eng.display_name(z.device, z.device),
                                                    open=open_state.get(dev_iid, True))
            parent = dev_iid
            if z.part is not None:
                hw_iid = "hw::" + z.hw_key
                if hw_iid not in parents:
                    parents[hw_iid] = self.tree.insert(dev_iid, "end", iid=hw_iid,
                                                       text=eng.display_name(z.hw_key, z.hw_name),
                                                       values=(z.hw_leds, self.split_text(z.hw_key)),
                                                       open=open_state.get(hw_iid, True))
                parent = hw_iid
            if not eng.is_enabled(z.key):
                uses = "Off"
            elif eng.uses_own_effect(z.key):
                e = eng.get_effect(z.key)
                uses = e.name if e else "-"
            else:
                uses = "All lights"
            text = eng.display_name(z.key, z.name if z.part else z.hw_name)
            self.tree.insert(parent, "end", iid=z.key, text=text, values=(z.lit, uses))
        # gaming devices that were found but that nothing can light (yet)
        others = eng.other_devices
        if others:
            self.tree.insert("", "end", iid="others", text=f"Found, not controllable ({len(others)})",
                             open=open_state.get("others", False), tags=("dim",))
            for d in others:
                self.tree.insert("others", "end", iid=f"other::{d['vid']:04x}:{d['pid']:04x}", text=d["name"],
                                 values=("-", "no driver"), tags=("dim",))
            self.tree.tag_configure("dim", foreground=T["muted"])
        if not self.tree.exists(self.sel):
            self.sel = GLOBAL
        self.tree.selection_set(self.sel)
        self.tree.see(self.sel)

    def _all_items(self, parent=""):
        out = []
        for iid in self.tree.get_children(parent):
            out.append(iid)
            out += self._all_items(iid)
        return out

    def on_select(self, _=None):
        sel = self.tree.selection()
        if sel and sel[0] != self.sel:
            self.sel = sel[0]
            self.refresh_details()

    def on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid != GLOBAL and self.kind(iid) not in ("others", "other"):
            self.sel = iid
            self.rename(iid)

    def rename(self, iid):
        new = simpledialog.askstring("Rename", "New name (leave empty to go back to the original):",
                                     initialvalue=self.current_name(iid), parent=self.root)
        if new is not None:
            self.engine.rename(self.rename_key(iid), new)
            self.tree_sig = None
            self.refresh_details()

    # ---------- details panel ----------
    WRAP = 600   # hint text width in the details panel

    def refresh_details(self, keep_scroll=False):
        pos = self.details_canvas.yview()[0] if keep_scroll else 0.0
        for w in self.details.winfo_children():
            w.destroy()
        kind = self.kind(self.sel)
        if kind == "global":
            ttk.Label(self.details, text="All lights", style="Head.TLabel").pack(anchor="w")
            self._tick(self.details)
            self._hint(self.details, f"The main effect. Every light set to \"{FOLLOW}\" runs it. "
                                     "To give one light its own effect, pick it in the list on the left.")
            self.effect_section(GLOBAL, follow_option=False)
        elif kind == "device":
            self.device_details()
        elif kind == "split":
            self.split_details()
        elif kind in ("others", "other"):
            self.other_details(kind)
        else:
            self.light_details()
        self._decorate(self.details)
        self.details_canvas.yview_moveto(pos)
        if keep_scroll:
            self.root.after(30, lambda: self.details_canvas.yview_moveto(pos))

    # building blocks: a section card, a two-column form, and hint text
    def _section(self, parent, title, key=None, open_=True):
        """A bordered card with a heading. With a key, clicking the heading folds it (remembered)."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=(14, 10, 14, 12))
        card.pack(fill="x", pady=(12, 0))
        head = ttk.Frame(card, style="Panel.TFrame")
        head.pack(fill="x")
        title_lbl = ttk.Label(head, text=title, style="Section.TLabel")
        title_lbl.pack(side="left")
        body = ttk.Frame(card, style="Panel.TFrame")
        if key is None:
            body.pack(fill="x", pady=(6, 0))
            return body
        arrow = ttk.Label(head, style="Fold.TLabel")
        arrow.pack(side="right")

        state = {"open": self.sections_open.get(key, open_)}

        def show(on):
            state["open"] = on
            arrow.config(text="Hide  ▲" if on else "Show  ▼")
            if on:
                body.pack(fill="x", pady=(6, 0))
            else:
                body.pack_forget()

        def clicked(_=None):
            self.sections_open[key] = not state["open"]    # only a click is remembered
            show(not state["open"])

        for w in (head, title_lbl, arrow):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", clicked)
        show(state["open"])
        return body

    def _form(self, parent):
        form = ttk.Frame(parent, style="Panel.TFrame")
        form.pack(fill="x")
        form.columnconfigure(0, minsize=200)
        form.columnconfigure(1, weight=1)
        return form

    def _field(self, form, label, hint=None):
        """One row of a form: the name on the left, a cell for the controls on the right."""
        r = form.grid_size()[1]
        ttk.Label(form, text=label, style="Form.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 12), pady=(6, 4))
        cell = ttk.Frame(form, style="Panel.TFrame")
        cell.grid(row=r, column=1, sticky="ew", pady=4)
        if hint:
            ttk.Label(form, text=hint, style="Hint.TLabel", wraplength=self.WRAP - 220, justify="left").grid(
                row=r + 1, column=1, sticky="w", pady=(0, 4))
        return cell

    def _hint(self, parent, text, wrap=None, **pack):
        pack.setdefault("anchor", "w")
        pack.setdefault("pady", (4, 0))
        lbl = ttk.Label(parent, text=text, style="Hint.TLabel", wraplength=wrap or self.WRAP, justify="left")
        lbl.pack(**pack)
        return lbl

    def title_row(self, iid, subtitle=None):
        row = ttk.Frame(self.details, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text=self.current_name(iid), style="Head.TLabel").pack(side="left")
        ttk.Button(row, text="Rename", command=lambda: self.rename(iid)).pack(side="left", padx=10)
        self._tick(self.details)
        if subtitle:
            self._hint(self.details, subtitle, pady=(0, 0))

    def device_details(self):
        dev = self.sel[5:]
        eng = self.engine
        lights = [z for z in eng.zones if z.device == dev]
        n = len(lights)
        self.title_row(self.sel, f"Device  ·  {n} light{'' if n == 1 else 's'}  ·  {sum(z.lit for z in lights)} LEDs")
        row = ttk.Frame(self.details, style="Panel.TFrame")
        row.pack(anchor="w", pady=(10, 0))
        ttk.Button(row, text="Blink to find it", command=lambda: eng.identify_lights([dev])).pack(side="left")

        def all_on(on):
            for z in lights:
                eng.set_enabled(z.key, on)
            self.tree_sig = None

        ttk.Button(row, text="All lights on", command=lambda: all_on(True)).pack(side="left", padx=6)
        ttk.Button(row, text="All lights off", command=lambda: all_on(False)).pack(side="left")
        self._hint(self.details, "To change an effect, pick one of this device's lights in the list on the left.",
                   pady=(8, 0))

        body = self._section(self.details, "Update speed")
        special = eng.device_note(dev)
        if special:
            # devices LightDeck drives itself set their own pace
            self._hint(body, special, pady=(0, 0))
            return
        how = eng.control_note(dev)
        if how:
            self._hint(body, how, pady=(0, 8))
            if eng.device_control(dev) == "none":
                return
        form = self._form(body)
        cell = self._field(form, "Updates per second")
        cur = eng.device_fps(dev)
        val = ttk.Label(cell, text=str(cur), style="Num.TLabel", width=4)

        def rate_changed(v):
            fps = int(float(v))
            eng.set_device_fps(dev, fps)
            val.config(text=str(fps))

        var = tk.DoubleVar(value=cur)
        scale = ttk.Scale(cell, from_=1, to=FPS_MAX, variable=var, command=rate_changed)
        scale.var = var
        scale.pack(side="left", fill="x", expand=True)
        val.pack(side="left", padx=(10, 0))
        if how:
            note = ("How often LightDeck sends new colors to this device. Raise it only if the device keeps up "
                    "without glitching.")
        elif eng.is_slow_device(dev):
            note = ("How often LightDeck sends new colors to this device. It uses a slow connection (I2C): too many "
                    "updates can make it glitch or flash random colors, so keep it around 5-15. Colors that don't "
                    "change are only re-sent every 2 seconds.")
        else:
            note = ("How often LightDeck sends new colors to this device. It's connected over USB and can keep up "
                    "with the full frame rate.")
        self._hint(body, note, pady=(6, 0))

    def other_details(self, kind):
        """A gaming device that was found but can't be lit: what it is and why."""
        eng = self.engine
        if kind == "others":
            ttk.Label(self.details, text="Found, not controllable", style="Head.TLabel").pack(anchor="w")
            self._tick(self.details)
            body = self._section(self.details, "What is this?")
            ttk.Label(body, wraplength=self.WRAP, style="Form.TLabel", justify="left", text=(
                "LightDeck looks for gaming devices every 30 seconds. These were found, but neither OpenRGB "
                "nor LightDeck has a driver for their lighting (or they have no RGB at all).")).pack(anchor="w")
            self._hint(body, "Devices OpenRGB supports show up in the Lights list by themselves when you plug them "
                             "in. A device without any driver can still be added the way the RK N80 was: by "
                             "recording the commands its own software sends.", pady=(8, 0))
            row = ttk.Frame(body, style="Panel.TFrame")
            row.pack(anchor="w", pady=(10, 0))
            ttk.Button(row, text="Rescan devices", command=eng.rescan).pack(side="left")
            ttk.Button(row, text="Report a device", command=self.make_report).pack(side="left", padx=8)
            self._hint(body, "\"Report a device\" makes a short list of what LightDeck sees on this PC (no personal "
                             "info), so support for a missing device can be added.", pady=(8, 0))
            return
        vid, pid = (int(x, 16) for x in self.sel.split("::")[1].split(":"))
        d = next((d for d in eng.other_devices if d["vid"] == vid and d["pid"] == pid), None)
        if d is None:
            return
        ttk.Label(self.details, text=d["name"], style="Head.TLabel").pack(anchor="w")
        self._tick(self.details)
        body = self._section(self.details, "Device info")
        form = self._form(body)
        rows = [("Maker", d["maker"]), ("USB ID", f"{vid:04x}:{pid:04x}"),
                ("Type", ", ".join(d["kinds"]) or "unknown"), ("Status", "No lighting driver")]
        for k, v in rows:
            ttk.Label(self._field(form, k), text=v, style="Form.TLabel").pack(anchor="w")
        note = d["note"] or ("Neither OpenRGB nor LightDeck knows how to control this device's lighting. "
                             "If it has RGB and comes with its own lighting software, its commands can be "
                             "recorded and added to LightDeck, like the RK N80.")
        self._hint(body, note, pady=(8, 0))
        self._capture_section(d)

    def _capture_section(self, d):
        """Record what the device's own app sends it, for a new driver (how the RK N80 was added)."""
        vid, pid, name = d["vid"], d["pid"], d["name"]
        body = self._section(self.details, "Add support for it", key="capture", open_=False)
        self._hint(body, "If this device has RGB lighting and its own lighting app, LightDeck can record what that "
                         "app sends to it. That recording is what's needed to write a driver.", pady=(0, 6))
        if not usbcapture.installed():
            self._hint(body, "This needs USBPcap, a free USB recorder. Install it from its website, restart the PC, "
                             "then come back here.", pady=(0, 6))
            ttk.Button(body, text="Open the USBPcap website",
                       command=lambda: webbrowser.open("https://desowin.org/usbpcap/")).pack(anchor="w")
            return
        steps = ("1. Plug the device in with its cable (lighting usually only works that way).\n"
                 "2. Click Start recording (Windows asks for admin).\n"
                 "3. Open the device's own lighting app and change its lighting, waiting a few seconds between "
                 "each step: all red, all blue, one key or zone green, brightness up and down, and any "
                 "music or screen mode for 10 seconds.\n"
                 "4. Click Stop and save. Only what the computer sent to this device is kept (never your key "
                 "presses); the raw recording is deleted.")
        ttk.Label(body, text=steps, style="Form.TLabel", wraplength=self.WRAP, justify="left").pack(anchor="w")
        row = ttk.Frame(body, style="Panel.TFrame")
        row.pack(anchor="w", pady=(10, 0))
        msg = ttk.Label(body, text="", style="Hint.TLabel", wraplength=self.WRAP, justify="left")
        msg.pack(anchor="w", pady=(6, 0))
        busy = self.capture is not None
        if busy and (self.capture["vid"], self.capture["pid"]) == (vid, pid):
            msg.config(text="Recording... change the lighting in the device's own app now.")

        def work_then(fn, done):
            box = {}

            def run():
                try:
                    box["ok"] = fn()
                except Exception as e:
                    box["err"] = str(e) or type(e).__name__
            t = threading.Thread(target=run, daemon=True)
            t.start()

            def check():
                if t.is_alive():
                    self.root.after(200, check)
                else:
                    done(box)
            self.root.after(200, check)

        def start():
            if self.capture is not None:
                msg.config(text="A recording is already running.")
                return
            msg.config(text="Starting the recorder (click Yes on Windows' prompt)...")

            def done(box):
                if "err" in box:
                    msg.config(text=f"Couldn't start: {box['err']}", style="Err.TLabel") if msg.winfo_exists() else None
                    return
                self.capture = {"folder": box["ok"], "vid": vid, "pid": pid, "name": name}
                if msg.winfo_exists():
                    msg.config(text="Recording... change the lighting in the device's own app now, then click "
                                    "Stop and save.", style="Hint.TLabel")
            work_then(usbcapture.start, done)

        def stop():
            cap = self.capture
            if cap is None:
                msg.config(text="Nothing is being recorded.")
                return
            self.capture = None
            msg.config(text="Stopping and keeping only this device's messages...")

            def work():
                usbcapture.stop(cap["folder"])
                text, count = usbcapture.extract(cap["folder"], cap["vid"], cap["pid"], cap["name"])
                path = report.USER_DIR / f"device-recording-{cap['vid']:04x}-{cap['pid']:04x}.txt"
                path.write_text(text, encoding="utf-8")
                return path, count

            def done(box):
                if not msg.winfo_exists():
                    return
                if "err" in box:
                    msg.config(text=f"Couldn't save the recording: {box['err']}", style="Err.TLabel")
                    return
                path, count = box["ok"]
                if not count:
                    msg.config(text="Nothing was sent to this device during the recording. Did its app change "
                                    "the lighting? Try again.", style="Err.TLabel")
                    return
                msg.config(text=f"Saved {count} messages as {path.name}. Attach it to your device report.",
                           style="Hint.TLabel")
                os.startfile(str(path.parent))
            work_then(work, done)

        ttk.Button(row, text="Start recording", command=start).pack(side="left")
        ttk.Button(row, text="Stop and save", command=stop).pack(side="left", padx=8)
        ttk.Button(row, text="Report a device", command=self.make_report).pack(side="left")

    def split_details(self):
        hw_key = self.sel[4:]
        eng = self.engine
        z = next((z for z in eng.zones if z.hw_key == hw_key), None)
        if z is None:
            return
        dev = eng.display_name(z.device, z.device)
        self.title_row(self.sel, f"{z.hw_name} on {dev}  ·  {z.hw_leds} LEDs  ·  split into {self.split_text(hw_key)}")
        row = ttk.Frame(self.details, style="Panel.TFrame")
        row.pack(anchor="w", pady=(10, 0))
        ttk.Button(row, text="Blink whole cable", command=lambda: eng.identify_lights([hw_key])).pack(side="left")
        lay = eng.layout(hw_key)
        word = ("row" if lay["order"] == "rows" else "strip") if lay else "part"
        self._hint(self.details, f"Each {word} is listed under this cable on the left. "
                                 f"Click one to give it its own effect or name.", pady=(8, 0))
        self.header_section(z)

    def split_text(self, hw_key):
        lay = self.engine.layout(hw_key)
        if lay and lay["order"] == "rows":
            rows = len({z.part for z in self.engine.zones if z.hw_key == hw_key})
            return f"{rows} key rows"
        if lay:
            return f"{lay['strips']} parallel strips"
        return f"{len(self.engine.segments(hw_key))} parts"

    def light_details(self):
        eng = self.engine
        z = self.zones_by_key().get(self.sel)
        if z is None:
            return
        dev = eng.display_name(z.device, z.device)
        if z.part is not None:
            what = {"strip": "Strip", "row": "Row"}.get(z.kind, "Part")
            sub = f"{what} {z.part} of {eng.display_name(z.hw_key, z.hw_name)} ({dev})  ·  {z.lit} LEDs"
        else:
            sub = f"{z.hw_name} on {dev}  ·  {z.lit} LEDs"
        self.title_row(z.key, sub)

        row = ttk.Frame(self.details, style="Panel.TFrame")
        row.pack(anchor="w", pady=(10, 0))
        en = tk.BooleanVar(value=eng.is_enabled(z.key))

        def toggle():
            eng.set_enabled(z.key, en.get())
            self.tree_sig = None

        ttk.Checkbutton(row, text="Light on", variable=en, command=toggle, style="Form.TCheckbutton").pack(side="left")
        ttk.Button(row, text="Blink to find it", command=lambda: eng.identify_lights([z.key])).pack(side="left", padx=14)

        self.effect_section(z.key, follow_option=True)
        if z.part is None and z.resizable:
            self.header_section(z)

    def header_section(self, z):
        """LED count + wiring test, and the two ways of splitting a cable."""
        eng = self.engine
        fixed = getattr(z, "fixed", False)

        # --- LED count ---
        body = self._section(self.details, "LED count", key="ledcount")
        form = self._form(body)
        if fixed:
            ttk.Label(self._field(form, "LEDs"), text=f"{z.hw_leds}  (set by the device)",
                      style="Form.TLabel").pack(anchor="w")
        else:
            cell = self._field(form, "LEDs on this cable")
            count = tk.StringVar(value=str(z.hw_leds))
            ttk.Spinbox(cell, from_=1, to=300, width=6, textvariable=count, font=self.ui).pack(side="left")
            ttk.Button(cell, text="Apply",
                       command=lambda: count.get().isdigit() and eng.set_led_count(z.hw_key, int(count.get()))
                       ).pack(side="left", padx=8)
        cell = self._field(form, "Check the wiring")
        ttk.Button(cell, text="Run a test dot", command=lambda: eng.show_led_order(z.hw_key)).pack(side="left")
        if fixed:
            self._hint(body, "The test dot runs through the LEDs one by one, in the order the device numbers them.")
        else:
            self._hint(body, "The test dot runs through the LEDs one by one, in the order they are wired. "
                             "Where it disappears is the real end of the strip - set that number above.")

        # --- splitting ---
        lay = eng.layout(z.hw_key)
        is_split = bool(eng.segments(z.hw_key) or lay)
        body = self._section(self.details, "Split this cable", key="split", open_=is_split)
        self._hint(body, "Cut one cable into pieces that each get their own effect and name.", pady=(0, 0))
        mode = tk.StringVar(value="strips" if lay else "parts")
        modes = ttk.Frame(body, style="Panel.TFrame")
        modes.pack(anchor="w", pady=(10, 2))
        area = ttk.Frame(body, style="Panel.TFrame")
        area.pack(fill="x")
        msg = ttk.Label(body, text="", style="Err.TLabel", font=self.ui)
        msg.pack(anchor="w")
        parts_box = ttk.Frame(area, style="Panel.TFrame")
        strips_box = ttk.Frame(area, style="Panel.TFrame")

        def show_mode():
            msg.config(text="")
            parts_box.pack_forget()
            strips_box.pack_forget()
            (parts_box if mode.get() == "parts" else strips_box).pack(fill="x")

        for value, text in (("parts", "Parts one after another"), ("strips", "Strips side by side")):
            ttk.Radiobutton(modes, text=text, value=value, variable=mode, command=show_mode,
                            style="Form.TRadiobutton").pack(side="left", padx=(0, 22))

        # parts along the cable
        self._hint(parts_box, "Like 3 fans chained on one cable: the first 20 LEDs, the next 20, and so on.",
                   pady=(0, 2))
        form = self._form(parts_box)
        cell = self._field(form, "Equal parts")
        n_parts = tk.StringVar(value=str(len(eng.segments(z.hw_key)) or 3))
        ttk.Spinbox(cell, from_=2, to=20, width=6, textvariable=n_parts, font=self.ui).pack(side="left")

        def equal():
            if not n_parts.get().isdigit() or int(n_parts.get()) < 2:
                msg.config(text="Pick 2 or more parts.")
                return
            n = min(int(n_parts.get()), z.hw_leds)
            base, extra = divmod(z.hw_leds, n)
            self.split(z, [base + (1 if i < extra else 0) for i in range(n)])

        ttk.Button(cell, text="Split equally", command=equal).pack(side="left", padx=8)
        cell = self._field(form, "Or exact sizes", hint="LEDs in each part, separated by commas - e.g. 20, 20, 20")
        parts = tk.StringVar(value=", ".join(str(s) for s in eng.segments(z.hw_key)))
        ttk.Entry(cell, textvariable=parts, width=18, font=self.ui).pack(side="left")

        def apply_parts():
            raw = [p.strip() for p in parts.get().replace(";", ",").split(",") if p.strip()]
            if not raw or not all(p.isdigit() and int(p) > 0 for p in raw):
                msg.config(text="Use whole numbers, e.g. 20, 20, 20")
                return
            sizes = [int(p) for p in raw]
            if sum(sizes) > z.hw_leds:
                msg.config(text=f"That's {sum(sizes)} LEDs, but the cable has {z.hw_leds}.")
                return
            self.split(z, sizes)

        ttk.Button(cell, text="Apply", command=apply_parts).pack(side="left", padx=8)

        # parallel strips
        self._hint(strips_box, "For several strips laid next to each other and wired as one long chain, "
                               "like a grid or a panel.", pady=(0, 2))
        lay_now = lay or {"strips": 4, "order": "across", "zigzag": False}
        form = self._form(strips_box)
        cell = self._field(form, "Number of strips")
        n_strips = tk.StringVar(value=str(lay_now["strips"]))
        ttk.Spinbox(cell, from_=2, to=30, width=6, textvariable=n_strips, font=self.ui).pack(side="left")
        orders = {"across": "Across all strips, row by row", "along": "Down one strip, then the next"}
        if z.matrix:
            orders["rows"] = "Key rows, from the device's key map"
        cell = self._field(form, "The wiring goes")
        order = ttk.Combobox(cell, values=list(orders.values()), state="readonly", width=30, font=self.ui)
        order.set(orders.get(lay_now["order"], orders["across"]))
        order.pack(side="left")
        zig = tk.BooleanVar(value=lay_now["zigzag"])
        cell = self._field(form, "Zigzag wiring")
        ttk.Checkbutton(cell, text="Every other row or strip runs backwards", variable=zig,
                        style="Form.TCheckbutton").pack(side="left")

        def apply_strips():
            key = next(k for k, v in orders.items() if v == order.get())
            if key == "rows":
                eng.set_layout(z.hw_key, len(z.matrix), "rows", False)
                self.after_split(z, True)
                return
            if not n_strips.get().isdigit() or int(n_strips.get()) < 2:
                msg.config(text="Pick 2 or more strips.")
                return
            s = int(n_strips.get())
            if s > z.hw_leds:
                msg.config(text=f"The cable only has {z.hw_leds} LEDs.")
                return
            key = next(k for k, v in orders.items() if v == order.get())
            eng.set_layout(z.hw_key, s, key, zig.get())
            self.after_split(z, True)

        ttk.Button(self._field(form, ""), text="Split into strips", command=apply_strips).pack(side="left")
        if z.matrix:
            self._hint(strips_box, "This device has a key map: pick \"Key rows\" to give every row of keys "
                                   "its own light (the number of strips is then set by the device).")
        if lay and lay["order"] != "rows" and z.hw_leds % lay["strips"]:
            self._hint(strips_box, f"{z.hw_leds} LEDs don't divide evenly into {lay['strips']} strips - "
                                   f"the last {z.hw_leds % lay['strips']} stay dark.")
        show_mode()

        if is_split:
            ttk.Button(body, text="Join back into one",
                       command=lambda: (eng.join(z.hw_key), self.after_split(z, False))).pack(anchor="w", pady=(10, 0))

    def split(self, z, sizes):
        self.engine.set_segments(z.hw_key, sizes)
        self.after_split(z, len(sizes) > 1)

    def after_split(self, z, is_split):
        # select the header (or the whole zone again) once the engine has rebuilt the lights
        self.sel = ("hw::" + z.hw_key) if is_split else z.hw_key
        self.tree_sig = None
        self.root.after(200, self.refresh_details)

    # ---------- effect section ----------
    def effect_section(self, target, follow_option):
        eng = self.engine
        body = self._section(self.details, "Effect")
        following = follow_option and not eng.uses_own_effect(target)
        names = eng.effect_names()
        form = self._form(body)
        cell = self._field(form, "Choose an effect")
        pick = ttk.Combobox(cell, values=([FOLLOW] if follow_option else []) + names, state="readonly", width=26,
                            font=self.ui)
        eff = None if following else eng.get_effect(target)
        pick.set(FOLLOW if following else (eff.name if eff else ""))
        pick.pack(side="left")

        def chosen(_=None):
            name = pick.get()
            if name == FOLLOW:
                eng.set_override(target, False)
            else:
                if follow_option:
                    eng.set_override(target, True)
                eng.set_effect(target, name)
            self.tree_sig = None
            self.refresh_details(keep_scroll=True)

        pick.bind("<<ComboboxSelected>>", chosen)
        if following:
            g = eng.get_effect(GLOBAL)
            self._hint(body, f"Running the All lights effect ({g.name if g else '-'}). "
                             "Pick an effect above to give this light its own.", pady=(6, 0))
            return
        if eff is None:
            self._hint(body, "No effects found in the effects folder.")
            return
        ttk.Button(cell, text="Reset to default",
                   command=lambda: (eng.reset_effect(target), self.refresh_details(keep_scroll=True))).pack(
            side="left", padx=8)
        if eff.description:
            self._hint(body, eff.description, pady=(6, 0))

        shown = [(k, p) for k, p in eff.params.items() if getattr(p, "visible", lambda v: True)(eff.values)]
        # settings that other settings depend on: changing them redraws the list
        self._controllers = {k for p in eff.params.values() for k in (getattr(p, "show_if", None) or {})}
        if shown:
            sbody = self._section(self.details, f"{eff.name} settings")
            form = self._form(sbody)
            for key, p in shown:
                cell = self._field(form, p.label, hint=getattr(p, "hint", None))
                self._param_widget(cell, target, key, p, eff.values[key])
        for err in eng.effect_errors:
            ttk.Label(self.details, text="⚠ " + err, style="Err.TLabel", wraplength=self.WRAP).pack(anchor="w",
                                                                                                    pady=(8, 0))

    def _set(self, target, key, value):
        eff = self.engine.get_effect(target)
        if eff is not None and key in eff.values:
            eff.values[key] = value
            if key in getattr(self, "_controllers", ()):
                self.root.after(10, lambda: self.refresh_details(keep_scroll=True))

    def _param_widget(self, cell, target, key, p, value):
        if p.kind == "number":
            is_int = float(p.step).is_integer()
            var = tk.DoubleVar(value=value)
            lbl = ttk.Label(cell, text=str(value), style="Num.TLabel", width=5)

            def changed(v, lbl=lbl):
                val = round(float(v) / p.step) * p.step
                val = int(val) if is_int else round(val, 3)
                lbl.config(text=str(val))
                self._set(target, key, val)

            scale = ttk.Scale(cell, from_=p.min, to=p.max, variable=var, command=changed)
            scale.var = var
            scale.pack(side="left", fill="x", expand=True)
            lbl.pack(side="left", padx=(10, 0))
        elif p.kind == "color":
            btn = tk.Button(cell, text=value, bg=value, fg=self._text_on(value), relief="flat", font=self.ui,
                            activebackground=value, width=12, cursor="hand2")

            def pick(btn=btn):
                cur = self.engine.get_effect(target).values.get(key, value)
                res = colorchooser.askcolor(color=cur, title=p.label, parent=self.root)
                if res and res[1]:
                    btn.config(bg=res[1], activebackground=res[1], text=res[1], fg=self._text_on(res[1]))
                    self._set(target, key, res[1])

            btn.config(command=pick)
            btn.pack(side="left")
        elif p.kind == "choice":
            cb = ttk.Combobox(cell, values=p.options, state="readonly", width=22, font=self.ui)
            cb.set(value)
            cb.bind("<<ComboboxSelected>>", lambda e, cb=cb: self._set(target, key, cb.get()))
            cb.pack(side="left")
        elif p.kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            cb = ttk.Checkbutton(cell, variable=var, style="Form.TCheckbutton",
                                 command=lambda var=var: self._set(target, key, var.get()))
            cb.var = var
            cb.pack(side="left", pady=(2, 0))
        elif p.kind == "palette":
            self._palette_editor(cell, target, key, p, list(value or p.default))

    def _palette_editor(self, box, target, key, p, colors):
        """Row of color swatches you can change, add, remove and reorder, plus presets."""
        state = {"colors": colors}
        swatches = ttk.Frame(box, style="Panel.TFrame")
        swatches.pack(fill="x")
        bar = tk.Canvas(box, height=8, bg=T["panel"], highlightthickness=0)
        bar.pack(fill="x", pady=(6, 0))
        tools = ttk.Frame(box, style="Panel.TFrame")
        tools.pack(fill="x", pady=(6, 0))

        def draw_bar():
            if not bar.winfo_exists():
                return
            bar.delete("all")
            w = max(bar.winfo_width(), 20)
            cols = state["colors"]
            steps = 80
            for k in range(steps):
                f = k / (steps - 1) * (len(cols) - 1)
                i = min(int(f), max(len(cols) - 2, 0))
                col = cols[0] if len(cols) == 1 else hud.blend(cols[i], cols[i + 1], f - i)
                bar.create_rectangle(k * w / steps, 0, (k + 1) * w / steps + 1, 8, fill=col, outline="")

        def commit():
            self._set(target, key, list(state["colors"]))
            draw()

        def edit(i):
            res = colorchooser.askcolor(color=state["colors"][i], title=f"{p.label} - color {i + 1}", parent=self.root)
            if res and res[1]:
                state["colors"][i] = res[1]
                commit()

        def remove(i):
            if len(state["colors"]) > 1:
                del state["colors"][i]
                commit()

        def move_left(i):
            if i > 0:
                c = state["colors"]
                c[i - 1], c[i] = c[i], c[i - 1]
                commit()

        def add():
            if len(state["colors"]) >= 16:
                return
            res = colorchooser.askcolor(color=state["colors"][-1], title=f"{p.label} - add a color", parent=self.root)
            if res and res[1]:
                state["colors"].append(res[1])
                commit()

        def draw():
            for w in swatches.winfo_children():
                w.destroy()
            for i, col in enumerate(state["colors"]):
                sw = tk.Label(swatches, bg=col, width=3, height=1, cursor="hand2",
                              highlightthickness=1, highlightbackground=T["border"], highlightcolor=T["accent"])
                sw.pack(side="left", padx=(0, 4))
                sw.bind("<Button-1>", lambda e, i=i: edit(i))
                sw.bind("<Shift-Button-1>", lambda e, i=i: move_left(i))
                sw.bind("<Button-3>", lambda e, i=i: remove(i))
                sw.bind("<Enter>", lambda e, sw=sw: sw.configure(highlightbackground=T["accent"]))
                sw.bind("<Leave>", lambda e, sw=sw: sw.configure(highlightbackground=T["border"]))
            plus = tk.Label(swatches, text="+", width=3, bg=T["btn_bg"], fg=T["btn_fg"], cursor="hand2",
                            font=(T["font_ui"], 10), highlightthickness=1, highlightbackground=T["border"])
            plus.pack(side="left")
            plus.bind("<Button-1>", lambda e: add())
            n = len(state["colors"])
            ttk.Label(swatches, text=f"{n} color{'' if n == 1 else 's'}", style="Hint.TLabel").pack(side="left",
                                                                                                    padx=8)
            self.root.after(10, draw_bar)

        bar.bind("<Configure>", lambda e: draw_bar())
        presets = ttk.Combobox(tools, values=list(PALETTE_PRESETS), state="readonly", width=16, font=self.ui)
        presets.set("Load a preset...")
        presets.pack(side="left")

        def load_preset(_=None):
            state["colors"] = list(PALETTE_PRESETS[presets.get()])
            presets.set("Load a preset...")
            commit()

        presets.bind("<<ComboboxSelected>>", load_preset)

        def make_vivid():
            # keep each hue, but push it to full saturation and brightness so LEDs don't look white
            out = []
            for col in state["colors"]:
                r, g, b = (int(col[k:k + 2], 16) / 255 for k in (1, 3, 5))
                h, sat, val = colorsys.rgb_to_hsv(r, g, b)
                if sat < 0.08:          # a true white/grey stays as it is
                    out.append(col)
                    continue
                r, g, b = colorsys.hsv_to_rgb(h, max(sat, 0.97), max(val, 0.9))
                out.append("#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
            state["colors"] = out
            commit()

        ttk.Button(tools, text="Make vivid", command=make_vivid).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="Click a color to change it  ·  right-click to remove it  ·  Shift+click to move it left",
                  style="Hint.TLabel").pack(anchor="w", pady=(4, 0))
        draw()

    @staticmethod
    def _text_on(hexcolor):
        h = hexcolor.lstrip("#")
        try:
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return "black"
        return "black" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "white"

    # ---------- preview ----------
    def draw_preview(self, t=0.0):
        eng = self.engine
        zones = [z for z in eng.zones if z.leds > 0]
        width = max(self.canvas.winfo_width(), 300)
        height = max(self.canvas.winfo_height(), 60)
        names = tuple(eng.light_name(z) for z in zones)
        label_w = 210
        sig = (tuple((z.key, z.leds) for z in zones), names, width, height)
        if sig != self.preview_sig:
            self.preview_sig = sig
            c = self.canvas
            c.delete("all")
            self.preview_items = {}
            top = 16
            row_h = max(14, min(22, (height - top - 4) / max(1, len(zones))))
            avail = width - label_w - 12
            max_leds = max([z.leds for z in zones] + [1])
            self.led_w = max(2, min(16, avail / max_leds))
            # LED index ruler
            for k in range(0, max_leds + 1, 10 if max_leds > 20 else 5):
                x = label_w + k * self.led_w
                c.create_line(x, top - 4, x, top - 1, fill=T["muted"])
                c.create_text(x + 1, 1, text=str(k), anchor="nw", fill=T["muted"], font=(T["font_mono"], 7))
            c.create_line(label_w, top - 1, label_w + max_leds * self.led_w, top - 1, fill=T["border"])
            for i, (z, name) in enumerate(zip(zones, names)):
                y = top + 2 + i * row_h
                if z.device in eng.cfg["names"]:
                    dev = eng.cfg["names"][z.device]
                else:
                    words = z.device.split()
                    # keep the number of numbered duplicates, e.g. "ENE 2" for "ENE DRAM 2"
                    dev = words[0] + (f" {words[-1]}" if len(words) > 1 and words[-1].isdigit() else "")
                label = f"{i:02d} {dev} · {name}"
                if len(label) > 31:
                    label = label[:30] + "…"
                c.create_text(4, y + row_h / 2 - 1, text=label, anchor="w", fill=T["muted"], font=(T["font_mono"], 8))
                items = []
                for k in range(z.leds):
                    x = label_w + k * self.led_w
                    items.append(c.create_rectangle(x, y + 2, x + self.led_w - T["led_gap"], y + row_h - 4,
                                                    outline="", fill="#000"))
                self.preview_items[z.key] = items
            self.scan_area = (label_w, max_leds * self.led_w, top, top + 2 + len(zones) * row_h)
            # scanner: a soft band and a bright line that sweep across the LEDs
            self.scan_band = c.create_rectangle(0, top, 0, self.scan_area[3], outline="",
                                                fill=hud.blend(T["panel"], T["sub"], 0.18))
            self.scan_line = c.create_line(0, top, 0, self.scan_area[3], fill=T["sub"], width=1)
        prev = eng.preview
        for key, items in self.preview_items.items():
            cols = prev.get(key)
            if not cols:
                continue
            for item, col in zip(items, cols):
                self.canvas.itemconfig(item, fill="#%02x%02x%02x" % col)
        x0, w, y0, y1 = self.scan_area
        sx = x0 + (t * 0.25 % 1.0) * w
        self.canvas.coords(self.scan_line, sx, y0, sx, y1)
        self.canvas.coords(self.scan_band, max(x0, sx - 40), y0, sx, y1)
        self.canvas.tag_lower(self.scan_band)     # glow shows between the LEDs
        self.canvas.tag_raise(self.scan_line)

    # ---------- timers ----------
    def tick_fast(self):
        t = time.perf_counter()
        self.frame_no += 1
        try:
            self.draw_preview(t)
            self.title_anim.animate(t)
            self.stripe_anim.animate(t)
            if self.frame_no % 3 == 0:
                self.telemetry.update(t)
                self.animate_status(t)
            self.animate_ticks(t)
        except tk.TclError:
            pass
        self.root.after(40, self.tick_fast)

    def animate_ticks(self, t):
        """Accent bars under headings gently pulse and stretch."""
        alive = []
        for a, b, i in self.tick_bars:
            if not a.winfo_exists():
                continue
            alive.append((a, b, i))
            phase = math.sin(t * 2.2 + i * 0.9)
            a.configure(width=int(46 + 14 * phase))
            b.configure(bg=hud.blend(T["panel"], T["btn_press"], 0.55 + 0.45 * math.sin(t * 5 + i)))
        self.tick_bars = alive

    def animate_status(self, t):
        if not self.status_text:
            return
        if T["upper"]:
            stamp = time.strftime("%H:%M:%S") + f".{int((time.time() % 1) * 1000):03d}"
            spin = "◐◓◑◒"[int(t * 6) % 4]
            self.status.config(text=f"[{stamp}] {spin} {self.status_text.upper()}")
        else:
            self.status.config(text=self.status_text)

    def tick_slow(self):
        eng = self.engine
        fps = f"  ·  {eng.actual_fps:.0f} fps" if eng.client else ""
        err = f"  ·  ⚠ {eng.last_error}" if eng.last_error else ""
        self.status_text = eng.status + fps + err
        if eng.reload_if_changed():
            self.tree_sig = None
            self.refresh_details()
        sig = (tuple((z.key, z.leds) for z in eng.zones), tuple(eng.cfg["disabled"]), tuple(eng.cfg["overrides"]),
               tuple(sorted(eng.cfg["names"].items())),
               tuple((k, e.name if e else "") for k, e in eng.effects.items()),
               tuple((d["vid"], d["pid"]) for d in eng.other_devices))
        if sig != self.tree_sig:
            structure_changed = self.tree_sig is None or self.tree_sig[0] != sig[0]
            self.tree_sig = sig
            had = self.sel
            self.rebuild_tree()
            if structure_changed or had != self.sel:
                self.refresh_details()
        self.save_timer += 1
        if self.save_timer >= 20:  # autosave every ~10 s
            self.save_timer = 0
            try:
                eng.save_config()
            except Exception:
                pass
        self.root.after(500, self.tick_slow)

    def show_welcome(self):
        """Shown the first time LightDeck runs on a PC: what to check on this setup."""
        self.bring_to_front()
        win = tk.Toplevel(self.root)
        win.title("Welcome to LightDeck")
        win.configure(bg=T["panel"])
        win.transient(self.root)
        win.resizable(False, False)
        box = ttk.Frame(win, style="Panel.TFrame", padding=22)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Welcome to LightDeck", style="Head.TLabel").pack(anchor="w")
        self._tick(box)
        tips = [
            ("Close other RGB apps", "SignalRGB, iCUE, Armoury Crate, G HUB lighting, Mystic Light, RGB Fusion, "
                                     "NZXT CAM... Only one app can drive the lights - they will fight."),
            ("Allow OpenRGB as administrator", "Windows asks when LightDeck starts it. Say Yes so RAM and some "
                                               "motherboards work. If OpenRGB warns about PawnIO, install the free "
                                               "PawnIO driver from pawnio.eu for RAM/SMBus lighting."),
            ("Set your ARGB headers", "Headers start at 60 LEDs. Click one, use \"Blink to find it\" and "
                                      "\"Run a test dot\", and set the real LED count. You can split a cable into "
                                      "parts or strips there too."),
            ("Something missing?", "Devices OpenRGB supports appear by themselves. Others are listed under "
                                   "\"Found, not controllable\". Press Rescan devices after plugging something in."),
            ("Make it yours", "Pick effects and palettes per light, switch themes at the top right, and add your "
                              "own effects in the Effects folder (see README.md)."),
        ]
        for title, text in tips:
            ttk.Label(box, text=title, style="Sub.TLabel").pack(anchor="w", pady=(10, 0))
            ttk.Label(box, text=text, style="Panel.TLabel", wraplength=480, justify="left").pack(anchor="w")
        ttk.Button(box, text="Got it", command=win.destroy).pack(anchor="e", pady=(16, 0))
        self._decorate(box)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()

    def show_settings(self):
        """App settings. Each setting is a section: a heading, a control and a short hint."""
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_force()
            return
        win = self.settings_win = tk.Toplevel(self.root)
        win.title("LightDeck settings")
        win.configure(bg=T["panel"])
        win.transient(self.root)
        win.resizable(False, False)
        box = ttk.Frame(win, style="Panel.TFrame", padding=22)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Settings", style="Head.TLabel").pack(anchor="w")
        self._tick(box)
        self._hint(box, "Options for the whole app. Settings for each light are in the main window.", wrap=460)

        # --- Startup ---
        body = self._section(box, "Startup")
        start_var = tk.BooleanVar(value=startup.is_enabled())
        msg = ttk.Label(body, text="", style="Err.TLabel", font=self.ui)

        def toggle_startup():
            try:
                start_var.set(startup.set_enabled(start_var.get()))
                msg.config(text="")
            except OSError as e:
                start_var.set(startup.is_enabled())
                msg.config(text=f"Could not change it: {e}")

        ttk.Checkbutton(body, text="Start LightDeck with Windows", variable=start_var,
                        command=toggle_startup, style="Form.TCheckbutton").pack(anchor="w")
        self._hint(body, "LightDeck opens minimized in the taskbar when you sign in to Windows, "
                         "so your lights come on by themselves.", wrap=440)
        msg.pack(anchor="w")

        self._wifi_section(box, win)

        # --- Help add a device ---
        body = self._section(box, "Help add a device")
        self._hint(body, "A device that doesn't light up? \"Report a device\" saves a short list of what LightDeck "
                         "sees on this PC (names and USB IDs only, nothing personal) and copies it, ready to paste "
                         "into a request for support.", wrap=440, pady=(0, 6))
        ttk.Button(body, text="Report a device", command=self.make_report).pack(anchor="w")

        ttk.Button(box, text="Close", command=win.destroy).pack(anchor="e", pady=(18, 0))
        self._decorate(box)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 60
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ---------- Wi-Fi lights (in Settings) ----------
    def _wifi_section(self, parent, win):
        eng = self.engine
        drivers = eng.network_drivers()
        if not drivers:
            return
        body = self._section(parent, "Wi-Fi lights")
        kinds = ", ".join(c.kind_name for c in drivers)
        self._hint(body, f"Lights on your home network: {kinds}. They must be on the same network as this PC.",
                   wrap=440, pady=(0, 6))
        added = ttk.Frame(body, style="Panel.TFrame")
        added.pack(fill="x")
        found_box = ttk.Frame(body, style="Panel.TFrame")
        msg = ttk.Label(body, text="", style="Hint.TLabel", wraplength=440, justify="left")
        state = {"sig": None}

        def say(text, error=False):
            if msg.winfo_exists():
                msg.config(text=text, style="Err.TLabel" if error else "Hint.TLabel")

        def in_background(work, done):
            """Run network work off the window's thread, then show the result."""
            box = {}

            def run():
                try:
                    box["ok"] = work()
                except Exception as e:             # shown to the user as plain text
                    box["err"] = str(e) or type(e).__name__

            t = threading.Thread(target=run, daemon=True)
            t.start()

            def check():
                if not win.winfo_exists():
                    return
                if t.is_alive():
                    win.after(150, check)
                else:
                    done(box)

            win.after(150, check)

        def draw_added():
            if not added.winfo_exists():
                return
            lights = eng.network_lights()
            sig = tuple((c.__name__, e.get("id"), st) for c, e, st in lights)
            if sig != state["sig"]:
                state["sig"] = sig
                for w in added.winfo_children():
                    w.destroy()
                if not lights:
                    ttk.Label(added, text="No Wi-Fi lights added yet.", style="Form.TLabel").pack(anchor="w")
                for cls, entry, status in lights:
                    row = ttk.Frame(added, style="Panel.TFrame")
                    row.pack(fill="x", pady=2)
                    ttk.Label(row, text=cls.label(entry), style="Form.TLabel").pack(side="left")
                    ttk.Label(row, text=f"  {cls.kind_name}  ·  {status}", style="Hint.TLabel").pack(side="left")
                    ttk.Button(row, text="Remove",
                               command=lambda c=cls, e=entry: remove(c, e)).pack(side="right")
                self._decorate(added)
            win.after(2000, draw_added)

        def remove(cls, entry):
            eng.remove_network_light(cls, entry)
            eng.save_config()
            state["sig"] = None
            say(f"Removed {cls.label(entry)}.")

        def add(cls, entry):
            hint = f" {cls.pair_hint}" if cls.needs_pairing else ""
            say(f"Adding {cls.label(entry)}...{hint}")

            def done(box):
                if "err" in box:
                    say(box["err"], error=True)
                    return
                eng.save_config()
                state["sig"] = None
                say(f"Added {cls.label(box['ok'])}. It appears in the Lights list in a few seconds.")
                for w in found_box.winfo_children():
                    w.destroy()
                found_box.pack_forget()

            in_background(lambda: eng.add_network_light(cls, entry), done)

        def search():
            say("Searching your network (a few seconds)...")

            def done(box):
                for w in found_box.winfo_children():
                    w.destroy()
                if "err" in box:
                    say(box["err"], error=True)
                    return
                found, problems = box["ok"]
                if not found:
                    say("No new lights found. " + (" ".join(problems) + " " if problems else "") +
                        "If yours is on, add it by its IP address (shown in its own app or your router).")
                    return
                found_box.pack(fill="x", pady=(8, 0), before=msg)
                ttk.Label(found_box, text="Found:", style="Form.TLabel").pack(anchor="w")
                for cls, entry in found:
                    row = ttk.Frame(found_box, style="Panel.TFrame")
                    row.pack(fill="x", pady=2)
                    ttk.Label(row, text=f"{cls.label(entry)}  ·  {cls.kind_name}", style="Form.TLabel").pack(side="left")
                    ttk.Button(row, text="Add", command=lambda c=cls, e=entry: add(c, e)).pack(side="right")
                    if cls.needs_pairing:
                        self._hint(found_box, cls.pair_hint, wrap=440, pady=(0, 4))
                self._decorate(found_box)
                say(f"Found {len(found)} new light{'s' if len(found) != 1 else ''}.")

            in_background(eng.search_network, done)

        row = ttk.Frame(body, style="Panel.TFrame")
        row.pack(anchor="w", pady=(10, 0))
        ttk.Button(row, text="Search my network", command=search).pack(side="left")

        form = self._form(body)
        cell = self._field(form, "Or add by IP address")
        by_name = {c.kind_name: c for c in drivers}
        kind = ttk.Combobox(cell, values=list(by_name), state="readonly", width=12, font=self.ui)
        kind.set(drivers[0].kind_name)
        kind.pack(side="left")
        ip = tk.StringVar()
        ttk.Entry(cell, textvariable=ip, width=15, font=self.ui).pack(side="left", padx=6)

        def add_ip():
            cls, address = by_name[kind.get()], ip.get().strip()
            if not address:
                say("Type the light's IP address, e.g. 192.168.1.40", error=True)
                return
            say(f"Checking {address}...")
            in_background(lambda: cls.probe(address), lambda box: say(box["err"], error=True) if "err" in box
                          else add(cls, box["ok"]))

        ttk.Button(cell, text="Add", command=add_ip).pack(side="left")
        tips = [f"{c.kind_name}: {c.pair_hint}" for c in drivers if c.pair_hint]
        self._hint(body, "\n".join(tips), wrap=440, pady=(6, 0))
        msg.pack(anchor="w", pady=(8, 0))
        draw_added()

    def make_report(self):
        """'Report a device': save the report, copy it, and open where to send it."""
        try:
            path, text = report.save(self.engine)
        except OSError as e:
            self.status_text = f"Could not save the report: {e}"
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        url = report.issue_url()
        if url:
            webbrowser.open(url)
            where = "The report form opened in your browser: paste the report there (Ctrl+V) and describe the device."
        else:
            os.startfile(str(path))
            where = "Send it to whoever looks after LightDeck for you."
        win = tk.Toplevel(self.root)
        win.title("Device report")
        win.configure(bg=T["panel"])
        win.transient(self.root)
        box = ttk.Frame(win, style="Panel.TFrame", padding=22)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Report ready", style="Head.TLabel").pack(anchor="w")
        self._tick(box)
        self._hint(box, f"Saved as {path.name} and copied. {where} Check it first: it only lists device names, USB "
                        f"IDs and problems.", wrap=420)
        ttk.Button(box, text="OK", command=win.destroy).pack(anchor="e", pady=(14, 0))
        self._decorate(box)

    def on_close(self):
        if self.capture is not None:          # never leave a USB recording running
            try:
                usbcapture.stop(self.capture["folder"])
            finally:
                usbcapture.discard(self.capture["folder"])
        try:
            self.engine.save_config()
        finally:
            self.engine.stop()
            self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
