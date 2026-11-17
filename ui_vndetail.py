"""VN detail window: cover, totals, unique kanji, newest kanji, and a reading-speed-over-time chart.

    open_vn_detail(app, grp, geometry=None) -> Toplevel      (one window, re-pointed when opened for another VN)
    rebuild_vn_detail(app, win)                               (in place; theme change / data change)
Chart: chars/hour per session or per day on a Tk canvas drawn with app.P; hover shows the point.
Must not `import tracker` (uses app.lib).
"""
import datetime as dt
import tkinter as tk

import kanji
import vnstats
from ui_theme import Card, Pill, mix, rad, rounded_rect

W, H = 480, 190


def open_vn_detail(app, grp, geometry=None):
    win = app.windows.get("vn_detail")
    try:
        alive = win is not None and bool(win.winfo_exists())
    except tk.TclError:
        alive = False
    if alive:
        win.vn_grp = grp
        rebuild_vn_detail(app, win)
        win.deiconify()
        win.lift()
        return win
    win = tk.Toplevel(app.root)
    win.title("VN Tracker - details")
    win.geometry(geometry or "540x640")
    win.minsize(500, 420)
    win.configure(bg=app.P["bg"])
    win.vn_grp = grp
    win.mode = "session"
    app.windows["vn_detail"] = win

    def on_destroy(e):
        if e.widget is win and app.windows.get("vn_detail") is win:
            app.windows.pop("vn_detail", None)

    win.bind("<Destroy>", on_destroy, add="+")
    rebuild_vn_detail(app, win)
    refresher = lambda: rebuild_vn_detail(app, win)  # noqa: E731
    win._refresher = refresher
    app.listeners.append(refresher)  # data_changed removes it when the window is gone (TclError)
    return win


def _item(app, grp):
    for it in app.store.library():
        if it["grp"] == grp:
            return it
    return None


