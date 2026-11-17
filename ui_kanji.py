"""Kanji page + "unique kanji" tile for the Stats window, and the Library card menu entries for it.

Called from ui_stats.StatsWindow (`sw`): build_page(sw, frame), fill_page(sw), fill_tile(sw),
card_menu_items(sw, menu, item). Logic lives in kanji.py. Must not `import tracker` (use `sw.lib`).
The grid is one Canvas (a few thousand kanji as plain items), so it stays fast and rebuilds in place.
"""
import datetime as dt
import time
import tkinter as tk
import types
from tkinter import ttk

import kanji
from ui_theme import Card, Pill, mix

CELL = 46
RECENT_DAYS = 7
SORTS = [("first", "Newest"), ("oldest", "Oldest"), ("freq", "Most seen"), ("rare", "Rarest")]


def _state(sw):
    st = getattr(sw, "kj", None)
    if st is None:
        # sort is a saved preference (cfg kanji_sort); the VN filter lives on the app so a theme rebuild keeps it
        st = sw.kj = {"sort": sw.app.cfg.get("kanji_sort") or "first", "grp": sw.app.__dict__.get("_kj_grp"),
                      "rows": [], "cols": 0, "hover": None}
        if st["sort"] not in dict(SORTS):
            st["sort"] = "first"
    return st


def _set_pill(p, text):
    p.text = text
    p.w = p.font.measure(text) + 24
    p.configure(width=p.w)
    p._draw()


def fill_tile(sw):
    store = sw.store
    n = kanji.unique_count(store)
    new = kanji.new_today(store)
    v, sub = sw.tiles["kanji"]
    v.configure(text=sw.lib.fmt_int(n))
    sub.configure(text=f"+{sw.lib.fmt_int(new)} today" if new else "different kanji")


def build_page(sw, f):
    P, F = sw.P, sw.F
    st = _state(sw)
    bar = tk.Frame(f, bg=P["bg"])
    bar.pack(fill="x", pady=(0, 8))
    sw.kj_count = sw._label(bar, "", "md", "dim")
    sw.kj_count.pack(side="left", padx=2)
    st["vn_pill"] = Pill(bar, P, F, "", lambda: _vn_menu(sw), kind="ghost", font="sm", padx=12, pady=4)
    st["vn_pill"].pack(side="right")
    st["sort_pill"] = Pill(bar, P, F, "", lambda: _sort_menu(sw), kind="ghost", font="sm", padx=12, pady=4)
    st["sort_pill"].pack(side="right", padx=(0, 4))

    info = tk.Frame(f, bg=P["bg"])
    info.pack(fill="x", pady=(0, 8))
    st["legend"] = tk.Canvas(info, width=14, height=14, bg=P["bg"], highlightthickness=0, bd=0)
    st["legend"].pack(side="left", padx=(4, 6))
    st["legend"].create_rectangle(1, 1, 13, 13, fill=P["accent"], outline=P["accent"])
    sw._label(info, f"new in the last {RECENT_DAYS} days", "xs", "dim").pack(side="left")
    st["tip"] = sw._label(info, "", "sm", "fg", anchor="e", justify="right")
    st["tip"].pack(side="right", padx=4)

    card = Card(f, P, radius=16, pad=8, height=10)
    card.pack(fill="both", expand=True)
    body = card.body
    sb = ttk.Scrollbar(body, orient="vertical", style="Card.Vertical.TScrollbar")
    cv = tk.Canvas(body, bg=P["card"], highlightthickness=0, bd=0)
    sb.configure(command=cv.yview)
    cv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    cv.pack(side="left", fill="both", expand=True)
    st["cv"] = cv
    sw.kj_sf = types.SimpleNamespace(canvas=cv)  # the window-level wheel handler scrolls this
    cv.bind("<Configure>", lambda e: _draw(sw))
    cv.bind("<Motion>", lambda e: _hover(sw, e))
    cv.bind("<Leave>", lambda e: st["tip"].configure(text=""))
    _set_pill(st["sort_pill"], "Sort: " + dict(SORTS)[st["sort"]] + " ▾")
    _set_pill(st["vn_pill"], "VN: " + _vn_name(sw, st["grp"]) + " ▾")


def _vn_name(sw, grp):
    if grp is None:
        return "All"
    for it in sw.store.library():
        if it["grp"] == grp:
            n = it["name"] or "?"
            return n if len(n) <= 22 else n[:21] + "…"
    return "All"


def _sort_menu(sw):
    st = _state(sw)
    m = sw._menu_obj()
    for key, label in SORTS:
        m.add_command(label=("● " if key == st["sort"] else "    ") + label, command=lambda k=key: _set_sort(sw, k))
    p = st["sort_pill"]
    sw._popup(m, p.winfo_rootx(), p.winfo_rooty() + p.winfo_height() + 2)


def _set_sort(sw, key):
    st = _state(sw)
    st["sort"] = key
    if sw.app.cfg.get("kanji_sort") != key:
        sw.app.cfg["kanji_sort"] = key
        sw.app.save_config()
    _set_pill(st["sort_pill"], "Sort: " + dict(SORTS)[key] + " ▾")
    fill_page(sw)


