"""Stats window for VN Tracker: summary tiles, and Library / Days / Sessions / Lines pages.

Entry point: open_stats(app, geometry=None, state=None). Uses only the `app` object from UI_CONTRACT.md
(never imports tracker) plus the widgets in ui_theme.
"""
import csv
import datetime as dt
import math
import os
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox, simpledialog

import goals
import manual
import lookups
import progress
import ui_kanji
import ui_more
from ui_heatmap import Heatmap
from ui_theme import Card, Pill, ScrollFrame, rounded_rect, mix, rad

PAGES = [("library", "Library"), ("days", "Days"), ("sessions", "Sessions"), ("lines", "Lines"),
         ("kanji", "Kanji"), ("next", "Read next")]
SORTS = ["Last read", "Characters", "Time", "Title", "Status"]
GAP = 14
# library_card_size -> cover width, height (the Card is 24px wider than its cover)
CARD_SIZES = {"small": (104, 148), "medium": (136, 194), "large": (170, 242)}
CARD_SIZE_LABELS = [("small", "Small"), ("medium", "Medium"), ("large", "Large")]
CHART_DAYS = (14, 30, 60, 90)


def _default_page(app):
    p = app.cfg.get("stats_default_page")
    return p if p in dict(PAGES) else "library"


def _fit(card):
    """Keep a Card's height following its content (defensive against Card not doing it in canvas windows)."""
    def go(_=None):
        try:
            h = card.body.winfo_reqheight() + 2 * card.pad
            if int(card.cget("height")) != h:
                card.configure(height=h)
        except tk.TclError:
            pass
    card.body.bind("<Configure>", go, add="+")
    card.after_idle(go)
    return card


def _draw_bar(cv, P, frac, color=None, h=6):
    """A thin rounded progress bar on a Canvas: faint track, accent fill (good when full)."""
    cv.delete("all")
    w = cv.winfo_width()
    if w <= 4:
        return
    cv.configure(height=h)
    rounded_rect(cv, 0, 0, w - 1, h - 1, rad(h / 2), fill=P["line"], outline=P["line"])
    if frac > 0:
        col = color or (P["good"] if frac >= 1 else P["accent"])
        rounded_rect(cv, 0, 0, max(h, int(w * frac)) - 1, h - 1, rad(h / 2), fill=col, outline=col)


def open_stats(app, geometry=None, state=None):
    page = (state or {}).get("page") or _default_page(app)
    if page not in dict(PAGES):
        page = _default_page(app)
    win = app.windows.get("stats")
    try:
        alive = win is not None and bool(win.winfo_exists())
    except tk.TclError:
        alive = False
    if alive:
        win.deiconify()
        win.lift()
        try:
            win.focus_force()
        except tk.TclError:
            pass
        if (state or {}).get("page"):  # an explicit page switches; plain "open" just raises the window
            win._stats.show(page)
        return win

    win = tk.Toplevel(app.root)
    win.title("VN Tracker - reading log")
    win.geometry(geometry or "1000x780")
    win.minsize(760, 560)
    win.configure(bg=app.P["bg"])
    win.ui_state = {"page": page}
    app.windows["stats"] = win
    win._stats = StatsWindow(app, win, page, state or {})
    win.select_page = win._stats.show  # the app calls this to switch pages on an open window
    return win


def rebuild_stats(app, win, state=None):
    """Rebuilds an open stats window's contents in place (theme change) without closing the window."""
    old = getattr(win, "_stats", None)
    if old is not None and old.refresh in app.listeners:
        app.listeners.remove(old.refresh)
    for child in win.winfo_children():
        child.destroy()
    win.unbind("<MouseWheel>")
    win.configure(bg=app.P["bg"])
    state = dict(state or {})
    page = state.get("page") if state.get("page") in dict(PAGES) else _default_page(app)
    win.ui_state = {"page": page}
    win._stats = StatsWindow(app, win, page, state)
    win.select_page = win._stats.show
    return win


