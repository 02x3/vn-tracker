"""Small themed toast shown near the overlay (session summary, milestone, break reminder, "mark finished?").

    show_toast(app, title, lines=(), buttons=(), ms=7000, kind="info")  -> toast window or None
    buttons: [(label, callback, primary_bool)]; callback runs, then the toast closes.
One toast at a time: extra ones wait in app._toast_queue and appear when the current one closes.
Every toast is also appended to app.toast_log (last 50 dicts) so tests / other features can inspect them.
Must not `import tracker` (uses `app.lib`/`app.P`). BMP characters only in text.
"""
import tkinter as tk

from ui_theme import Card, Pill, mix

KINDS = {"info": "accent", "milestone": "warn", "finish": "good", "break": "accent"}


def show_toast(app, title, lines=(), buttons=(), ms=7000, kind="info"):
    data = dict(title=title, lines=list(lines), buttons=[b[0] for b in buttons], ms=ms, kind=kind)
    log = app.__dict__.setdefault("toast_log", [])
    log.append(data)
    del log[:-50]
    app.last_toast_buttons = list(buttons)  # (label, callback, primary) of the newest toast, for tests
    cur = getattr(app, "_toast_win", None)
    if cur is not None and _alive(cur):
        app.__dict__.setdefault("_toast_queue", []).append((title, lines, buttons, ms, kind))
        return None
    return _build(app, title, lines, buttons, ms, kind)


def _alive(w):
    try:
        return bool(w.winfo_exists())
    except tk.TclError:
        return False


def close_toast(app, win=None):
    win = win or getattr(app, "_toast_win", None)
    if win is None:
        return
    app._toast_win = None
    try:
        job = getattr(win, "_job", None)
        if job:
            win.after_cancel(job)
        win.destroy()
    except tk.TclError:
        pass
    q = app.__dict__.get("_toast_queue") or []
    if q and not getattr(app, "_closing", False):
        t, lines, buttons, ms, kind = q.pop(0)
        try:
            app.root.after(250, lambda: _build(app, t, lines, buttons, ms, kind))
        except tk.TclError:
            pass


def _build(app, title, lines, buttons, ms, kind):
    P, F, root = app.P, app.F, app.root
    ui = app.ui_theme
    try:
        win = tk.Toplevel(root)
    except tk.TclError:
        return None
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    try:
        win.attributes("-alpha", min(0.98, float(app.cfg.get("overlay_alpha", 0.95)) + 0.03))
        win.configure(bg=ui.TRANSPARENT)
        win.attributes("-transparentcolor", ui.TRANSPARENT)
    except tk.TclError:
        pass
    app._toast_win = win
    accent = P[KINDS.get(kind, "accent")] if KINDS.get(kind, "accent") in P else P["accent"]

    card = Card(win, P, fill="card", outline="line", radius=16, pad=14, stretch=False)
    card.pack()
    b = card.body
    wrap = 270
    head = tk.Frame(b, bg=P["card"])
    head.pack(fill="x")
    tk.Frame(head, bg=accent, width=4, height=18).pack(side="left", padx=(0, 8))
    tk.Label(head, text=title, bg=P["card"], fg=P["fg"], font=F["mdb"], anchor="w", justify="left",
             wraplength=wrap).pack(side="left", fill="x")
    for ln in lines:
        tk.Label(b, text=ln, bg=P["card"], fg=P["dim"], font=F["sm"], anchor="w", justify="left",
                 wraplength=wrap + 12).pack(fill="x", pady=(4, 0))
    if buttons:
        row = tk.Frame(b, bg=P["card"])
        row.pack(fill="x", pady=(10, 0))
        for label, cb, primary in buttons:
            def go(cb=cb):
                try:
                    if cb:
                        cb()
                finally:
                    close_toast(app, win)
            Pill(row, P, F, label, go, kind="accent" if primary else "soft", font="sm", padx=14,
                 pady=4).pack(side="left", padx=(0, 6))
    else:
        for w in (card, b, head) + tuple(b.winfo_children()) + tuple(head.winfo_children()):
            w.bind("<Button-1>", lambda e: close_toast(app, win))
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass

    win.update_idletasks()
    w, h = card.winfo_reqwidth(), card.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    try:
        ox, oy = root.winfo_x(), root.winfo_y()
        ow, oh = root.winfo_width(), root.winfo_height()
    except tk.TclError:
        ox, oy, ow, oh = sw - 260, 60, 240, 80
    x = ox + ow - w                       # right edges line up
    y = oy + oh + 8                       # below the overlay...
    if y + h > sh - 40:
        y = max(0, oy - h - 8)            # ...or above it when there's no room
    x = max(0, min(x, sw - w))
    win.geometry(f"{w}x{h}+{x}+{y}")
    if ms:
        win._job = win.after(ms, lambda: close_toast(app, win))
    return win
