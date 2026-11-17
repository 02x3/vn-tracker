"""Look & feel for VN Tracker: theme presets, fonts, and small rounded widgets for tkinter."""
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# Every palette has the same keys:
#   bg      window / overlay background      card    surfaces (tiles, cards, lists)
#   card2   hovered / pressed surface        line    hairlines, tracks, grid
#   fg      main text                        dim     secondary text
#   accent  highlight color                  accent_fg  text drawn on the accent
#   good / warn / bad  status colors
PRESETS = {
    "Sakura":   dict(bg="#fff6f9", card="#ffe9f0", card2="#ffd9e6", line="#f6d3df", fg="#5b3b4c", dim="#b48c9d",
                     accent="#ff8fb3", accent_fg="#ffffff", good="#7cc79a", warn="#f2b56b", bad="#ff6f91"),
    "Matcha":   dict(bg="#f5f8ef", card="#e8f0dc", card2="#dbe8c9", line="#d6e3c4", fg="#3f4a36", dim="#8f9c80",
                     accent="#8bbd6b", accent_fg="#ffffff", good="#5fae7a", warn="#e0b45c", bad="#e07a6f"),
    "Latte":    dict(bg="#fbf7f1", card="#f2e9dd", card2="#eadcc9", line="#e6d8c4", fg="#5a4636", dim="#a8927d",
                     accent="#d59f6c", accent_fg="#ffffff", good="#8db87a", warn="#e6b05c", bad="#d9776a"),
    "Sky":      dict(bg="#f4f9ff", card="#e3f0ff", card2="#d0e5ff", line="#cfe2f7", fg="#34495e", dim="#8aa1b9",
                     accent="#6fb2ff", accent_fg="#ffffff", good="#6cc6a0", warn="#f0b968", bad="#ff7f8f"),
    "Lavender": dict(bg="#1f1b2e", card="#2a2540", card2="#362f52", line="#3a3355", fg="#ece6ff", dim="#9a90bf",
                     accent="#c4a7ff", accent_fg="#1e1a2d", good="#9be3b5", warn="#ffd59e", bad="#ff9bb3"),
    "Midnight": dict(bg="#1a1b26", card="#24283b", card2="#2f3550", line="#2c3047", fg="#c0caf5", dim="#787c99",
                     accent="#7aa2f7", accent_fg="#16161f", good="#9ece6a", warn="#e0af68", bad="#f7768e"),
    "Mono":     dict(bg="#ffffff", card="#f4f4f5", card2="#e9e9eb", line="#e4e4e7", fg="#1f1f22", dim="#9b9ba1",
                     accent="#2b2b30", accent_fg="#fefefe", good="#4caf7d", warn="#d9a441", bad="#e0606e"),
}
DEFAULT_THEME = "Sakura"
CUSTOMIZABLE = [("accent", "Accent"), ("bg", "Background"), ("card", "Surface"), ("fg", "Text"),
                ("dim", "Soft text"), ("good", "Finished / goal"), ("warn", "On hold / warning"),
                ("bad", "Dropped")]
FONT_CHOICES = ["Yu Gothic UI", "UD デジタル 教科書体 NK-R", "Meiryo UI", "Noto Sans JP", "BIZ UDPゴシック", "Segoe UI"]
# Extra families that look nice for big numbers (only the installed ones are offered).
NUMBER_FONT_CHOICES = ["Segoe UI", "Bahnschrift", "Consolas", "Cascadia Mono", "Georgia", "Trebuchet MS",
                       "Verdana", "Calibri", "Comic Sans MS"]

# ---- look options (stored in config.json; see UI_CONTRACT.md)
UI_SCALES = [(0.9, "Small"), (1.0, "Normal"), (1.15, "Large"), (1.3, "Extra large")]
CORNER_STYLES = {"round": 1.0, "soft": 0.5, "sharp": 0.15}   # radius multipliers
CORNER_LABELS = [("round", "Round"), ("soft", "Soft"), ("sharp", "Sharp")]
OVERLAY_SIZES = {"small": 0.75, "normal": 1.0, "large": 1.3}  # big overlay number + cover
OVERLAY_SIZE_LABELS = [("small", "Small"), ("normal", "Normal"), ("large", "Large")]
CUTE_SYMBOLS = ["✿", "❀", "✦", "★", "♡", "♪"]  # BMP only (Tk 8.6 can't draw emoji)
NUMBER_FORMATS = [("comma", "12,345"), ("dot", "12.345"), ("space", "12 345"), ("man", "1.2万")]
MIN_RADIUS = 3