def _vn_menu(sw):
    st = _state(sw)
    m = sw._menu_obj()
    counts = kanji.per_vn_counts(sw.store)
    items = [it for it in sw.store.library() if counts.get(it["grp"])]
    items.sort(key=lambda it: -counts[it["grp"]])
    m.add_command(label=("● " if st["grp"] is None else "    ") + "All visual novels",
                  command=lambda: set_filter(sw, None))
    for it in items[:40]:
        name = it["name"] or "?"
        name = name if len(name) <= 36 else name[:35] + "…"
        m.add_command(label=("● " if st["grp"] == it["grp"] else "    ") + f"{name}  ({counts[it['grp']]})",
                      command=lambda g=it["grp"]: set_filter(sw, g))
    p = st["vn_pill"]
    sw._popup(m, p.winfo_rootx(), p.winfo_rooty() + p.winfo_height() + 2)


def set_filter(sw, grp):
    st = _state(sw)
    st["grp"] = grp
    sw.app._kj_grp = grp
    _set_pill(st["vn_pill"], "VN: " + _vn_name(sw, grp) + " ▾")
    fill_page(sw)


def fill_page(sw):
    """Reloads the kanji rows from the DB and redraws."""
    st = _state(sw)
    if st["grp"] is not None and not any(it["grp"] == st["grp"] for it in sw.store.library()):
        st["grp"] = sw.app._kj_grp = None  # that VN was deleted
        _set_pill(st["vn_pill"], "VN: All ▾")
    st["rows"] = kanji.kanji_list(sw.store, st["grp"], st["sort"])
    n = len(st["rows"])
    total = kanji.unique_count(sw.store)
    scope = "" if st["grp"] is None else f" in this VN · {sw.lib.fmt_int(total)} overall"
    sw.kj_count.configure(text=f"{sw.lib.fmt_int(n)} unique kanji{scope}")
    _draw(sw)


def _draw(sw):
    st = _state(sw)
    cv, P, F = st.get("cv"), sw.P, sw.F
    if cv is None:
        return
    cv.delete("all")
    rows = st["rows"]
    w = max(cv.winfo_width(), CELL)
    if not rows:
        msg = "(・ω・) no kanji yet" if sw.app.cute() else "no kanji yet"
        cv.create_text(w // 2, 70, text=msg + "\n\nkanji show up here as you read", fill=P["dim"], font=F["md"],
                       justify="center")
        cv.configure(scrollregion=(0, 0, w, 140))
        st["cols"] = 0
        return
    cols = max(1, w // CELL)
    st["cols"] = cols
    pad = max(0, (w - cols * CELL) // 2)
    cutoff = time.time() - RECENT_DAYS * 86400
    base, hi = P["card2"], P["accent"]
    mx = max(r[2] for r in rows) or 1
    for i, (ch, first, n, _g) in enumerate(rows):
        x, y = pad + (i % cols) * CELL, (i // cols) * CELL
        if first >= cutoff:
            fill, fg = hi, P["accent_fg"]
        else:
            # frequent kanji get a faint accent wash so the grid shows what you know best
            fill, fg = mix(base, hi, 0.28 * min(1.0, n / mx) ** 0.5), P["fg"]
        cv.create_rectangle(x + 2, y + 2, x + CELL - 2, y + CELL - 2, fill=fill, outline=fill)
        cv.create_text(x + CELL / 2, y + CELL / 2, text=ch, fill=fg, font=F["lg"])
    rows_n = (len(rows) + cols - 1) // cols
    cv.configure(scrollregion=(0, 0, w, rows_n * CELL + 4))


def _hover(sw, e):
    st = _state(sw)
    cv, cols = st["cv"], st["cols"]
    if not cols or not st["rows"]:
        return
    w = max(cv.winfo_width(), CELL)
    pad = max(0, (w - cols * CELL) // 2)
    x, y = e.x - pad, cv.canvasy(e.y)
    if x < 0 or x >= cols * CELL:
        return
    i = int(y // CELL) * cols + int(x // CELL)
    if 0 <= i < len(st["rows"]):
        ch, first, n, game = st["rows"][i]
        day = dt.datetime.fromtimestamp(first).strftime("%Y-%m-%d")
        st["tip"].configure(text=f"{ch}  ·  seen {sw.lib.fmt_int(n)}x  ·  first {day}  ·  {game}")


def card_menu_items(sw, menu, it):
    """Adds the per-VN unique kanji count and a Details entry to a Library card menu."""
    n = kanji.unique_count(sw.store, it["grp"])
    menu.add_separator()
    menu.add_command(label=f"Unique kanji: {sw.lib.fmt_int(n)}", state="disabled")
    menu.add_command(label="Details & speed chart…", command=lambda: sw.app.open_vn_detail(it["grp"]))
    menu.add_command(label="Show its kanji", command=lambda: show_vn_kanji(sw, it["grp"]))


def show_vn_kanji(sw, grp):
    sw.show("kanji")
    set_filter(sw, grp)
