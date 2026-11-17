"""Settings window: look / overlay / stats / reading / text & games, plus reset buttons. Applies changes live."""
import copy
import time
import tkinter as tk
from tkinter import ttk
from tkinter import colorchooser
from tkinter import messagebox

import ui_theme
from ui_theme import Card, Pill, Switch, ScrollFrame, rounded_rect, mix

MAX_H = 820
WIDTH = 520

# Keys "Reset look to defaults" puts back (look + overlay + stats options). Reading data is never touched.
LOOK_KEYS = [
    "theme", "theme_custom", "font", "ui_scale", "corner_style", "number_font", "number_format",
    "cute", "cute_symbol", "blur_nsfw_covers",
    "overlay_compact", "overlay_cover", "overlay_alpha", "overlay_main", "overlay_unit", "overlay_size",
    "overlay_show_title", "overlay_show_sub", "overlay_show_session", "overlay_show_goal",
    "stats_default_page", "library_card_size", "chart_days", "library_sort",
]
# "Reset all settings" resets every other key too, but keeps these (the user's own lists and links).
KEEP_ON_RESET_ALL = [
    "ocr_region", "ocr_region_spec", "discord_client_id", "locked_game", "vndb_user", "vndb_username", "vndb_last_sync", "vndb_deleted", "vndb_token",
    "overlay_x", "overlay_y", "ignored_processes", "passthrough_processes",
]
KEPT_TEXT = ("Your reading data, library, sessions, VNDB link, text boxes and ignored programs are kept.")


def reset_config(app, keys):
    """Puts `keys` back to DEFAULT_CONFIG (deep copies), saves, and restyles everything. Returns the keys reset."""
    defaults = app.lib.DEFAULT_CONFIG
    changed = []
    for k in keys:
        if k in defaults:
            app.cfg[k] = copy.deepcopy(defaults[k])
            changed.append(k)
    app.save_config()
    if "text_source" in changed:
        app.set_text_source(app.cfg["text_source"])
    if "hotkeys" in changed or "hotkeys_enabled" in changed:
        app.apply_hotkeys()
    if any(k.startswith("discord_") for k in changed):
        app.apply_discord()
    app.root.after_idle(app.apply_theme)  # also re-applies number format, corners, fonts, opacity
    return changed


class SoftPill(Pill):
    """A Pill that stays visible on a Card (the stock 'soft' pill is the same color as a card)."""

    def _colors(self):
        P = self.P
        if self.kind == "soft" and not self.selected:
            return (mix(P["card2"], P["accent"], 0.25) if self.hover else P["card2"]), P["fg"]
        return super()._colors()


class DangerPill(Pill):
    """A quiet pill that turns red on hover, for destructive-ish actions."""

    def _colors(self):
        P = self.P
        if self.hover:
            return mix(P["bad"], P["bg"], 0.82), P["bad"]
        return mix(P["bad"], P["bg"], 0.92), mix(P["bad"], P["fg"], 0.2)