_STYLE = {"corner": 1.0}


def set_corner_style(name) -> None:
    """Sets the radius multiplier used by Card / Pill / Switch / covers (called on load and on theme change)."""
    _STYLE["corner"] = CORNER_STYLES.get(name, 1.0)


def rad(r: float) -> float:
    """A corner radius scaled by the chosen corner style; never below MIN_RADIUS unless r itself is smaller."""
    m = _STYLE["corner"]
    if m >= 1.0:
        return r
    return max(min(r, MIN_RADIUS), r * m)


def scale_value(cfg: dict) -> float:
    """cfg['ui_scale'] snapped to the nearest allowed text scale."""
    try:
        v = float(cfg.get("ui_scale", 1.0))
    except (TypeError, ValueError):
        v = 1.0
    return min((s for s, _ in UI_SCALES), key=lambda s: abs(s - v))


def cute_symbol(cfg: dict) -> str:
    s = cfg.get("cute_symbol")
    return s if s in CUTE_SYMBOLS else CUTE_SYMBOLS[0]
TRANSPARENT = "#fe01fd"  # color keyed out of the overlay window to get rounded corners

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def mix(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb colors; t=0 gives a, t=1 gives b."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def luminance(c: str) -> float:
    c = c.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def palette(cfg: dict) -> dict:
    """The active colors: a preset plus any custom colors the user picked."""
    p = dict(PRESETS.get(cfg.get("theme"), PRESETS[DEFAULT_THEME]))
    custom = {k: v for k, v in (cfg.get("theme_custom") or {}).items()
              if k in p and isinstance(v, str) and _HEX.match(v)}
    if custom:
        p.update(custom)
        # keep the derived colors consistent with what was customized
        p["card2"] = mix(p["card"], p["accent"], 0.18)
        p["line"] = mix(p["bg"], p["dim"], 0.3)
        p["accent_fg"] = "#ffffff" if luminance(p["accent"]) < 0.62 else mix(p["fg"], "#000000", 0.3)
    return p


def is_dark(p: dict) -> bool:
    return luminance(p["bg"]) < 0.4


class Fonts(dict):
    """Named fonts, so changing the family updates every widget at once."""
    SIZES = {"xs": (8, "normal"), "sm": (9, "normal"), "md": (10, "normal"), "mdb": (10, "bold"),
             "lg": (13, "bold"), "xl": (24, "bold"), "h1": (17, "bold"),
             # big numbers: use the number font. ov_num is the overlay's count (also scaled by overlay_size).
             "xl_num": (24, "bold"), "lg_num": (13, "bold"), "ov_num": (24, "bold")}
    NUMBER_FONTS = ("xl_num", "lg_num", "ov_num")

    def __init__(self, root, family: str | None, cfg: dict | None = None):
        super().__init__()
        self.root = root
        self._cfg = {}
        for name, (size, weight) in self.SIZES.items():
            self[name] = tkfont.Font(root=root, family="TkDefaultFont", size=size, weight=weight)
        self.update_from({**(cfg or {}), "font": (cfg or {}).get("font", family) or family})

    def resolve(self, family: str | None) -> str:
        installed = set(tkfont.families(self.root))
        for f in (family, *FONT_CHOICES):
            if f and f in installed:
                return f
        return "TkDefaultFont"

    def update_from(self, cfg: dict) -> None:
        """(Re)configure every named font from the look keys: font, number_font, ui_scale, overlay_size."""
        self._cfg = dict(cfg)
        fam = self.resolve(cfg.get("font"))
        nf = cfg.get("number_font")
        num_fam = nf if nf and nf in set(tkfont.families(self.root)) else fam
        scale = scale_value(cfg)
        ov = OVERLAY_SIZES.get(cfg.get("overlay_size"), 1.0)
        for name, (size, weight) in self.SIZES.items():
            s = scale * (ov if name == "ov_num" else 1.0)
            self[name].configure(family=num_fam if name in self.NUMBER_FONTS else fam,
                                 size=max(6, round(size * s)), weight=weight)

    def set_family(self, family: str | None) -> None:
        self.update_from({**self._cfg, "font": family})

    def available(self) -> list[str]:
        installed = set(tkfont.families(self.root))
        return [f for f in FONT_CHOICES if f in installed]

    def available_numbers(self) -> list[str]:
        installed = set(tkfont.families(self.root))
        return [f for f in dict.fromkeys(FONT_CHOICES + NUMBER_FONT_CHOICES) if f in installed]


def rounded_rect(canvas: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 1:  # smooth=True on a square polygon looks like a blob; draw plain
        return canvas.create_rectangle(x0, y0, x1, y1, **{k: v for k, v in kw.items() if k != "smooth"})
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


def rounded_image(img, radius: int):
    """PIL image with rounded, anti-aliased (transparent) corners."""
    from PIL import Image, ImageDraw
    w, h = img.size
    mask = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius * 3, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize((w, h), Image.LANCZOS))
    return out


def _parent_bg(widget) -> str:
    try:
        return widget.cget("bg")
    except tk.TclError:
        return "#ffffff"


class Card(tk.Canvas):
    """A rounded surface. Put children in `.body`. Height follows the content; width either
    follows the content (stretch=False) or fills the space it's packed into (stretch=True)."""

    def __init__(self, parent, P, fill="card", outline=None, radius=14, pad=12, stretch=True,
                 width=None, height=None):
        super().__init__(parent, bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         width=width or 10, height=height or 10)
        self.P, self.fill_key, self.outline_key = P, fill, outline
        self.r, self.pad, self.stretch = radius, pad, stretch
        self.fixed_w, self.fixed_h = width, height
        self.body = tk.Frame(self, bg=P[fill])
        self._win = self.create_window(pad, pad, window=self.body, anchor="nw")
        self.bind("<Configure>", self._on_canvas)
        self.body.bind("<Configure>", self._on_body)
        self.body.bind("<Map>", self._on_body)  # with stretch=False the body may never get a Configure
        self.after_idle(self._on_body)

    def _on_body(self, _=None):
        if not self.winfo_exists():
            return
        kw = {}
        h = self.body.winfo_reqheight() + 2 * self.pad
        if not self.fixed_h and int(self.cget("height")) != h:
            kw["height"] = h
        if not self.stretch and not self.fixed_w:
            w = self.body.winfo_reqwidth() + 2 * self.pad
            if int(self.cget("width")) != w:
                kw["width"] = w
        if kw:
            self.configure(**kw)

    def _on_canvas(self, e):
        self.delete("bg")
        line = self.P[self.outline_key] if self.outline_key else self.P[self.fill_key]
        rounded_rect(self, 1, 1, e.width - 2, e.height - 2, rad(self.r), fill=self.P[self.fill_key],
                     outline=line, width=1, tags="bg")
        self.tag_lower("bg")
        if self.stretch:
            self.itemconfigure(self._win, width=max(1, e.width - 2 * self.pad))
        if self.fixed_h:
            self.itemconfigure(self._win, height=max(1, e.height - 2 * self.pad))
        self.after_idle(self._on_body)  # re-measure: covers cards created before their content was sized

    def set_fill(self, key: str):
        self.fill_key = key
        self.body.configure(bg=self.P[key])
        self.event_generate("<Configure>", width=self.winfo_width(), height=self.winfo_height())


class Pill(tk.Canvas):
    """Rounded button. kind: accent | soft | ghost | chip (chip = small colored label, not clickable)."""

    def __init__(self, parent, P, F, text, command=None, kind="soft", font="sm", padx=14, pady=5,
                 color=None, selected=False):
        self.P, self.text, self.command, self.kind = P, text, command, kind
        self.color, self.selected, self.hover = color, selected, False
        self.font = F[font]
        w = self.font.measure(text) + 2 * padx
        h = self.font.metrics("linespace") + 2 * pady
        super().__init__(parent, width=w, height=h, bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2" if command else "")
        self.w, self.h = w, h
        self._draw()
        if command:
            self.bind("<Enter>", lambda e: self._set_hover(True))
            self.bind("<Leave>", lambda e: self._set_hover(False))
            self.bind("<ButtonRelease-1>", lambda e: self.command())

    def _colors(self):
        P = self.P
        if self.kind == "chip":
            c = self.color or P["accent"]
            return mix(c, P["card"], 0.78), mix(c, P["fg"], 0.25)
        if self.kind == "accent" or self.selected:
            return (mix(P["accent"], P["fg"], 0.12) if self.hover else P["accent"]), P["accent_fg"]
        if self.kind == "ghost":
            return (P["card"] if self.hover else _parent_bg(self.master)), (P["fg"] if self.hover else P["dim"])
        return (P["card2"] if self.hover else P["card"]), P["fg"]

    def _draw(self):
        self.delete("all")
        fill, fg = self._colors()
        rounded_rect(self, 0, 0, self.w - 1, self.h - 1, rad(self.h / 2), fill=fill, outline=fill)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def set_selected(self, on: bool):
        self.selected = on
        self._draw()


class Switch(tk.Canvas):
    """A little on/off toggle."""

    def __init__(self, parent, P, value: bool, command=None):
        super().__init__(parent, width=40, height=22, bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.P, self.value, self.command = P, bool(value), command
        self._draw()
        self.bind("<ButtonRelease-1>", self._toggle)

    def _draw(self):
        self.delete("all")
        P = self.P
        track = P["accent"] if self.value else P["line"]
        rounded_rect(self, 1, 1, 39, 21, rad(10), fill=track, outline=track)
        x = 29 if self.value else 11
        knob = P["accent_fg"] if self.value else P["card"]
        if _STYLE["corner"] >= 1.0:
            self.create_oval(x - 8, 3, x + 8, 19, fill=knob, outline=mix(track, P["fg"], 0.08))
        else:  # the knob follows the track's corners
            rounded_rect(self, x - 8, 3, x + 8, 19, rad(8), fill=knob, outline=mix(track, P["fg"], 0.08))

    def _toggle(self, _=None):
        self.value = not self.value
        self._draw()
        if self.command:
            self.command(self.value)


class ScrollFrame(tk.Frame):
    """A vertically scrollable area; put children in `.inner`."""

    def __init__(self, parent, P, **kw):
        super().__init__(parent, bg=P["bg"], **kw)
        self.canvas = tk.Canvas(self, bg=P["bg"], highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.inner = tk.Frame(self.canvas, bg=P["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.bind_all_wheel(self.canvas)

    def bind_all_wheel(self, widget):
        def wheel(e):
            try:
                self.canvas.yview_scroll(int(-e.delta / 120), "units")
            except tk.TclError:  # window was closed while the wheel binding was still active
                try:
                    widget.unbind_all("<MouseWheel>")
                except tk.TclError:
                    pass

        widget.bind("<Enter>", lambda e: widget.bind_all("<MouseWheel>", wheel))
        widget.bind("<Leave>", lambda e: widget.unbind_all("<MouseWheel>"))


def style_ttk(root, P, F) -> ttk.Style:
    """Flat, palette-colored ttk widgets (lists, scrollbars, dropdowns, sliders)."""
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=P["bg"], foreground=P["fg"], fieldbackground=P["card"], bordercolor=P["line"],
                lightcolor=P["card"], darkcolor=P["card"], troughcolor=P["bg"], focuscolor=P["accent"],
                selectbackground=P["accent"], selectforeground=P["accent_fg"], font=F["sm"])
    rowh = int(F["sm"].metrics("linespace") * 2)
    s.configure("Treeview", background=P["card"], fieldbackground=P["card"], foreground=P["fg"], rowheight=rowh,
                borderwidth=0, font=F["sm"])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview.Heading", background=P["card"], foreground=P["dim"], relief="flat", borderwidth=0,
                font=F["xs"], padding=(6, 6))
    s.map("Treeview.Heading", background=[("active", P["card2"])])
    s.map("Treeview", background=[("selected", P["accent"])], foreground=[("selected", P["accent_fg"])])
    s.configure("Vertical.TScrollbar", gripcount=0, background=P["card2"], troughcolor=P["bg"], bordercolor=P["bg"],
                lightcolor=P["card2"], darkcolor=P["card2"], arrowcolor=P["dim"], arrowsize=11, relief="flat")
    s.map("Vertical.TScrollbar", background=[("active", P["line"])])
    s.configure("TCombobox", fieldbackground=P["card"], background=P["card"], foreground=P["fg"],
                arrowcolor=P["dim"], bordercolor=P["line"], padding=4)
    s.map("TCombobox", fieldbackground=[("readonly", P["card"])], foreground=[("readonly", P["fg"])],
          selectbackground=[("readonly", P["card"])], selectforeground=[("readonly", P["fg"])])
    s.configure("TEntry", fieldbackground=P["card"], foreground=P["fg"], bordercolor=P["line"],
                insertcolor=P["fg"], padding=6)
    s.configure("Horizontal.TScale", background=P["accent"], troughcolor=P["line"], bordercolor=P["bg"],
                lightcolor=P["accent"], darkcolor=P["accent"])
    root.option_add("*TCombobox*Listbox.background", P["card"])
    root.option_add("*TCombobox*Listbox.foreground", P["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", P["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", P["accent_fg"])
    return s
