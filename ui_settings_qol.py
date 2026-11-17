"""Settings section "windows & notifications": start with Windows, tray icon, toasts, milestone popups,
mark-finished prompt, break reminder. Called from ui_settings.open_settings with its helpers so it looks
and rebuilds like the rest of the window. Must not `import tracker` (use `app.lib`)."""
import tkinter as tk


def build_qol_sections(app, win, section, row, switch_row, seg_row, SoftPill, width):
    P, F, cfg = app.P, app.F, app.cfg

    def save():
        app.save_config()

    def note(parent, text):
        tk.Label(parent, text=text, bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
                 wraplength=width - 90).pack(fill="x", pady=(4, 0))

    # =================================================================== windows
    sec = section("windows & notifications")
    win.autostart_switch = switch_row(sec, "Start with Windows", "autostart", False,
                                      after=lambda: app.set_autostart(cfg.get("autostart", False)))
    note(sec, "Puts a “VN Tracker” shortcut in your Startup folder (the same program as the Desktop shortcut). "
              "Turn it off to remove it.")
    tk.Frame(sec, bg=P["line"], height=1).pack(fill="x", pady=(8, 3))
    win.tray_switch = switch_row(sec, "Tray icon", "tray_enabled", False, after=app.apply_qol)
    win.tray_close_switch = switch_row(sec, "Close to tray (the ✕ hides the overlay)", "tray_close_to_tray", False)
    note(sec, "Right-click the tray icon: show / hide the overlay, open the Library, pause / resume, quit. "
              "A left click shows or hides the overlay.")
    tk.Frame(sec, bg=P["line"], height=1).pack(fill="x", pady=(8, 3))
    switch_row(sec, "Summary when a session ends", "toast_session", True)
    switch_row(sec, "Milestone popups (100k, 250k, ... characters)", "toast_milestones", True)
    switch_row(sec, "Ask to mark a VN finished at 100%", "auto_finish_prompt", True)
    tk.Frame(sec, bg=P["line"], height=1).pack(fill="x", pady=(8, 3))
    win.break_switch = switch_row(sec, "Break reminder", "break_reminder", False)
    r = row(sec, "Remind me after (minutes of reading)", pady=4)
    v = tk.StringVar(value=str(cfg.get("break_reminder_minutes", 60)))
    sp = tk.Spinbox(r, from_=5, to=480, increment=5, textvariable=v, width=8, justify="right", font=F["md"],
                    bg=P["bg"], fg=P["fg"], insertbackground=P["fg"], relief="flat", bd=0,
                    buttonbackground=P["card2"], highlightthickness=1, highlightbackground=P["line"],
                    highlightcolor=P["accent"], disabledbackground=P["bg"],
                    selectbackground=P["accent"], selectforeground=P["accent_fg"])
    sp.pack(side="right", ipady=3)

    def store(rewrite):
        try:
            n = max(5, min(480, int(float(v.get()))))
        except ValueError:
            if rewrite:
                v.set(str(cfg.get("break_reminder_minutes", 60)))
            return
        if rewrite:
            v.set(str(n))
        if cfg.get("break_reminder_minutes") != n:
            cfg["break_reminder_minutes"] = n
            save()

    sp.configure(command=lambda: store(True))
    sp.bind("<Return>", lambda e: store(True))
    sp.bind("<FocusOut>", lambda e: store(True))
    v.trace_add("write", lambda *_: store(False))
    win.break_minutes = v
    note(sec, "A gentle toast after that long without a 5-minute break. The timer restarts after a break "
              "or when the session ends.")