def open_settings(app, geometry=None, state=None, into=None):
    """Opens the settings window. With `into` (an existing settings window), rebuilds its contents in
    place instead, which is how theme changes restyle it without closing it."""
    old = app.windows.get("settings")
    try:
        if into is None and old is not None and old.winfo_exists():
            old.deiconify()
            old.lift()
            old.focus_force()
            return old
    except tk.TclError:
        pass

    P, F, cfg, root = app.P, app.F, app.cfg, app.root
    state = dict(state or {})
    saved_scroll = state.get("scroll") or 0.0
    if into is not None:
        win = into
        for child in win.winfo_children():
            child.destroy()
        win.unbind("<MouseWheel>")
        win.ui_state = state
        win.configure(bg=P["bg"])
    else:
        win = tk.Toplevel(root)
        win.attributes("-alpha", 0.0)  # invisible while it lays out (a withdrawn window never sizes its cards)
        win.geometry(geometry or f"{WIDTH}x600")
        app.windows["settings"] = win
        win.ui_state = state
        win.title("settings")
        win.configure(bg=P["bg"])
        win.attributes("-topmost", True)
        win.minsize(420, 260)

        def on_destroy(e):
            if e.widget is win and app.windows.get("settings") is win:
                app.windows.pop("settings", None)

        win.bind("<Destroy>", on_destroy, add="+")

    sf = ScrollFrame(win, P)
    sf.pack(fill="both", expand=True)
    body = tk.Frame(sf.inner, bg=P["bg"])
    body.pack(fill="x", padx=16, pady=(14, 16))

    def save():
        app.save_config()

    def restyle():
        root.after_idle(app.apply_theme)

    # ---- header
    head = tk.Frame(body, bg=P["bg"])
    head.pack(fill="x", pady=(0, 10))
    tk.Label(head, text="settings" + app.mark(), bg=P["bg"], fg=P["fg"],
             font=F["h1"]).pack(side="left")
    Pill(head, P, F, "Done", win.destroy, kind="accent", font="md", padx=18, pady=5).pack(side="right")

    cards = []

    def section(title):
        tk.Label(body, text=title, bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w").pack(
            fill="x", padx=6, pady=(10, 3))
        c = Card(body, P, radius=16, pad=14, stretch=True)
        c.pack(fill="x")
        cards.append(c)
        return c.body

    def row(parent, label, pady=4):
        f = tk.Frame(parent, bg=P["card"])
        f.pack(fill="x", pady=pady)
        tk.Label(f, text=label, bg=P["card"], fg=P["fg"], font=F["md"], anchor="w").pack(side="left")
        return f

    def divider(parent):
        tk.Frame(parent, bg=P["line"], height=1).pack(fill="x", pady=(8, 3))

    def switch_row(parent, label, key, default, after=None):
        r = row(parent, label, pady=5)
        sw = Switch(r, P, bool(cfg.get(key, default)))

        def cmd(v):
            cfg[key] = bool(v)
            save()
            if after:
                after()

        sw.command = cmd
        sw.pack(side="right")
        return sw

    def seg_row(parent, label, key, options, current, stack=False, after=None, pady=5):
        """A row of SoftPills (one choice). options: [(value, label)]. Saves cfg[key] and restyles on click."""
        if stack:
            tk.Label(parent, text=label, bg=P["card"], fg=P["fg"], font=F["md"], anchor="w").pack(
                fill="x", pady=(pady, 2))
            seg = tk.Frame(parent, bg=P["card"])
            seg.pack(fill="x", pady=(0, pady))
            side = "left"
        else:
            r = row(parent, label, pady=pady)
            seg = tk.Frame(r, bg=P["card"])
            seg.pack(side="right")
            side = "left"
        pills = {}

        def choose(val):
            for k, p in pills.items():
                p.set_selected(k == val)
            cfg[key] = val
            save()
            (after or restyle)()

        for val, text in options:
            p = SoftPill(seg, P, F, text, lambda v=val: choose(v), selected=(val == current), padx=10)
            p.pack(side=side, padx=(0 if stack else 2, 4 if stack else 2))
            pills[val] = p
        setattr(win, "choose_" + key, choose)
        return pills

    # =================================================================== Look
    look = section("look")

    cur_theme = cfg.get("theme") or ui_theme.DEFAULT_THEME
    grid = tk.Frame(look, bg=P["card"])
    grid.pack(fill="x")
    swatches = {}

    def pick_theme(name):
        cfg["theme"] = name
        cfg["theme_custom"] = {}
        save()
        restyle()

    def draw_swatch(cv, name, selected):
        p = ui_theme.PRESETS[name]
        cv.delete("all")
        rounded_rect(cv, 2, 2, 102, 64, ui_theme.rad(12), fill=p["bg"],
                     outline=P["accent"] if selected else p["line"], width=2 if selected else 1)
        rounded_rect(cv, 10, 10, 94, 30, ui_theme.rad(7), fill=p["card"], outline=p["card"])
        cv.create_oval(16, 16, 24, 24, fill=p["accent"], outline=p["accent"])
        cv.create_rectangle(30, 18, 70, 22, fill=p["line"], outline=p["line"])
        cv.create_text(52, 48, text=name, fill=p["fg"], font=F["sm"])

    for i, name in enumerate(ui_theme.PRESETS):
        cv = tk.Canvas(grid, width=104, height=66, bg=P["card"], highlightthickness=0, bd=0, cursor="hand2")
        cv.grid(row=i // 4, column=i % 4, padx=3, pady=3)
        draw_swatch(cv, name, name == cur_theme)
        cv.bind("<ButtonRelease-1>", lambda e, n=name: pick_theme(n))
        swatches[name] = cv
    win.pick_theme = pick_theme

    tk.Label(look, text="customize colors", bg=P["card"], fg=P["dim"], font=F["sm"], anchor="w").pack(
        fill="x", pady=(10, 4))
    chips = tk.Frame(look, bg=P["card"])
    chips.pack(fill="x")

    def pick_color(key):
        cur = P[key]
        res = colorchooser.askcolor(color=cur, parent=win, title="Pick a color")
        hexv = res[1] if res else None
        if not hexv:
            return
        cfg.setdefault("theme_custom", {})
        if not isinstance(cfg["theme_custom"], dict):
            cfg["theme_custom"] = {}
        cfg["theme_custom"][key] = hexv
        save()
        restyle()

    for i, (key, label) in enumerate(ui_theme.CUSTOMIZABLE):
        chips.columnconfigure(i % 4, weight=1, uniform="chip")
        f = tk.Frame(chips, bg=P["card"])
        f.grid(row=i // 4, column=i % 4, sticky="n", pady=(0, 6))
        cv = tk.Canvas(f, width=30, height=30, bg=P["card"], highlightthickness=0, bd=0, cursor="hand2")
        cv.pack()
        cv.create_oval(2, 2, 28, 28, fill=P[key], outline=mix(P[key], P["fg"], 0.25), width=1)
        cv.bind("<ButtonRelease-1>", lambda e, k=key: pick_color(k))
        tk.Label(f, text=label, bg=P["card"], fg=P["dim"], font=F["xs"], wraplength=100, justify="center").pack(
            pady=(2, 0))
    win.pick_color = pick_color

    def reset_colors():
        cfg["theme_custom"] = {}
        save()
        restyle()

    bar = tk.Frame(look, bg=P["card"])
    bar.pack(fill="x", pady=(4, 0))
    Pill(bar, P, F, "Reset colors", reset_colors, kind="ghost").pack(side="left")

    divider(look)

    # text size
    seg_row(look, "Text size", "ui_scale", [(s, t) for s, t in ui_theme.UI_SCALES], ui_theme.scale_value(cfg))
    # corners
    seg_row(look, "Corners", "corner_style", ui_theme.CORNER_LABELS, cfg.get("corner_style", "round"))

    # fonts
    frow = row(look, "Font", pady=(8, 2))
    fonts = app.F.available()
    fv = tk.StringVar(value=cfg.get("font") if cfg.get("font") in fonts else (fonts[0] if fonts else ""))
    cb = ttk.Combobox(frow, textvariable=fv, values=fonts, state="readonly", width=24, font=F["md"])
    cb.pack(side="right")

    def on_font(_=None):
        if fv.get() and fv.get() != cfg.get("font"):
            cfg["font"] = fv.get()
            save()
            restyle()

    cb.bind("<<ComboboxSelected>>", on_font)
    win.on_font = on_font

    same = "Same as text font"
    nrow = row(look, "Number font", pady=(6, 2))
    nfonts = [same] + app.F.available_numbers()
    nv = tk.StringVar(value=cfg.get("number_font") if cfg.get("number_font") in nfonts else same)
    ncb = ttk.Combobox(nrow, textvariable=nv, values=nfonts, state="readonly", width=24, font=F["md"])
    ncb.pack(side="right")

    def on_number_font(_=None):
        val = "" if nv.get() == same else nv.get()
        if val != (cfg.get("number_font") or ""):
            cfg["number_font"] = val
            save()
            restyle()

    ncb.bind("<<ComboboxSelected>>", on_number_font)
    win.on_number_font = on_number_font

    seg_row(look, "Number format", "number_format", ui_theme.NUMBER_FORMATS, cfg.get("number_format", "comma"),
            pady=(8))

    divider(look)
    switch_row(look, "Cute extras (kaomoji, symbols, ♡)", "cute", True, restyle)
    seg_row(look, "Cute symbol", "cute_symbol", [(s, s) for s in ui_theme.CUTE_SYMBOLS],
            ui_theme.cute_symbol(cfg))
    switch_row(look, "Blur explicit covers", "blur_nsfw_covers", True, restyle)

    def do_reset_look():
        if messagebox.askyesno("Reset look to defaults",
                               "Put the theme, colors, fonts, text size, corners, number format, cute extras, "
                               "overlay options and stats options back to their defaults?\n\n" + KEPT_TEXT,
                               icon="warning", parent=win):
            reset_config(app, LOOK_KEYS)
            return True
        return False

    win.reset_look = do_reset_look
    divider(look)
    bar2 = tk.Frame(look, bg=P["card"])
    bar2.pack(fill="x", pady=(4, 0))
    SoftPill(bar2, P, F, "Reset look to defaults", do_reset_look).pack(side="left")

    # =================================================================== Overlay
    ovs = section("overlay")
    seg_row(ovs, "Big number", "overlay_main", [("today", "Today"), ("session", "Session"), ("total", "Total")],
            cfg.get("overlay_main", "today"))
    seg_row(ovs, "Label", "overlay_unit", [("字", "字"), ("chars", "chars"), ("none", "none")],
            cfg.get("overlay_unit", "字"))
    seg_row(ovs, "Size", "overlay_size", ui_theme.OVERLAY_SIZE_LABELS, cfg.get("overlay_size", "normal"))
    divider(ovs)
    switch_row(ovs, "Compact overlay", "overlay_compact", False, restyle)
    switch_row(ovs, "Cover", "overlay_cover", True, restyle)
    switch_row(ovs, "Game title", "overlay_show_title", True, restyle)
    switch_row(ovs, "Time · speed line", "overlay_show_sub", True, restyle)
    switch_row(ovs, "Session / today figure", "overlay_show_session", True, restyle)
    switch_row(ovs, "Daily goal bar", "overlay_show_goal", True, restyle)

    # opacity
    orow = row(ovs, "Opacity", pady=(8, 2))
    ov = tk.DoubleVar(value=float(cfg.get("overlay_alpha", 0.95)))
    app.style.configure("Soft.Horizontal.TScale", background=P["accent"], troughcolor=P["card2"],
                        bordercolor=P["card"], lightcolor=P["accent"], darkcolor=P["accent"],
                        sliderlength=22, sliderrelief="flat", borderwidth=0, gripcount=0)
    app.style.map("Soft.Horizontal.TScale", background=[("active", mix(P["accent"], P["fg"], 0.12))])
    sc = ttk.Scale(orow, from_=0.3, to=1.0, variable=ov, length=190, style="Soft.Horizontal.TScale")
    sc.pack(side="right")

    def live_alpha(_=None):
        try:
            root.attributes("-alpha", round(ov.get(), 2))
        except tk.TclError:
            pass

    def save_alpha(_=None):
        cfg["overlay_alpha"] = round(ov.get(), 2)
        live_alpha()
        save()

    sc.configure(command=live_alpha)
    sc.bind("<ButtonRelease-1>", save_alpha)

    # =================================================================== Stats
    st = section("stats")
    seg_row(st, "Opens on", "stats_default_page",
            [("library", "Library"), ("days", "Days"), ("sessions", "Sessions"), ("lines", "Lines")],
            cfg.get("stats_default_page", "library"))
    seg_row(st, "Library cards", "library_card_size", [("small", "Small"), ("medium", "Medium"), ("large", "Large")],
            cfg.get("library_card_size", "medium"))
    seg_row(st, "Days chart", "chart_days", [(n, f"{n} days") for n in (14, 30, 60, 90)],
            cfg.get("chart_days", 30))

    # =================================================================== Reading
    rd = section("reading")
    fields = [
        ("afk_seconds", "AFK timeout (seconds)", 5, 3600, 60),
        ("day_start_hour", "New day starts at (hour)", 0, 12, 4),
        ("daily_goal", "Daily goal (0 = off)", 0, 1_000_000, 0),
        ("weekly_goal", "Weekly goal (0 = off)", 0, 10_000_000, 0),
        ("session_gap_minutes", "Session ends after idle (minutes)", 5, 240, 30),
    ]

    def spin_row(key, label, lo, hi, default):
        r = row(rd, label, pady=4)
        v = tk.StringVar(value=str(cfg.get(key, default)))
        sp = tk.Spinbox(r, from_=lo, to=hi, textvariable=v, width=8, justify="right", font=F["md"],
                        bg=P["bg"], fg=P["fg"], insertbackground=P["fg"], relief="flat", bd=0,
                        buttonbackground=P["card2"], highlightthickness=1, highlightbackground=P["line"],
                        highlightcolor=P["accent"], disabledbackground=P["bg"],
                        selectbackground=P["accent"], selectforeground=P["accent_fg"])
        sp.pack(side="right", ipady=3)

        def parse():
            try:
                return max(lo, min(hi, int(float(v.get()))))
            except ValueError:
                return None

        def store(rewrite):
            n = parse()
            if n is None:
                if rewrite:
                    v.set(str(cfg.get(key, default)))
                return
            if rewrite:
                v.set(str(n))
            if cfg.get(key) != n:
                cfg[key] = n
                save()
                app.refresh()

        sp.configure(command=lambda: store(True))
        sp.bind("<Return>", lambda e: store(True))
        sp.bind("<FocusOut>", lambda e: store(True))
        v.trace_add("write", lambda *_: store(False))
        return sp

    for f_ in fields:
        sp_ = spin_row(*f_)
        if f_[0] == "weekly_goal":
            sp_.configure(increment=5000)
    seg_row(rd, "Week starts on", "week_starts", [("monday", "Monday"), ("sunday", "Sunday")],
            cfg.get("week_starts", "monday"), after=app.data_changed)
    seg_row(rd, "Overlay goal bar", "overlay_goal_mode", [("daily", "Daily"), ("weekly", "Weekly"), ("both", "Both")],
            cfg.get("overlay_goal_mode", "daily"), after=app.data_changed)

    # =================================================================== Text & games
    tg = section("text & games")
    srow = row(tg, "read text from", pady=(2, 6))
    seg = tk.Frame(srow, bg=P["card"])
    seg.pack(side="right")
    cur_src = cfg.get("text_source", "ocr")
    seg_pills = {}

    def set_src(val):
        for k, p in seg_pills.items():
            p.set_selected(k == val)
        cfg["text_source"] = val
        app.set_text_source(val)

    for val, label in [("ocr", "OCR"), ("clipboard", "Clipboard"), ("both", "Both")]:
        p = SoftPill(seg, P, F, label, lambda v=val: set_src(v), selected=(val == cur_src), padx=12)
        p.pack(side="left", padx=2)
        seg_pills[val] = p
    win.set_src = set_src

    brow = tk.Frame(tg, bg=P["card"])
    brow.pack(fill="x", pady=(2, 6))

    def select_box():
        win.destroy()
        app.select_region()

    SoftPill(brow, P, F, "Select text box…", select_box).pack(side="left", padx=(0, 6))
    SoftPill(brow, P, F, "Show text box", app.flash_region).pack(side="left")

    switch_row(tg, "Look up new games on VNDB", "vndb_auto_match", True)

    # ---- VNDB account: pull the VNs already read on VNDB into the Library
    tk.Frame(tg, bg=P["line"], height=1).pack(fill="x", pady=(8, 3))
    tk.Label(tg, text="VNDB account", bg=P["card"], fg=P["fg"], font=F["mdb"], anchor="w").pack(
        fill="x", pady=(4, 0))
    vbox = tk.Frame(tg, bg=P["card"])
    vbox.pack(fill="x")

    def ago(ts):
        if not ts:
            return "never"
        d = time.time() - float(ts)
        if d < 60:
            return "just now"
        if d < 3600:
            return f"{int(d // 60)} min ago"
        if d < 86400:
            return f"{int(d // 3600)} h ago"
        return time.strftime("%b %d, %H:%M", time.localtime(float(ts)))

    if not cfg.get("vndb_user"):
        tk.Label(vbox, text="Add the VNs you already read on VNDB to your Library.", bg=P["card"], fg=P["dim"],
                 font=F["sm"], anchor="w").pack(fill="x", pady=(2, 6))
        lrow = tk.Frame(vbox, bg=P["card"])
        lrow.pack(fill="x")
        uv = tk.StringVar()
        ent = tk.Entry(lrow, textvariable=uv, font=F["md"], bg=P["bg"], fg=P["fg"], insertbackground=P["fg"],
                       relief="flat", bd=0, highlightthickness=1, highlightbackground=P["line"],
                       highlightcolor=P["accent"], selectbackground=P["accent"],
                       selectforeground=P["accent_fg"])
        ent.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))
        msg = tk.Label(vbox, text="", bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
                       wraplength=WIDTH - 90)
        busy = [False]

        def on_found(res, err):
            busy[0] = False
            if err:
                msg.configure(text="Couldn't reach VNDB, check your connection and try again.", fg=P["bad"])
            elif not res:
                msg.configure(text=f"No VNDB user called “{uv.get().strip()}”. Use the name from your "
                                   "profile URL (vndb.org/u12345) or the u12345 id.", fg=P["bad"])
            else:
                cfg["vndb_user"], cfg["vndb_username"] = res["id"], res.get("username") or uv.get().strip()
                cfg["vndb_last_sync"] = None
                save()
                app.sync_vndb()
                restyle()  # reopens this window in its linked state

        def link():
            name = uv.get().strip()
            if busy[0] or not name:
                return
            busy[0] = True
            msg.configure(text="Looking you up…", fg=P["dim"])
            app.worker.submit(lambda: app.lib.vndb_user(name), on_found)

        ent.bind("<Return>", lambda e: link())
        Pill(lrow, P, F, "Link", link, kind="accent", font="md", padx=16, pady=4).pack(side="right")
        msg.pack(fill="x", pady=(4, 0))
        win.vndb_link = link
        win.vndb_entry = uv
    else:
        who = tk.Label(vbox, text="", bg=P["card"], fg=P["fg"], font=F["md"], anchor="w")
        who.pack(fill="x", pady=(2, 6))

        def show_who(*_):
            who.configure(text=f"Linked as {cfg.get('vndb_username') or cfg.get('vndb_user')}"
                               f" · last synced {ago(cfg.get('vndb_last_sync'))}")

        show_who()
        app.listeners.append(show_who)  # sync_vndb ends with data_changed(); dead labels drop out on TclError
        brow2 = tk.Frame(vbox, bg=P["card"])
        brow2.pack(fill="x", pady=(0, 4))

        def sync_now():
            who.configure(text=f"Linked as {cfg.get('vndb_username')} · syncing…")

            def after_sync(res, err):
                try:
                    show_who()
                except tk.TclError:  # window was closed or rebuilt meanwhile
                    pass

            app.sync_vndb(after_sync)

        def unlink():
            cfg["vndb_user"] = cfg["vndb_username"] = cfg["vndb_last_sync"] = None
            save()
            restyle()

        SoftPill(brow2, P, F, "Sync now", sync_now).pack(side="left", padx=(0, 6))
        SoftPill(brow2, P, F, "Unlink", unlink).pack(side="left")
        switch_row(vbox, "Sync when the tracker starts", "vndb_sync_on_start", True)
        tk.Label(vbox, text="Unlinking keeps the VNs already added to your Library.", bg=P["card"], fg=P["dim"],
                 font=F["xs"], anchor="w").pack(fill="x", pady=(2, 0))

    tk.Label(tg, text="More options in data/config.json", bg=P["card"], fg=P["dim"], font=F["xs"],
             anchor="w").pack(fill="x", pady=(8, 0))

    # hotkeys, backups, Discord (ui_settings_extra.py)
    import ui_settings_extra
    ui_settings_extra.build_extra_sections(app, win, section, row, switch_row, seg_row, SoftPill, WIDTH)

    # VNDB status sync + lookups (ui_more.py)
    import ui_more
    ui_more.build_settings(app, win, section, row, switch_row, SoftPill, WIDTH)

    # start with Windows, tray, toasts, milestones, break reminder (ui_settings_qol.py)
    import ui_settings_qol
    ui_settings_qol.build_qol_sections(app, win, section, row, switch_row, seg_row, SoftPill, WIDTH)

    # =================================================================== footer
    def do_reset_all():
        if messagebox.askyesno("Reset all settings",
                               "Put every setting back to its default?\n\n" + KEPT_TEXT +
                               "\n\nThis can't be undone.", icon="warning", parent=win):
            keys = [k for k in app.lib.DEFAULT_CONFIG if k not in KEEP_ON_RESET_ALL]
            reset_config(app, keys)
            return True
        return False

    win.reset_all = do_reset_all
    foot = tk.Frame(body, bg=P["bg"])
    foot.pack(fill="x", pady=(14, 0))
    DangerPill(foot, P, F, "Reset all settings", do_reset_all, font="xs", padx=12, pady=3).pack(side="right")
    tk.Label(foot, text="your reading data is never touched", bg=P["bg"], fg=P["dim"], font=F["xs"]).pack(
        side="left", padx=6)

    # ---- sizing, scrolling, restoring state
    win.update_idletasks()
    for c in cards:  # size each Card to its content up front (don't wait for Configure events)
        c.configure(height=c.body.winfo_reqheight() + 2 * c.pad)
    win.update_idletasks()
    need = sf.inner.winfo_reqheight()
    scrollable = need > MAX_H
    if not scrollable:
        sf.sb.pack_forget()
    else:
        def wheel(e):
            sf.canvas.yview_scroll(int(-e.delta / 120), "units")
        win.bind("<MouseWheel>", wheel)

        def on_scroll(a, b):
            sf.sb.set(a, b)
            state["scroll"] = float(a)

        sf.canvas.configure(yscrollcommand=on_scroll)
        if saved_scroll:
            sf.canvas.yview_moveto(saved_scroll)
            win.after(80, lambda: sf.canvas.yview_moveto(saved_scroll))
    if into is not None:
        pass  # keep the window exactly where and how big it is
    elif geometry:
        win.geometry(geometry)
    else:
        win.geometry(f"{WIDTH}x{min(need, MAX_H)}")
    win.update_idletasks()
    if into is None:
        win.attributes("-alpha", 1.0)
    return win
