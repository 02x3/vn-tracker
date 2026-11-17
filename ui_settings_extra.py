"""Settings sections for hotkeys, backups and Discord. Called from ui_settings.open_settings with its helpers,
so they look and rebuild like the rest of the window. Must not `import tracker` (use `app.lib`)."""
import os
import time
import tkinter as tk

import hotkeys


def _entry(parent, P, F, var, **kw):
    return tk.Entry(parent, textvariable=var, font=F["md"], bg=P["bg"], fg=P["fg"], insertbackground=P["fg"],
                    relief="flat", bd=0, highlightthickness=1, highlightbackground=P["line"],
                    highlightcolor=P["accent"], selectbackground=P["accent"], selectforeground=P["accent_fg"], **kw)


def _ago(ts):
    d = time.time() - float(ts)
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if time.strftime("%Y-%m-%d", time.localtime(ts)) == time.strftime("%Y-%m-%d"):
        return "today " + time.strftime("%H:%M", time.localtime(ts))
    return time.strftime("%b %d, %H:%M", time.localtime(ts))


def build_extra_sections(app, win, section, row, switch_row, seg_row, SoftPill, width):
    P, F, cfg = app.P, app.F, app.cfg

    def save():
        app.save_config()

    # =================================================================== hotkeys
    hk = section("hotkeys")
    labels = {}  # action -> (entry var, entry, fail label)

    def show_failures():
        failed = app.hotkeys.failed if cfg.get("hotkeys_enabled", True) else {}
        for action, (var, ent, fail) in labels.items():
            if action in failed:
                fail.configure(text=failed[action])
                if not fail.winfo_ismapped():
                    fail.pack(side="right", padx=(0, 8))
            else:
                fail.pack_forget()

    def on_toggle():
        app.apply_hotkeys()
        show_failures()
        for var, ent, fail in labels.values():
            ent.configure(state="readonly" if cfg.get("hotkeys_enabled", True) else "disabled")

    switch_row(hk, "Global hotkeys", "hotkeys_enabled", True, after=on_toggle)

    def make_row(action):
        r = row(hk, hotkeys.LABELS[action], pady=3)
        var = tk.StringVar(value=hotkeys.pretty(cfg["hotkeys"].get(action) or hotkeys.DEFAULTS[action]))
        reset = tk.Label(r, text="reset", bg=P["card"], fg=P["dim"], font=F["xs"], cursor="hand2")
        reset.pack(side="right", padx=(8, 0))
        ent = _entry(r, P, F, var, width=16, justify="center", state="readonly", readonlybackground=P["bg"],
                     cursor="hand2")
        ent.pack(side="right", ipady=3)
        fail = tk.Label(r, text="", bg=P["card"], fg=P["bad"], font=F["xs"])
        labels[action] = (var, ent, fail)

        def shown():
            var.set(hotkeys.pretty(cfg["hotkeys"].get(action) or hotkeys.DEFAULTS[action]))

        def set_combo(combo):
            cfg["hotkeys"][action] = combo
            save()
            shown()
            app.apply_hotkeys()
            show_failures()

        def stop_capture(*_):
            ent.unbind("<KeyPress>")
            ent.unbind("<FocusOut>")
            shown()
            win.focus_set()

        def on_key(e):
            if e.keysym == "Escape":
                stop_capture()
                return "break"
            combo = hotkeys.from_tk_event(e.keysym, e.state)
            if combo is None:  # only a modifier so far
                return "break"
            try:
                combo = hotkeys.normalize(combo)
            except ValueError as err:
                var.set(str(err))
                return "break"
            stop_capture()
            set_combo(combo)
            return "break"

        def start_capture(_=None):
            if not cfg.get("hotkeys_enabled", True):
                return
            var.set("press keys…")
            ent.focus_set()
            ent.bind("<KeyPress>", on_key)
            ent.bind("<FocusOut>", stop_capture)

        ent.bind("<Button-1>", lambda e: (start_capture(), "break")[1])
        reset.bind("<Button-1>", lambda e: set_combo(hotkeys.DEFAULTS[action]))
        reset.bind("<Enter>", lambda e: reset.configure(fg=P["accent"]))
        reset.bind("<Leave>", lambda e: reset.configure(fg=P["dim"]))
        win.hotkey_capture = getattr(win, "hotkey_capture", {})
        win.hotkey_capture[action] = (start_capture, on_key)

    for action in hotkeys.ACTIONS:
        make_row(action)
    on_toggle_state = "readonly" if cfg.get("hotkeys_enabled", True) else "disabled"
    for var, ent, fail in labels.values():
        ent.configure(state=on_toggle_state)
    tk.Label(hk, text="Click a box, then press the keys. Esc cancels. Works while a game has focus.",
             bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
             wraplength=width - 90).pack(fill="x", pady=(6, 0))
    show_failures()

    # =================================================================== backups
    bk = section("backups")
    last = tk.Label(bk, text="", bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
                    wraplength=width - 90)

    def show_last():
        info = app.last_backup_info()
        keep = int(cfg.get("backup_keep", 7) or 7)
        if info:
            text = f"last backup: {_ago(info[1])}  ·  keeps the last {keep}"
        else:
            text = f"last backup: none yet  ·  keeps the last {keep}"
        last.configure(text=text)

    def back_up():
        def done(path, err):
            try:
                show_last()
            except tk.TclError:
                pass

        app.backup_now(manual=True, callback=done)

    def open_folder():
        folder = app.backup_dir()
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    brow = tk.Frame(bk, bg=P["card"])
    brow.pack(fill="x", pady=(2, 4))
    win.backup_now_btn = SoftPill(brow, P, F, "Back up now", back_up)
    win.backup_now_btn.pack(side="left", padx=(0, 6))
    SoftPill(brow, P, F, "Open backups folder", open_folder).pack(side="left")
    last.pack(fill="x", pady=(2, 0))
    show_last()
    app.listeners.append(show_last)

    # =================================================================== Discord
    dc = section("discord")

    def on_discord():
        app.apply_discord()
        show_state()

    switch_row(dc, "Show what I'm reading on Discord", "discord_enabled", False, after=on_discord)
    arow = row(dc, "Application ID", pady=4)
    idvar = tk.StringVar(value=str(cfg.get("discord_client_id") or ""))
    ident = _entry(arow, P, F, idvar, width=24)
    ident.pack(side="right", ipady=3)

    def store_id(*_):
        v = idvar.get().strip()
        if v != cfg.get("discord_client_id"):
            cfg["discord_client_id"] = v
            save()
            app.apply_discord()
        show_state()

    ident.bind("<Return>", store_id)
    ident.bind("<FocusOut>", store_id)
    win.discord_id_var = idvar
    win.discord_store_id = store_id
    seg_row(dc, "Title", "discord_title_lang", [("english", "English"), ("japanese", "Japanese")],
            cfg.get("discord_title_lang", "english"))
    switch_row(dc, "Show the cover", "discord_show_cover", True)
    switch_row(dc, "Show characters read", "discord_show_chars", True)
    state = tk.Label(dc, text="", bg=P["card"], fg=P["dim"], font=F["sm"], anchor="w")
    state.pack(fill="x", pady=(6, 0))

    def show_state():
        try:
            s = app.discord.status() if cfg.get("discord_enabled") else "off"
            state.configure(text="status: " + s,
                            fg=P["good"] if s == "connected" else (P["warn"] if s != "off" else P["dim"]))
        except tk.TclError:
            pass

    def refresh_state():
        try:
            show_state()
            win.after(1500, refresh_state)
        except tk.TclError:
            pass

    refresh_state()
    tk.Label(dc, text="Create an application named “VN Tracker” at discord.com/developers/applications and "
                      "paste its Application ID here. Covers come from VNDB; explicit ones are never sent when "
                      "blurring is on.", bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
             wraplength=width - 90).pack(fill="x", pady=(4, 0))