def rebuild_vn_detail(app, win):
    if not win.winfo_exists():
        raise tk.TclError("detail window closed")
    P, F, lib = app.P, app.F, app.lib
    for c in win.winfo_children():
        c.destroy()
    win.configure(bg=P["bg"])
    it = _item(app, win.vn_grp)
    if it is None:
        tk.Label(win, text="this VN is gone", bg=P["bg"], fg=P["dim"], font=F["md"]).pack(pady=40)
        return
    store = app.store
    outer = tk.Frame(win, bg=P["bg"])
    outer.pack(fill="both", expand=True, padx=20, pady=16)

    # ---- header: cover + title + status
    head = tk.Frame(outer, bg=P["bg"])
    head.pack(fill="x")
    vn = it["vn"]
    img = app.cover_photo(vn, 84, 120, radius=12)
    pic = tk.Label(head, image=img, bg=P["bg"], bd=0)
    pic.image = img
    pic.pack(side="left", padx=(0, 14))
    col = tk.Frame(head, bg=P["bg"])
    col.pack(side="left", fill="x", expand=True)
    tk.Label(col, text=it["name"] or "?", bg=P["bg"], fg=P["fg"], font=F["h1"], anchor="w", justify="left",
             wraplength=330).pack(fill="x")
    if vn and vn.get("alttitle") and vn["alttitle"] != it["name"]:
        tk.Label(col, text=vn["alttitle"], bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w", justify="left",
                 wraplength=330).pack(fill="x")
    Pill(col, P, F, it["status"], kind="chip", color=app.status_color(it["status"]), font="xs", padx=10,
         pady=2).pack(anchor="w", pady=(8, 0))

    # ---- numbers
    info = vnstats.summary(store, it["grp"])
    n_kanji = kanji.unique_count(store, it["grp"])
    tiles = tk.Frame(outer, bg=P["bg"])
    tiles.pack(fill="x", pady=(14, 0))
    items = [("Characters", lib.fmt_int(it["chars"])), ("Reading time", lib.fmt_dur(it["seconds"])),
             ("Speed", lib.fmt_speed(it["chars"], it["seconds"])), ("Unique kanji", lib.fmt_int(n_kanji))]
    for i, (label, val) in enumerate(items):
        tiles.columnconfigure(i, weight=1, uniform="t")
        c = Card(tiles, P, radius=14, pad=10)
        c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == 3 else 4))
        tk.Label(c.body, text=label, bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w").pack(fill="x")
        tk.Label(c.body, text=val, bg=P["card"], fg=P["fg"], font=F["lg_num"], anchor="w").pack(fill="x")
    sub = f"{info['sessions']} session{'s' if info['sessions'] != 1 else ''}"
    if info["first"]:
        sub += f" · first read {dt.datetime.fromtimestamp(info['first']).strftime('%Y-%m-%d')}"
    tk.Label(outer, text=sub, bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w").pack(fill="x", pady=(6, 0))

    # ---- speed chart
    top = tk.Frame(outer, bg=P["bg"])
    top.pack(fill="x", pady=(14, 4))
    tk.Label(top, text="reading speed (characters / hour)", bg=P["bg"], fg=P["dim"], font=F["sm"]).pack(side="left")
    for mode, label in (("day", "per day"), ("session", "per session")):
        p = Pill(top, P, F, label, lambda m=mode: _set_mode(app, win, m), kind="soft", font="xs", padx=10, pady=2,
                 selected=(win.mode == mode))
        p.pack(side="right", padx=(4, 0))
    card = Card(outer, P, radius=16, pad=10, height=H + 20)
    card.pack(fill="x")
    cv = tk.Canvas(card.body, height=H, bg=P["card"], highlightthickness=0, bd=0)
    cv.pack(fill="x")
    win.chart = cv
    series = (vnstats.speed_by_day if win.mode == "day" else vnstats.speed_by_session)(store, it["grp"])
    win.chart_series = series
    tip = tk.Label(outer, text="", bg=P["bg"], fg=P["fg"], font=F["sm"], anchor="w")
    tip.pack(fill="x", pady=(4, 0))
    cv.bind("<Configure>", lambda e: draw_speed_chart(cv, P, F, series, win.mode, lib, tip))

    # ---- newest kanji
    recent = [r for r in kanji.kanji_list(store, it["grp"], "first")][:24]
    if recent:
        tk.Label(outer, text="newest kanji in this VN", bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w").pack(
            fill="x", pady=(12, 4))
        box = Card(outer, P, radius=14, pad=10)
        box.pack(fill="x")
        tk.Label(box.body, text=" ".join(r[0] for r in recent), bg=P["card"], fg=P["fg"], font=F["lg"],
                 anchor="w", justify="left", wraplength=430).pack(fill="x")

    foot = tk.Frame(outer, bg=P["bg"])
    foot.pack(fill="x", pady=(14, 0))
    Pill(foot, P, F, "Show kanji", lambda: _show_kanji(app, it["grp"]), kind="soft", font="md", padx=16,
         pady=5).pack(side="left")
    Pill(foot, P, F, "Close", win.destroy, kind="accent", font="md", padx=18, pady=5).pack(side="right")


def _show_kanji(app, grp):
    app.open_stats("kanji")
    win = app.windows.get("stats")
    if win is not None and getattr(win, "_stats", None):
        import ui_kanji
        ui_kanji.set_filter(win._stats, grp)


def _set_mode(app, win, mode):
    win.mode = mode
    rebuild_vn_detail(app, win)


def speed_points(series, mode):
    """[(label, speed)] for the chart; label = date text."""
    out = []
    for p in series:
        if mode == "day":
            out.append((p[0], p[3]))
        else:
            out.append((dt.datetime.fromtimestamp(p[0]).strftime("%Y-%m-%d %H:%M"), p[3]))
    return out


def draw_speed_chart(cv, P, F, series, mode, lib, tip=None):
    cv.delete("all")
    w, h = cv.winfo_width(), int(cv.cget("height"))
    if w <= 10:
        return
    pts = speed_points(series, mode)
    if len(pts) < 2:
        cv.create_text(w / 2, h / 2, fill=P["dim"], font=F["sm"], justify="center",
                       text="not enough reading yet\n(needs 2+ " + ("days" if mode == "day" else "sessions")
                            + " with 2+ minutes)")
        return
    left, right, top, bot = 46, 12, 10, 24
    vals = [v for _, v in pts]
    hi = max(vals) * 1.1 or 1
    lo = 0
    x0, x1, y0, y1 = left, w - right, top, h - bot

    def px(i):
        return x0 + (x1 - x0) * i / (len(pts) - 1)

    def py(v):
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    for frac in (0, 0.5, 1.0):  # grid + y labels
        y = y1 - (y1 - y0) * frac
        cv.create_line(x0, y, x1, y, fill=P["line"])
        cv.create_text(x0 - 6, y, text=lib.fmt_int(round(hi * frac)), anchor="e", fill=P["dim"], font=F["xs"])
    avg = sum(vals) / len(vals)
    cv.create_line(x0, py(avg), x1, py(avg), fill=mix(P["accent"], P["card"], 0.55), dash=(4, 3))
    coords = []
    for i, (_, v) in enumerate(pts):
        coords += [px(i), py(v)]
    cv.create_line(*coords, fill=P["accent"], width=2, smooth=False, joinstyle="round")
    dots = []
    for i, (lab, v) in enumerate(pts):
        d = cv.create_oval(px(i) - 3, py(v) - 3, px(i) + 3, py(v) + 3, fill=P["accent"], outline=P["card"])
        dots.append((px(i), lab, v, d))
    cv.create_text(x0, h - 10, text=pts[0][0][:10], anchor="w", fill=P["dim"], font=F["xs"])
    cv.create_text(x1, h - 10, text=pts[-1][0][:10], anchor="e", fill=P["dim"], font=F["xs"])

    def move(e):
        i = min(range(len(dots)), key=lambda k: abs(dots[k][0] - e.x))
        for k, (_, _, _, d) in enumerate(dots):
            cv.itemconfigure(d, fill=P["good"] if k == i else P["accent"])
        if tip is not None:
            tip.configure(text=f"{dots[i][1]}  ·  {lib.fmt_int(round(dots[i][2]))} chars/hour")

    cv.bind("<Motion>", move)
    cv.bind("<Leave>", lambda e: tip is not None and tip.configure(text=f"average {lib.fmt_int(round(avg))} chars/hour"))
    if tip is not None:
        tip.configure(text=f"average {lib.fmt_int(round(avg))} chars/hour")