class StatsWindow:
    def __init__(self, app, win, page, state):
        self.app, self.win = app, win
        self.P, self.F, self.store, self.lib = app.P, app.F, app.store, app.lib
        self.page = page
        saved = app.cfg.get("library_sort")
        self.sort = state.get("sort") if state.get("sort") in SORTS else (saved if saved in SORTS else "Last read")
        self.cover_w, self.cover_h = CARD_SIZES.get(app.cfg.get("library_card_size"), CARD_SIZES["medium"])
        self.card_w = self.cover_w + 24
        self.chart_n = app.cfg.get("chart_days") if app.cfg.get("chart_days") in CHART_DAYS else 30
        self.dirty = set()
        self.cards, self.lib_cols = [], 0
        self.daily30 = []
        self.click_job = None
        self._style_scrollbar()
        self._build()
        self.line_day = state.get("line_day")
        self.win.ui_state["line_day"] = self.line_day
        self.show(page)
        app.listeners.append(self.refresh)
        win.bind("<MouseWheel>", self._wheel)
        win.bind("<Destroy>", self._destroyed)
        self.refresh()

    # ------------------------------------------------------------------ helpers
    def _destroyed(self, e):
        if e.widget is self.win:
            if self.app.windows.get("stats") is self.win:
                self.app.windows.pop("stats", None)

    def _style_scrollbar(self):
        P = self.P
        self.app.style.configure("Card.Vertical.TScrollbar", troughcolor=P["card"], bordercolor=P["card"],
                                 background=P["card2"], lightcolor=P["card2"], darkcolor=P["card2"],
                                 arrowcolor=P["dim"], gripcount=0, relief="flat", arrowsize=11)
        self.app.style.map("Card.Vertical.TScrollbar", background=[("active", P["line"])])

    def _label(self, parent, text="", font="md", fg="fg", bg="bg", **kw):
        return tk.Label(parent, text=text, font=self.F[font], fg=self.P[fg], bg=self.P[bg], **kw)

    def _wheel(self, e):
        sf = {"library": getattr(self, "lib_sf", None), "sessions": getattr(self, "ses_sf", None),
              "next": getattr(getattr(self, "next_page", None), "sf", None),
              "kanji": getattr(self, "kj_sf", None)}.get(self.page)
        if sf is not None:
            sf.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _scroll_area(self, parent):
        sf = ScrollFrame(parent, self.P)
        # ScrollFrame binds the wheel on Enter/Leave of its canvas, which breaks over child widgets;
        # the window-level handler above covers it instead.
        sf.canvas.unbind("<Enter>")
        sf.canvas.unbind("<Leave>")
        return sf

    # ------------------------------------------------------------------ layout
    def _build(self):
        P, F, app, win = self.P, self.F, self.app, self.win
        root = tk.Frame(win, bg=P["bg"])
        root.pack(fill="both", expand=True, padx=24, pady=(20, 18))

        head = tk.Frame(root, bg=P["bg"])
        head.pack(fill="x")
        title = "reading log" + app.mark()
        self._label(head, title, "h1").pack(side="left")
        Pill(head, P, F, "Settings", lambda: app.open_settings(), kind="soft", font="md",
             padx=18, pady=6).pack(side="right")
        Pill(head, P, F, "Add game", lambda: app.choose_game_dialog(win), kind="accent", font="md",
             padx=18, pady=6).pack(side="right", padx=(0, 8))
        Pill(head, P, F, "Add reading", lambda: app.manual_entry_dialog(win), kind="soft", font="md",
             padx=18, pady=6).pack(side="right", padx=(0, 8))

        tiles = tk.Frame(root, bg=P["bg"])
        tiles.pack(fill="x", pady=(18, 0))
        self.tiles = {}
        specs = [("chars", "Characters"), ("week", "This week"), ("vns", "Visual novels"), ("time", "Reading time"),
                 ("speed", "Average speed"), ("streak", "Day streak"), ("lookups", "Lookups"),
                 ("kanji", "Unique kanji")]
        self.tile_font = F["xl_num"].copy()  # eight tiles: a little smaller than the single big number
        sz = int(self.tile_font.cget("size"))
        self.tile_font.configure(size=(1 if sz > 0 else -1) * max(10, round(abs(sz) * 0.66)))
        for i, (key, label) in enumerate(specs):
            tiles.columnconfigure(i, weight=1, uniform="tile")
            c = _fit(Card(tiles, P, radius=18, pad=10))
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == len(specs) - 1 else 4))
            self._label(c.body, label, "xs", "dim", "card", anchor="w").pack(fill="x")
            v = tk.Label(c.body, text="", font=self.tile_font, fg=P["fg"], bg=P["card"], anchor="w")
            v.pack(fill="x", pady=(2, 0))
            sub = self._label(c.body, "", "xs", "dim", "card", anchor="w")
            sub.pack(fill="x")
            self.tiles[key] = (v, sub)
            if key == "week":  # small progress bar toward the weekly goal
                self.week_bar = tk.Canvas(c.body, height=6, bg=P["card"], highlightthickness=0, bd=0)
                self.week_bar.pack(fill="x", pady=(5, 0))
                self.week_frac = 0.0
                self.week_bar.bind("<Configure>", lambda e: self._draw_week_bar())

        tabs = tk.Frame(root, bg=P["bg"])
        tabs.pack(fill="x", pady=(18, 10))
        self.tab_pills = {}
        for key, label in PAGES:
            p = Pill(tabs, P, F, label, lambda k=key: self.show(k), kind="soft", font="md", padx=18, pady=6)
            p.pack(side="left", padx=(0, 8))
            self.tab_pills[key] = p

        content = tk.Frame(root, bg=P["bg"])
        content.pack(fill="both", expand=True)
        self.pages = {k: tk.Frame(content, bg=P["bg"]) for k, _ in PAGES}
        self._build_library(self.pages["library"])
        self._build_days(self.pages["days"])
        self._build_sessions(self.pages["sessions"])
        self._build_lines(self.pages["lines"])
        ui_kanji.build_page(self, self.pages["kanji"])  # unique kanji grid (ui_kanji.py)
        self.next_page =ui_more.ReadNextPage(self, self.pages["next"])  # what to read next (readnext.py)
        ui_more.attach(self)

    def _tree_card(self, parent, cols):
        P = self.P
        card = Card(parent, P, radius=16, pad=8, height=10)
        fr = card.body
        tv = ttk.Treeview(fr, columns=[c[0] for c in cols], show="headings", selectmode="extended")
        for cid, head, width, anchor, stretch in cols:
            tv.heading(cid, text=head, anchor=anchor)
            tv.column(cid, width=width, anchor=anchor, stretch=stretch, minwidth=40)
        sb = ttk.Scrollbar(fr, orient="vertical", command=tv.yview, style="Card.Vertical.TScrollbar")
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        return card, tv

    def show(self, page):
        if page not in self.pages:
            page = "library"
        self.page = page
        self.win.ui_state["page"] = page
        for k, f in self.pages.items():
            f.pack_forget()
        self.pages[page].pack(fill="both", expand=True)
        for k, p in self.tab_pills.items():
            p.set_selected(k == page)
        if page in self.dirty:
            self._fill_page(page)

    # ------------------------------------------------------------------ library page
    def _build_library(self, f):
        P, F = self.P, self.F
        bar = tk.Frame(f, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 8))
        self.lib_count = self._label(bar, "", "md", "dim")
        self.lib_count.pack(side="left", padx=2)
        self.sort_pill = Pill(bar, P, F, "", self._sort_menu, kind="ghost", font="sm", padx=12, pady=4)
        self.sort_pill.pack(side="right")
        self._set_sort_text()
        self.lib_sf = self._scroll_area(f)
        self.lib_sf.pack(fill="both", expand=True)
        self.lib_sf.canvas.bind("<Configure>", self._reflow, add="+")

    def _set_sort_text(self):
        p = self.sort_pill
        p.text = f"Sort: {self.sort} ▾"
        w = p.font.measure(p.text) + 24
        p.w = w
        p.configure(width=w)
        p._draw()

    def _menu_obj(self):
        P = self.P
        return tk.Menu(self.win, tearoff=0, bg=P["card"], fg=P["fg"], activebackground=P["accent"],
                       activeforeground=P["accent_fg"], bd=0, relief="flat", font=self.F["sm"],
                       disabledforeground=P["dim"])

    def _popup(self, m, x, y):
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _sort_menu(self):
        m = self._menu_obj()
        for s in SORTS:
            m.add_command(label=("● " if s == self.sort else "    ") + s,
                          command=lambda s=s: self._set_sort(s))
        p = self.sort_pill
        self._popup(m, p.winfo_rootx(), p.winfo_rooty() + p.winfo_height() + 2)

    def _set_sort(self, s):
        self.sort = s
        self.win.ui_state["sort"] = s
        self._set_sort_text()
        if self.app.cfg.get("library_sort") != s:
            self.app.cfg["library_sort"] = s
            self.app.save_config()
        self._fill_library(keep_scroll=False)

    def _fill_library(self, keep_scroll=True):
        P, F, app, lib = self.P, self.F, self.app, self.lib
        data = self.store.library()
        real = [it for it in data if not it["unknown"]]
        fin = sum(1 for it in real if it["status"] == "Finished")
        reading = sum(1 for it in real if it["status"] == "Reading")
        n = len(real)
        self.lib_count.configure(text=f"{n} visual novel{'s' if n != 1 else ''} · {fin} finished"
                                      f" · {reading} reading")
        keys = {
            "Last read": lambda it: -it["last"],
            "Characters": lambda it: -it["chars"],
            "Time": lambda it: -it["seconds"],
            "Title": lambda it: (it["name"] or "").lower(),
            "Status": lambda it: (lib.STATUSES.index(it["status"]) if it["status"] in lib.STATUSES else 9,
                                  -it["last"]),
        }
        items = sorted(data, key=keys[self.sort])
        sf = self.lib_sf
        y = sf.canvas.yview()[0] if keep_scroll else 0
        for w in sf.inner.winfo_children():
            w.destroy()
        self.cards, self.lib_cols = [], 0
        self.totals = progress.all_totals(self.store)
        self.lk = lookups.by_group(self.store)
        oc, os_, _nd = self.store.totals()
        self.overall = (oc, os_)
        if items:
            progress.start_fetch(app)  # background: total characters from jiten.moe for VNs we don't know yet
        if not items:
            msg = "(・ω・) nothing read yet" if app.cute() else "nothing read yet"
            self._label(sf.inner, msg + "\n\nadd a game or start reading and it will show up here", "md", "dim",
                        justify="center").pack(pady=60)
            self._finish_scroll(sf, y)
            return
        holder = tk.Frame(sf.inner, bg=P["bg"])
        holder.pack(anchor="n", pady=(2, 16))
        self.cards = [self._make_card(holder, it) for it in items]
        self._reflow(force=True)
        self._finish_scroll(sf, y)

    def _finish_scroll(self, sf, y):
        sf.update_idletasks()
        sf.canvas.configure(scrollregion=sf.canvas.bbox("all"))
        sf.canvas.yview_moveto(y)

    def _reflow(self, e=None, force=False):
        if not self.cards:
            return
        w = self.lib_sf.canvas.winfo_width()
        cols = max(1, (w - 8) // (self.card_w + GAP))
        if cols == self.lib_cols and not force:
            return
        self.lib_cols = cols
        for i, c in enumerate(self.cards):
            c.grid(row=i // cols, column=i % cols, padx=GAP // 2, pady=GAP // 2, sticky="nsew")

    def _make_card(self, parent, it):
        P, F, app, lib = self.P, self.F, self.app, self.lib
        vn = it["vn"]
        cw = self.cover_w
        card = _fit(Card(parent, P, radius=18, pad=12, stretch=False, width=self.card_w))
        b = card.body
        img = app.cover_photo(vn, cw, self.cover_h, radius=12)
        pic = tk.Label(b, image=img, bg=P["card"], bd=0)
        pic.image = img
        pic.pack()
        prog = progress.card_progress(it, self.totals, *self.overall,
                                      cpm=self.app.cfg.get("chars_per_minute"))
        if prog:  # thin progress bar right under the cover
            bar = tk.Canvas(b, height=6, width=cw, bg=P["card"], highlightthickness=0, bd=0)
            bar.pack(fill="x", pady=(7, 0))
            col = P["good"] if prog["finished"] else (mix(P["accent"], P["card"], 0.4) if prog["estimate"] else None)
            bar.bind("<Configure>", lambda e, bar=bar, f=prog["frac"], col=col: _draw_bar(bar, P, f, col))
        self._label(b, it["name"] or "?", "mdb", "fg", "card", wraplength=cw, justify="left",
                    anchor="w").pack(fill="x", pady=(8, 0))
        if vn and vn.get("alttitle") and vn["alttitle"] != it["name"]:
            self._label(b, vn["alttitle"], "xs", "dim", "card", wraplength=cw, justify="left",
                        anchor="w").pack(fill="x")
        if it.get("source") == "vndb" and not it["chars"]:
            self._label(b, "from your VNDB list", "sm", "dim", "card", anchor="w").pack(fill="x", pady=(6, 0))
        else:
            self._label(b, f"{lib.fmt_int(it['chars'])} 字", "md", "fg", "card", anchor="w").pack(fill="x",
                                                                                                        pady=(6, 0))
            self._label(b, f"{lib.fmt_dur(it['seconds'])} · {lib.fmt_speed(it['chars'], it['seconds'])}", "sm",
                        "dim", "card", anchor="w").pack(fill="x")
        if prog:
            main, small = progress.card_texts(prog, lib.fmt_int)
            self._label(b, main, "sm", "fg", "card", anchor="w").pack(fill="x", pady=(4, 0))
            if small:
                self._label(b, small, "xs", "dim", "card", anchor="w").pack(fill="x")
        lk_text = lookups.card_text(self.lk.get(it["grp"], 0), it["chars"])  # dictionary lookups (difficulty hint)
        if lk_text:
            self._label(b, lk_text, "xs", "dim", "card", anchor="w", wraplength=cw, justify="left").pack(
                fill="x", pady=(2, 0))
        Pill(b, P, F, it["status"], kind="chip", color=app.status_color(it["status"]), font="xs", padx=10,
             pady=2).pack(anchor="w", pady=(8, 0))
        self._bind_card(card, it)
        return card

    def _bind_card(self, w, it):
        w.bind("<Button-1>", lambda e, it=it: self._left_click(e, it))
        w.bind("<Double-Button-1>", lambda e, it=it: self._dbl_click(it))
        w.bind("<Button-3>", lambda e, it=it: self._card_menu(it, e.x_root, e.y_root))
        w.configure(cursor="hand2")
        for c in w.winfo_children():
            self._bind_card(c, it)

    def _left_click(self, e, it):
        if self.click_job:
            self.win.after_cancel(self.click_job)
        x, y = e.x_root, e.y_root
        self.click_job = self.win.after(260, lambda: self._card_menu(it, x, y))

    def _dbl_click(self, it):
        if self.click_job:
            self.win.after_cancel(self.click_job)
            self.click_job = None
        self._open_vndb(it)

    def _open_vndb(self, it):
        if it["vn"]:
            webbrowser.open(f"https://vndb.org/{it['vn']['id']}")

    def _card_menu(self, it, x, y):
        self.click_job = None
        app, store = self.app, self.store
        m = self._menu_obj()
        for st in self.lib.STATUSES:
            m.add_command(label=("● " if it["status"] == st else "    ") + st,
                          command=lambda s=st: (store.set_status(it["grp"], s), app.data_changed()))
        m.add_separator()
        m.add_command(label="Fix VNDB match…",
                      command=lambda: app.fix_match_dialog(it["grp"], it["name"], self.win))
        if it["vn"]:
            m.add_command(label="Open on VNDB", command=lambda: self._open_vndb(it))
        m.add_command(label="Rename…", command=lambda: self._rename(it))
        m.add_separator()
        m.add_command(label="Add reading…", command=lambda: app.manual_entry_dialog(self.win, it["grp"]))
        m.add_command(label="Set total characters…", command=lambda: self._set_total(it))
        n_lk = self.lk.get(it["grp"], 0)
        if n_lk:
            m.add_command(label=f"Lookups: {lookups.card_text(n_lk, it['chars'])} · trend…",
                          command=lambda: (self.show("days"), self.lk_trend.choose(it["grp"], it["name"] or "?")))
        ui_kanji.card_menu_items(self, m, it)  # unique kanji count, details + speed chart, show its kanji
        m.add_separator()
        programs = [os.path.basename(k) for k in store.group_keys(it["grp"])
                    if not k.startswith("manual:") and k != "unknown"]
        if programs:
            m.add_command(label="Not a VN — delete & ignore " + ", ".join(programs),
                          command=lambda: self._delete(it, programs))
        m.add_command(label="Delete…", command=lambda: self._delete(it, None))
        self._popup(m, x, y)

    def _delete(self, it, programs):
        what = f"“{it['name']}” and its {self.lib.fmt_int(it['chars'])} 字"
        if programs:
            msg = (f"Delete {what} from your stats?\n\n{', '.join(programs)} will be ignored from now on, "
                   "so it won't be detected as a game again.")
        else:
            msg = f"Delete {what} from your stats?\n\nIts reading time and sessions are removed too."
        if messagebox.askyesno("Delete", msg, icon="warning", parent=self.win):
            self.app.delete_group(it["grp"], ignore_program=bool(programs))
            self.app.status(f"deleted {it['name']}")

    def _set_total(self, it):
        vid = it["vn"]["id"] if it["vn"] else it["grp"]
        row = progress.all_totals(self.store).get(vid)
        cur = row["total"] if row and row["source"] == "user" else None
        online = row["total"] if row and row["source"] == "jiten" else None
        hint = (f"\nOnline (jiten.moe): {self.lib.fmt_int(online)}" if online else "")
        s = simpledialog.askstring(
            "Total characters",
            f"Total characters in “{it['name']}” (empty = use the online / estimated value):{hint}",
            initialvalue=str(cur) if cur else "", parent=self.win)
        if s is None:
            return
        digits = "".join(ch for ch in s if ch.isdigit())
        progress.set_user_total(self.store, vid, int(digits) if digits else 0)
        self.app.data_changed()

    def _rename(self, it):
        new = simpledialog.askstring("Rename", "New name (an existing unmatched name merges them):",
                                     initialvalue=it["name"], parent=self.win)
        if new and new.strip():
            self.store.rename_group(it["grp"], new.strip())
            self.app.data_changed()

    # ------------------------------------------------------------------ days page
    def _build_days(self, f):
        P, F = self.P, self.F
        top = tk.Frame(f, bg=P["bg"])
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        heat = _fit(Card(top, P, radius=18, pad=16, stretch=False))
        heat.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._label(heat.body, "the last 26 weeks", "mdb", "fg", "card", anchor="w").pack(fill="x")
        self.heat = Heatmap(heat.body, self.app, weeks=26, on_click=self._open_day)
        self.heat.pack(pady=(6, 0))
        chart = _fit(Card(top, P, radius=18, pad=16))
        chart.grid(row=0, column=1, sticky="nsew")
        self._label(chart.body, f"last {self.chart_n} days", "mdb", "fg", "card", anchor="w").pack(fill="x")
        self.cv = tk.Canvas(chart.body, height=self.heat.winfo_reqheight() - 10, bg=P["card"], highlightthickness=0,
                            bd=0)
        self.cv.pack(fill="x", pady=(6, 0))
        self.cv.bind("<Configure>", lambda e: self._draw_chart())
        self.lk_trend = ui_more.LookupTrend(self, f)  # lookups per 1,000 chars by week (lookups.py)
        card, self.days_tv = self._tree_card(f, [
            ("day", "Date", 150, "w", False), ("chars", "Characters", 110, "e", True),
            ("time", "Time", 100, "e", True), ("speed", "Speed", 100, "e", True),
            ("lines", "Lines", 80, "e", True)])
        card.pack(fill="both", expand=True, pady=(12, 0))

    def _draw_chart(self):
        P, F, lib = self.P, self.F, self.lib
        cv = self.cv
        cv.delete("all")
        W, H = cv.winfo_width(), int(cv["height"])
        if W < 120:
            return
        pad_l, pad_r, pad_t, pad_b = 48, 8, 14, 24
        data = {d: c for d, c, s, n in self.daily30}
        today = dt.date.fromisoformat(self.store.today_str())
        n = self.chart_n
        days = [today - dt.timedelta(days=i) for i in range(n - 1, -1, -1)]
        vals = [data.get(d.isoformat(), 0) or 0 for d in days]
        goal = int(self.app.cfg.get("daily_goal") or 0)
        top = max(max(vals), goal, 1)
        ph = H - pad_t - pad_b
        bw = (W - pad_l - pad_r) / len(days)
        for frac in (0, 0.5, 1):
            y = pad_t + ph * (1 - frac)
            cv.create_line(pad_l, y, W - pad_r, y, fill=P["line"])
            cv.create_text(pad_l - 8, y, text=lib.fmt_int(top * frac), fill=P["dim"], anchor="e", font=F["xs"])
        soft = mix(P["accent"], P["card"], 0.45)
        label_step = max(1, math.ceil(F["xs"].measure("Mar 30") * 1.5 / bw))  # a date label every few bars
        for i, (d, v) in enumerate(zip(days, vals)):
            cx0, cx1 = pad_l + i * bw, pad_l + (i + 1) * bw
            x0, x1 = cx0 + bw * 0.2, cx1 - bw * 0.2
            base = pad_t + ph
            if v:
                h = max(3, ph * v / top)
                color = P["good"] if (goal and v >= goal) else (P["accent"] if d == today else soft)
                r = min(rad(6), (x1 - x0) / 2, h / 2)
                rounded_rect(cv, x0, base - h, x1, base, r, fill=color, outline=color)
                cv.create_rectangle(x0, base - h + r, x1, base, fill=color, outline=color)
            top_y = base - (max(3, ph * v / top) if v else 0)
            hit = cv.create_rectangle(cx0, pad_t, cx1, base, fill="", outline="")
            label = f"{d.strftime('%a %b %d')}: {lib.fmt_int(v)} characters"
            cv.tag_bind(hit, "<Enter>", lambda e, x=(cx0 + cx1) / 2, y=top_y, t=label: self._tip(x, y, t, W))
            cv.tag_bind(hit, "<Leave>", lambda e: cv.delete("tip"))
            if (len(days) - 1 - i) % label_step == 0:
                txt = d.strftime("%b %d")
                lx = min((cx0 + cx1) / 2, W - F["xs"].measure(txt) / 2 - 1)  # keep the last label inside
                cv.create_text(lx, base + 13, text=txt, fill=P["dim"], font=F["xs"])
        if goal:
            y = pad_t + ph * (1 - goal / top)
            cv.create_line(pad_l, y, W - pad_r, y, fill=P["warn"], dash=(5, 4), width=1)
            cv.create_text(pad_l + 4, y - 8, text=f"goal {lib.fmt_int(goal)}", fill=P["warn"], anchor="w",
                           font=F["xs"])

    def _tip(self, x, ytop, text, W):
        P, F, cv = self.P, self.F, self.cv
        cv.delete("tip")
        t = cv.create_text(0, 0, text=text, font=F["sm"], fill=P["fg"], tags="tip", state="disabled")
        x0, y0, x1, y1 = cv.bbox(t)
        tw, th = x1 - x0, y1 - y0
        cx = min(max(x, tw / 2 + 14), W - tw / 2 - 14)
        cy = max(ytop - th / 2 - 16, th / 2 + 8)
        cv.coords(t, cx, cy)
        r = rounded_rect(cv, cx - tw / 2 - 10, cy - th / 2 - 5, cx + tw / 2 + 10, cy + th / 2 + 5, 10,
                         fill=P["card2"], outline=P["line"], tags="tip", state="disabled")
        cv.tag_lower(r, t)

    def _fill_days(self):
        lib = self.lib
        self.daily30 = self.store.daily(self.chart_n)  # (name kept: it's the last chart_n days)
        tv = self.days_tv
        top = tv.yview()[0]
        tv.delete(*tv.get_children())
        alldays = self.store.daily()
        for d, c, s, n in alldays:
            tv.insert("", "end", values=(d, lib.fmt_int(c), lib.fmt_dur(s), lib.fmt_speed(c, s), lib.fmt_int(n)))
        self.heat.set_data(alldays)
        tv.yview_moveto(top)
        self._draw_chart()
        self.lk_trend.fill()

    # ------------------------------------------------------------------ sessions page
    def _build_sessions(self, f):
        self.ses_sf = self._scroll_area(f)
        self.ses_sf.pack(fill="both", expand=True)
        self.photos = []

    def _session_day(self, ts):
        h = int(self.app.cfg.get("day_start_hour", 4))
        return (dt.datetime.fromtimestamp(ts) - dt.timedelta(hours=h)).date()

    def _fill_sessions(self):
        P, F, app, lib, store = self.P, self.F, self.app, self.lib, self.store
        sf = self.ses_sf
        y = sf.canvas.yview()[0]
        for w in sf.inner.winfo_children():
            w.destroy()
        self.photos = []
        sessions = store.sessions()
        if not sessions:
            msg = "(・ω・) no sessions yet" if app.cute() else "no sessions yet"
            self._label(sf.inner, msg + "\n\nsessions appear once you read a few lines", "md", "dim",
                        justify="center").pack(pady=60)
            self._finish_scroll(sf, 0)
            return
        today = dt.date.fromisoformat(store.today_str())
        vn_cache = {}
        reason_color = {"idle": P["warn"], "game closed": P["dim"], "quit": P["dim"],
                        "switched game": P["dim"], "tracker stopped": P["bad"], "manual": P["accent"]}
        last_day = None
        pad_r = 8
        for s in sessions:
            day = self._session_day(s["start"])
            if day != last_day:
                last_day = day
                if day == today:
                    txt = "Today"
                elif day == today - dt.timedelta(days=1):
                    txt = "Yesterday"
                else:
                    txt = day.strftime("%a %b %d")
                self._label(sf.inner, txt, "sm", "dim", anchor="w").pack(fill="x", padx=4, pady=(14, 4))
            if s["game"] not in vn_cache:
                vn_cache[s["game"]] = store.game_vn(s["game"])
            vn = vn_cache[s["game"]]
            row = _fit(Card(sf.inner, P, radius=14, pad=8))
            row.pack(fill="x", pady=3, padx=(0, pad_r))
            b = row.body
            b.columnconfigure(1, weight=1)
            img = app.cover_photo(vn, 34, 48, radius=7)
            self.photos.append(img)
            pic = tk.Label(b, image=img, bg=P["card"], bd=0)
            pic.grid(row=0, column=0, rowspan=2, padx=(0, 12))
            self._label(b, s["name"] or "?", "mdb", "fg", "card", anchor="w").grid(row=0, column=1, sticky="sw")
            t0 = dt.datetime.fromtimestamp(s["start"]).strftime("%H:%M")
            t1 = dt.datetime.fromtimestamp(s["end"]).strftime("%H:%M")
            span = "added by hand" if s["reason"] == "manual" else f"{t0} – {t1}"
            self._label(b, span, "sm", "dim", "card", anchor="w").grid(row=1, column=1, sticky="nw")
            for col, (txt, font, fg) in enumerate([
                    (f"{lib.fmt_int(s['chars'])} 字", "md", "fg"),
                    (lib.fmt_dur(s["seconds"]), "md", "fg"),
                    (lib.fmt_speed(s["chars"], s["seconds"]), "sm", "dim")], start=2):
                self._label(b, txt, font, fg, "card", anchor="e", width=(10 if col == 2 else 8)).grid(
                    row=0, column=col, rowspan=2, padx=(6, 0))
            if s["reason"] is None:
                chip = Pill(b, P, F, "reading now", kind="chip", color=P["accent"], font="xs", padx=10, pady=2)
            else:
                chip = Pill(b, P, F, s["reason"], kind="chip", color=reason_color.get(s["reason"], P["dim"]),
                            font="xs", padx=10, pady=2)
            chip.grid(row=0, column=5, rowspan=2, padx=(14, 4), sticky="e")
            b.columnconfigure(5, minsize=122)
        tk.Frame(sf.inner, bg=P["bg"], height=10).pack()
        self._finish_scroll(sf, y)

    # ------------------------------------------------------------------ lines page
    def _build_lines(self, f):
        P, F = self.P, self.F
        self.line_day = None  # a "YYYY-MM-DD" filter set by clicking a heatmap day
        self.day_bar = tk.Frame(f, bg=P["bg"])
        self.day_lbl = self._label(self.day_bar, "", "md", "fg")
        self.day_lbl.pack(side="left", padx=2)
        Pill(self.day_bar, P, F, "show all", lambda: self._open_day(None), kind="ghost", font="sm", padx=12,
             pady=3).pack(side="left", padx=8)
        card, self.lines_tv = self._tree_card(f, [
            ("when", "Time", 120, "w", False), ("game", "Game", 230, "w", False),
            ("chars", "字", 56, "e", False), ("text", "Text", 440, "w", True)])
        self.lines_tv.tag_configure("manual", foreground=P["accent"])
        card.pack(fill="both", expand=True)
        bar = tk.Frame(f, bg=P["bg"])
        bar.pack(fill="x", pady=(10, 0))
        Pill(bar, P, F, "Delete selected", self._delete_selected, kind="soft", font="sm", padx=16, pady=5
             ).pack(side="left")
        Pill(bar, P, F, "Export CSV", self._export_csv, kind="soft", font="sm", padx=16, pady=5).pack(side="right")

    def _fill_lines(self):
        tv = self.lines_tv
        top = tv.yview()[0]
        sel = set(tv.selection())
        tv.delete(*tv.get_children())
        if self.line_day:
            rows = manual.lines_for_day(self.store, self.line_day)
            d = dt.date.fromisoformat(self.line_day)
            self.day_lbl.configure(text=f"{d.strftime('%a %b %d')} · {len(rows)} line{'s' if len(rows) != 1 else ''}"
                                        f" · {self.lib.fmt_int(sum(r[3] for r in rows))} 字")
            self.day_bar.pack(fill="x", pady=(0, 8), before=tv.master.master)
        else:
            rows = self.store.recent_lines()
            self.day_bar.pack_forget()
        for lid, ts, name, c, s, text in rows:
            isman = manual.is_manual(text)
            when = dt.datetime.fromtimestamp(ts).strftime("%m/%d %H:%M:%S" if not isman else "%m/%d  manual")
            tv.insert("", "end", iid=str(lid), values=(when, name, c, manual.display_text(text).replace("\n", " ")),
                      tags=("manual",) if isman else ())
        keep = [i for i in sel if tv.exists(i)]
        if keep:
            tv.selection_set(keep)
        tv.yview_moveto(top)

    def _open_day(self, day_iso):
        """Heatmap click: the Lines page filtered to that reading day (None clears the filter)."""
        self.line_day = day_iso
        self.win.ui_state["line_day"] = day_iso
        self._fill_page("lines")
        if day_iso:
            self.show("lines")

    def _delete_selected(self):
        sel = self.lines_tv.selection()
        if not sel:
            messagebox.showinfo("VN Tracker", "Select lines first.", parent=self.win)
            return
        if messagebox.askyesno("VN Tracker", f"Delete {len(sel)} line(s) from your stats?", parent=self.win):
            ids = [int(i) for i in sel]
            self.store.delete_lines(ids)
            manual.cleanup(self.store)  # manual entries take their session / empty game key with them
            tr = getattr(self.app, "tracker", None)
            if tr is not None:
                tr.session_ids = [i for i in tr.session_ids if i not in ids]
            self.app.data_changed()

    def _export_csv(self):
        path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv",
                                            initialfile=f"vn-reading-{self.store.today_str()}.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["day", "time", "game", "vndb_id", "characters", "seconds", "text"])
            w.writerows(self.store.all_lines())
        messagebox.showinfo("VN Tracker", f"Exported to\n{path}", parent=self.win)

    # ------------------------------------------------------------------ refresh
    def _fill_tiles(self):
        lib, store = self.lib, self.store
        chars, secs, ndays = store.totals()
        real = [it for it in store.library() if not it["unknown"]]
        today_chars = store.sum_since(store.day_start_epoch())[0]
        streak = store.streak()
        t = self.tiles
        t["chars"][0].configure(text=lib.fmt_int(chars))
        t["chars"][1].configure(text=f"{lib.fmt_int(today_chars)} today")
        wk = goals.week_summary(store)
        t["week"][0].configure(text=lib.fmt_int(wk["chars"]))
        t["week"][1].configure(text=(f"of {lib.fmt_int(wk['goal'])} goal" if wk["goal"] else "no weekly goal set")
                               + (self.app.mark() if wk["goal"] and wk["frac"] >= 1 else ""))
        self.week_frac = wk["frac"] if wk["goal"] else 0.0
        self._draw_week_bar()
        t["vns"][0].configure(text=lib.fmt_int(len(real)))
        t["vns"][1].configure(text=f"{sum(1 for it in real if it['status'] == 'Finished')} finished")
        t["time"][0].configure(text=lib.fmt_dur(secs))
        t["time"][1].configure(text=f"over {lib.fmt_int(ndays)} day{'s' if ndays != 1 else ''}")
        t["speed"][0].configure(text=lib.fmt_speed(chars, secs))
        t["speed"][1].configure(text="characters / hour")
        t["streak"][0].configure(text=str(streak))
        t["streak"][1].configure(text="day in a row" if streak == 1 else "days in a row")
        ui_more.fill_tile(self)
        ui_kanji.fill_tile(self)

    def _draw_week_bar(self):
        _draw_bar(self.week_bar, self.P, self.week_frac)

    def _fill_page(self, page):
        self.dirty.discard(page)
        {"library": self._fill_library, "days": self._fill_days, "sessions": self._fill_sessions,
         "lines": self._fill_lines, "kanji": lambda: ui_kanji.fill_page(self),
         "next": self.next_page.fill}[page]()

    def refresh(self):
        if not self.win.winfo_exists():
            raise tk.TclError("stats window closed")
        self._fill_tiles()
        self.dirty = {k for k, _ in PAGES}
        self._fill_page(self.page)
