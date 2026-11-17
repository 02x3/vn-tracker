"""Dialogs: find a game on VNDB (fix a match) and choose which game to count toward."""
import tkinter as tk
from tkinter import ttk

from ui_theme import Card, Pill


def _title(app, d, text, sub=None):
    P, F = app.P, app.F
    tk.Label(d, text=text + app.mark(), bg=P["bg"], fg=P["fg"], font=F["lg"],
             anchor="w").pack(fill="x", padx=18, pady=(14, 0 if sub else 8))
    if sub:
        tk.Label(d, text=sub, bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w", justify="left",
                 wraplength=480).pack(fill="x", padx=18, pady=(1, 8))


def _label(app, parent, text, **pack):
    P, F = app.P, app.F
    lb = tk.Label(parent, text=text, bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w")
    lb.pack(fill="x", **pack)
    return lb


def _listbox(app, parent, height=None, expand=True):
    """A palette-styled listbox inside a rounded card, with a scrollbar. Returns (card, listbox)."""
    P, F = app.P, app.F
    card = Card(parent, P, radius=14, pad=8)
    kw = {"height": height} if height else {}
    lb = tk.Listbox(card.body, bg=P["card"], fg=P["fg"], selectbackground=P["accent"],
                    selectforeground=P["accent_fg"], font=F["md"], highlightthickness=0, borderwidth=0,
                    activestyle="none", exportselection=False, relief="flat", **kw)
    sb = ttk.Scrollbar(card.body, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    lb.pack(side="left", fill="both", expand=True)
    return card, lb


def _open(app, parent, title, w, h):
    d = tk.Toplevel(parent)
    d.title(title)
    d.attributes("-topmost", True)
    d.configure(bg=app.P["bg"])
    try:
        x = parent.winfo_rootx() + 30
        y = parent.winfo_rooty() + 30
        d.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        d.geometry(f"{w}x{h}")
    return d


def _search_bar(app, d, qv, on_search):
    P, F = app.P, app.F
    bar = tk.Frame(d, bg=P["bg"])
    ent = ttk.Entry(bar, textvariable=qv, font=F["md"])
    ent.pack(side="left", fill="x", expand=True, ipady=2)
    Pill(bar, P, F, "Search", on_search, kind="accent", font="md", padx=16).pack(side="left", padx=(8, 0))
    ent.bind("<Return>", on_search)
    return bar, ent


def _vn_line(vn, with_id):
    year = (vn.get("released") or "")[:4] or "?"
    alt = f" — {vn['alttitle']}" if vn.get("alttitle") else ""
    line = f"{vn.get('title')}{alt} ({year})"
    if with_id:
        line += f" [{vn.get('id')}]"
    return line


def _ask_name(app, parent, title, prompt):
    """A small themed text prompt. Returns the text or None."""
    P, F = app.P, app.F
    d = _open(app, parent, title, 380, 150)
    out = [None]
    tk.Label(d, text=prompt, bg=P["bg"], fg=P["fg"], font=F["md"], anchor="w").pack(fill="x", padx=18, pady=(16, 6))
    v = tk.StringVar()
    ent = ttk.Entry(d, textvariable=v, font=F["md"])
    ent.pack(fill="x", padx=18, ipady=2)

    def ok(*_):
        out[0] = v.get().strip() or None
        d.destroy()

    bar = tk.Frame(d, bg=P["bg"])
    bar.pack(fill="x", padx=18, pady=14)
    Pill(bar, P, F, "Add", ok, kind="accent", font="md", padx=18).pack(side="right")
    Pill(bar, P, F, "Cancel", d.destroy, kind="ghost", font="md").pack(side="right", padx=6)
    ent.bind("<Return>", ok)
    ent.bind("<Escape>", lambda e: d.destroy())
    ent.focus_set()
    d.grab_set()
    d.wait_window()
    return out[0]


# ===================================================================== fix a VNDB match
def fix_match_dialog(app, grp, current_name, parent):
    P, F, store, lib = app.P, app.F, app.store, app.lib
    d = _open(app, parent, "Find on VNDB", 580, 470)
    _title(app, d, "find on vndb", f"Pick the right entry for “{current_name}”.")

    qv = tk.StringVar(value=lib.clean_title(current_name))
    bar, ent = _search_bar(app, d, qv, lambda *_: search())
    bar.pack(fill="x", padx=18)
    msg = tk.Label(d, text="", bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w")
    msg.pack(fill="x", padx=20, pady=(8, 4))
    card, lb = _listbox(app, d)
    card.pack(fill="both", expand=True, padx=18)
    results: list = []

    def empty_hint():
        msg.configure(text="Type a title and press Enter" + ("  (・ω・)" if app.cute() else ""))

    def show(res, err):
        if not d.winfo_exists():
            return
        lb.delete(0, "end")
        results.clear()
        if err:
            msg.configure(text=f"Search failed: {err}")
            return
        results.extend(res)
        if res:
            msg.configure(text=f"{len(res)} result(s) — double-click to pick")
        else:
            msg.configure(text="No results. Try the Japanese or romaji title"
                          + (" (╥_╥)" if app.cute() else ""))
        for vn in res:
            lb.insert("end", _vn_line(vn, True))
        if res:
            lb.selection_set(0)

    def search(*_):
        q = qv.get().strip()
        if not q:
            empty_hint()
            return
        msg.configure(text="Searching…")
        app.worker.submit(lambda: lib.vndb_search(q, 15), show)

    def pick(*_):
        sel = lb.curselection()
        if not sel:
            msg.configure(text="Pick a result first")
            return
        vn = results[sel[0]]
        keys = store.group_keys(grp)
        d.destroy()

        def done(path, err):
            store.set_match(keys, vn, 2, path)
            app.status(f"matched: {vn.get('title')}", 4000)
            app.data_changed()

        app.worker.submit(lambda: lib.download_cover(vn), done)

    def no_entry():
        store.set_no_match(store.group_keys(grp))
        d.destroy()
        app.data_changed()

    bot = tk.Frame(d, bg=P["bg"])
    bot.pack(fill="x", padx=18, pady=14)
    Pill(bot, P, F, "Use selected", pick, kind="accent", font="md", padx=18).pack(side="right")
    Pill(bot, P, F, "Not on VNDB / unlink", no_entry, kind="soft", font="md").pack(side="left")
    lb.bind("<Double-Button-1>", pick)
    lb.bind("<Return>", pick)
    d.bind("<Escape>", lambda e: d.destroy())
    ent.focus_set()
    if qv.get().strip():
        search()
    else:
        empty_hint()
    return d


# ===================================================================== choose / add a game
def choose_game_dialog(app, parent):
    P, F, store, lib = app.P, app.F, app.store, app.lib
    d = _open(app, parent, "Choose / add game", 600, 640)
    _title(app, d, "count reading toward…", "Your choice sticks until you pick “Auto-detect”.")

    mine = [it for it in store.library() if not it["unknown"]]
    _label(app, d, "your games", padx=20, pady=(2, 3))
    mcard, mine_lb = _listbox(app, d, height=6)
    mcard.pack(fill="both", expand=True, padx=18)
    for it in mine:
        mine_lb.insert("end", f"{it['name']} · {lib.fmt_int(it['chars'])} 字")
    if not mine:
        mine_lb.insert("end", "  nothing yet" + ("  (・ω・)" if app.cute() else ""))
        mine_lb.configure(state="disabled", disabledforeground=P["dim"])

    _label(app, d, "add a game from vndb", padx=20, pady=(10, 3))
    qv = tk.StringVar()
    bar, ent = _search_bar(app, d, qv, lambda *_: search())
    bar.pack(fill="x", padx=18)
    msg = tk.Label(d, text="Search by title to add a new game" if True else "", bg=P["bg"], fg=P["dim"],
                   font=F["sm"], anchor="w")
    msg.pack(fill="x", padx=20, pady=(6, 3))
    rcard, res_lb = _listbox(app, d, height=6)
    rcard.pack(fill="both", expand=True, padx=18)
    results: list = []

    def show(res, err):
        if not d.winfo_exists():
            return
        res_lb.delete(0, "end")
        results.clear()
        if err:
            msg.configure(text=f"Search failed: {err}")
            return
        results.extend(res)
        msg.configure(text=f"{len(res)} result(s)" if res else "No results. Try the Japanese or romaji title.")
        for vn in res:
            res_lb.insert("end", _vn_line(vn, False))

    def search(*_):
        q = qv.get().strip()
        if q:
            msg.configure(text="Searching…")
            app.worker.submit(lambda: lib.vndb_search(q, 15), show)

    def clear_other(this, other):
        def f(_e=None):
            if this.curselection():
                other.selection_clear(0, "end")
        return f

    mine_lb.bind("<<ListboxSelect>>", clear_other(mine_lb, res_lb))
    res_lb.bind("<<ListboxSelect>>", clear_other(res_lb, mine_lb))

    def use(*_):
        if mine and mine_lb.curselection():
            keys = store.group_keys(mine[mine_lb.curselection()[0]]["grp"])
            if keys:
                app.lock_game(keys[0])
        elif res_lb.curselection():
            app.lock_game(app.add_vndb_game(results[res_lb.curselection()[0]]))
        else:
            msg.configure(text="Pick a game from either list first")
            return
        d.destroy()

    def add_plain():
        name = _ask_name(app, d, "Add game", "Game name")
        if name:
            key = "manual:name:" + name
            store.ensure_game(key, name)
            store.set_no_match([key])
            app.lock_game(key)
            d.destroy()

    def auto():
        app.unlock_game()
        d.destroy()

    bot = tk.Frame(d, bg=P["bg"])
    bot.pack(fill="x", padx=18, pady=14)
    Pill(bot, P, F, "Count toward selected", use, kind="accent", font="md", padx=18).pack(side="right")
    Pill(bot, P, F, "Auto-detect", auto, kind="soft", font="md").pack(side="left")
    Pill(bot, P, F, "Add without VNDB…", add_plain, kind="soft", font="md").pack(side="left", padx=6)
    mine_lb.bind("<Double-Button-1>", use)
    res_lb.bind("<Double-Button-1>", use)
    d.bind("<Escape>", lambda e: d.destroy())
    ent.focus_set()
    return d


# ===================================================================== manual reading entry
def manual_entry_dialog(app, parent, grp=None):
    """Add reading done elsewhere (phone, manga, a VN without a usable text box). grp pre-selects a library entry."""
    import datetime as dt
    import goals
    import manual
    P, F, store, lib = app.P, app.F, app.store, app.lib
    d = _open(app, parent, "Add reading", 470, 450)
    _title(app, d, "add reading", "For reading done elsewhere. It counts in all your stats.")

    mine = [it for it in store.library() if not it["unknown"]]
    NEW = "＋ new / other…"
    names = [it["name"] for it in mine] + [NEW]
    pre = next((i for i, it in enumerate(mine) if it["grp"] == grp), None) if grp else None
    cur = pre if pre is not None else (0 if mine else len(names) - 1)
    today = goals.logical_today(app.cfg)

    def field(label):
        _label(app, d, label, padx=20, pady=(8, 2))

    field("visual novel")
    vnv = tk.StringVar(value=names[cur])
    combo = ttk.Combobox(d, textvariable=vnv, values=names, state="readonly", font=F["md"])
    combo.pack(fill="x", padx=18, ipady=2)
    namev = tk.StringVar()
    name_ent = ttk.Entry(d, textvariable=namev, font=F["md"])  # only shown for "new / other"

    def on_vn(*_):
        if vnv.get() == NEW:
            name_ent.pack(fill="x", padx=18, pady=(6, 0), ipady=2, after=combo)
            name_ent.focus_set()
        else:
            name_ent.pack_forget()

    combo.bind("<<ComboboxSelected>>", on_vn)

    row = tk.Frame(d, bg=P["bg"])
    row.pack(fill="x", padx=18, pady=(8, 0))
    cols = []
    for i, label in enumerate(("characters", "minutes (optional)")):
        c = tk.Frame(row, bg=P["bg"])
        c.pack(side="left", fill="x", expand=True, padx=(0, 8) if i == 0 else 0)
        tk.Label(c, text=label, bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w").pack(fill="x", pady=(0, 2))
        cols.append(c)
    charv, minv = tk.StringVar(), tk.StringVar()
    char_ent = ttk.Entry(cols[0], textvariable=charv, font=F["md"], justify="right")
    char_ent.pack(fill="x", ipady=2)
    ttk.Entry(cols[1], textvariable=minv, font=F["md"], justify="right").pack(fill="x", ipady=2)

    field("date")
    drow = tk.Frame(d, bg=P["bg"])
    drow.pack(fill="x", padx=18)
    datev = tk.StringVar(value=today.isoformat())
    ttk.Entry(drow, textvariable=datev, font=F["md"], width=12).pack(side="left", ipady=2)
    pills = {}

    def set_day(delta):
        datev.set((today - dt.timedelta(days=delta)).isoformat())
        sync_pills()

    def sync_pills():
        got = manual.parse_day(datev.get(), today)
        for k, p in pills.items():
            p.set_selected(got == today - dt.timedelta(days=k))

    for k, text in ((0, "today"), (1, "yesterday")):
        p = Pill(drow, P, F, text, lambda k=k: set_day(k), kind="soft", font="sm", padx=12, pady=4)
        p.pack(side="left", padx=(8, 0))
        pills[k] = p
    datev.trace_add("write", lambda *_: sync_pills())
    sync_pills()

    field("note (optional)")
    notev = tk.StringVar()
    ttk.Entry(d, textvariable=notev, font=F["md"]).pack(fill="x", padx=18, ipady=2)
    msg = tk.Label(d, text="", bg=P["bg"], fg=P["bad"], font=F["sm"], anchor="w")
    msg.pack(fill="x", padx=20, pady=(8, 0))

    def save(*_):
        try:
            chars = int(float(charv.get().replace(",", "").replace(" ", "") or 0))
        except ValueError:
            chars = 0
        if chars <= 0:
            msg.configure(text="Enter how many characters you read")
            return
        try:
            minutes = float(minv.get().strip() or 0)
        except ValueError:
            msg.configure(text="Minutes must be a number (or empty)")
            return
        day = manual.parse_day(datev.get(), today)
        if day is None:
            msg.configure(text="Date should look like 2026-11-10 (or today / yesterday)")
            return
        if day > today:
            msg.configure(text="That date is in the future")
            return
        sel = vnv.get()
        if sel == NEW:
            name = namev.get().strip()
            if not name:
                msg.configure(text="Type a name for the new title")
                return
            target, name = None, name
        else:
            it = mine[names.index(sel)]
            target, name = it["grp"], it["name"]
        manual.add_entry(store, target, name, chars, minutes, day, notev.get())
        d.destroy()
        app.status(f"added {lib.fmt_int(chars)} 字 to {name}" + app.mark(), 4000)
        app.data_changed()

    bot = tk.Frame(d, bg=P["bg"])
    bot.pack(fill="x", padx=18, pady=14, side="bottom")
    Pill(bot, P, F, "Add", save, kind="accent", font="md", padx=22).pack(side="right")
    Pill(bot, P, F, "Cancel", d.destroy, kind="ghost", font="md").pack(side="right", padx=6)
    d.bind("<Escape>", lambda e: d.destroy())
    d.bind("<Return>", save)
    on_vn()
    if vnv.get() != NEW:
        char_ent.focus_set()
    try:
        d.grab_set()
    except tk.TclError:
        pass
    return d
