"""Stats / Settings pieces for lookups, VNDB status push and Read next. Must not `import tracker` (use `app.lib`).

Called from ui_stats.StatsWindow (tile, trend card, "Read next" page) and ui_settings.open_settings (section).
Everything is built from the current palette `app.P`, so the in-place rebuilds (theme change) restyle it.
"""
import datetime as dt
import tkinter as tk
import webbrowser

import lookups
import readnext
import vndb_push
from ui_theme import Card, Pill, ScrollFrame, rounded_rect, mix, rad

MAX_ROWS = 60


def _label(sw, parent, text="", font="md", fg="fg", bg="bg", **kw):
    return tk.Label(parent, text=text, font=sw.F[font], fg=sw.P[fg], bg=sw.P[bg], **kw)


# ====================================================================== lookups: Stats tile
def fill_tile(sw):
    """The "Lookups" tile: overall lookups per 1,000 characters."""
    pair = sw.tiles.get("lookups")
    if not pair:
        return
    n, chars, rate = lookups.overall(sw.store)
    pair[0].configure(text=lookups.fmt_rate(rate) if n else "0")
    pair[1].configure(text=f"{sw.lib.fmt_int(n)} lookups / 1k 字" if n else "lookups / 1k 字")


def attach(sw):
    """Keep the tile live: every counted lookup re-fills it (cheap)."""
    sw.app.more_listeners.append(lambda: fill_tile(sw))


# ====================================================================== lookups: weekly trend card
class LookupTrend:
    """Card with lookups per 1,000 characters per week (all VNs, or one VN picked from a menu)."""
    WEEKS = 12

    def __init__(self, sw, parent):
        self.sw = sw
        P, F = sw.P, sw.F
        self.grp = None
        self.card = Card(parent, P, radius=18, pad=14)
        self.card.pack(fill="x", pady=(12, 0))
        head = tk.Frame(self.card.body, bg=P["card"])
        head.pack(fill="x")
        _label(sw, head, "lookups per 1,000 字, by week", "mdb", "fg", "card").pack(side="left")
        self.pick = Pill(head, P, F, "All VNs ▾", self._menu, kind="ghost", font="sm", padx=12, pady=3)
        self.pick.pack(side="right")
        self.note = _label(sw, head, "", "xs", "dim", "card")
        self.note.pack(side="right", padx=10)
        self.cv = tk.Canvas(self.card.body, height=96, bg=P["card"], highlightthickness=0, bd=0)
        self.cv.pack(fill="x", pady=(6, 0))
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.data = []

    def _set_pick(self, text):
        p = self.pick
        p.text = text + " ▾"
        p.w = p.font.measure(p.text) + 24
        p.configure(width=p.w)
        p._draw()

    def _menu(self):
        sw = self.sw
        m = sw._menu_obj()
        m.add_command(label=("● " if not self.grp else "    ") + "All VNs", command=lambda: self.choose(None, "All VNs"))
        counts = lookups.by_group(sw.store)
        names = {it["grp"]: it["name"] for it in sw.store.library()}
        for g in sorted(counts, key=lambda g: -counts[g]):
            if g in names:
                m.add_command(label=("● " if g == self.grp else "    ") + f"{names[g]} ({counts[g]})",
                              command=lambda g=g, n=names[g]: self.choose(g, n))
        sw._popup(m, self.pick.winfo_rootx(), self.pick.winfo_rooty() + self.pick.winfo_height() + 2)

    def choose(self, grp, name):
        self.grp = grp
        short = name if len(name) <= 28 else name[:27] + "…"
        self._set_pick(short)
        self.fill()

    def fill(self):
        sw = self.sw
        cfg = sw.app.cfg
        self.data = lookups.weekly(sw.store, self.grp, self.WEEKS, cfg.get("week_starts", "monday"))
        n = sum(d[1] for d in self.data)
        self.note.configure(text=f"{n} lookups in {self.WEEKS} weeks" if n else "no lookups yet")
        self.draw()

    def draw(self):
        sw = self.sw
        P, F, cv = sw.P, sw.F, self.cv
        cv.delete("all")
        W, H = cv.winfo_width(), int(cv["height"])
        if W < 120 or not self.data:
            return
        pad_l, pad_r, pad_t, pad_b = 40, 8, 10, 20
        rates = [d[3] for d in self.data]
        top = max([r for r in rates if r is not None] + [1.0])
        ph = H - pad_t - pad_b
        n = len(self.data)
        bw = (W - pad_l - pad_r) / n
        for frac in (0, 0.5, 1):
            y = pad_t + ph * (1 - frac)
            cv.create_line(pad_l, y, W - pad_r, y, fill=P["line"])
            cv.create_text(pad_l - 6, y, text=lookups.fmt_rate(top * frac), fill=P["dim"], anchor="e", font=F["xs"])
        soft = mix(P["accent"], P["card"], 0.45)
        step = 2 if bw < 46 else 1
        for i, (wk, looks, chars, rate) in enumerate(self.data):
            x0, x1 = pad_l + i * bw + bw * 0.2, pad_l + (i + 1) * bw - bw * 0.2
            base = pad_t + ph
            h = 0
            if rate is not None and rate > 0:
                h = max(3, ph * rate / top)
                col = P["accent"] if i == n - 1 else soft
                r = min(rad(6), (x1 - x0) / 2, h / 2)
                rounded_rect(cv, x0, base - h, x1, base, r, fill=col, outline=col)
                cv.create_rectangle(x0, base - h + r, x1, base, fill=col, outline=col)
            hit = cv.create_rectangle(pad_l + i * bw, pad_t, pad_l + (i + 1) * bw, base, fill="", outline="")
            tip = f"week of {wk.strftime('%b %d')}: {looks} lookups"
            tip += f", {lookups.fmt_rate(rate)} / 1k" if rate is not None else " (too little text)"
            cv.tag_bind(hit, "<Enter>", lambda e, x=(x0 + x1) / 2, y=base - h, t=tip: self._tip(x, y, t, W))
            cv.tag_bind(hit, "<Leave>", lambda e: cv.delete("tip"))
            if (n - 1 - i) % step == 0:
                cv.create_text((x0 + x1) / 2, base + 11, text=wk.strftime("%b %d"), fill=P["dim"], font=F["xs"])

    def _tip(self, x, ytop, text, W):
        P, F, cv = self.sw.P, self.sw.F, self.cv
        cv.delete("tip")
        t = cv.create_text(0, 0, text=text, font=F["sm"], fill=P["fg"], tags="tip", state="disabled")
        x0, y0, x1, y1 = cv.bbox(t)
        tw, th = x1 - x0, y1 - y0
        cx = min(max(x, tw / 2 + 14), W - tw / 2 - 14)
        cy = max(ytop - th / 2 - 10, th / 2 + 6)
        cv.coords(t, cx, cy)
        r = rounded_rect(cv, cx - tw / 2 - 10, cy - th / 2 - 4, cx + tw / 2 + 10, cy + th / 2 + 4, 10,
                         fill=P["card2"], outline=P["line"], tags="tip", state="disabled")
        cv.tag_lower(r, t)


# ====================================================================== Read next page
def _ago(ts):
    if not ts:
        return "never"
    d = dt.datetime.now().timestamp() - ts
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} d ago"


class ReadNextPage:
    def __init__(self, sw, parent):
        self.sw = sw
        P, F = sw.P, sw.F
        self.sort = sw.app.cfg.get("read_next_sort")
        if self.sort not in readnext.SORTS:
            self.sort = readnext.SORTS[0]
        bar = tk.Frame(parent, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 8))
        self.count = _label(sw, bar, "", "md", "dim")
        self.count.pack(side="left", padx=2)
        self.refresh_btn = Pill(bar, P, F, "Refresh", self._refresh, kind="soft", font="sm", padx=14, pady=4)
        self.refresh_btn.pack(side="right")
        self.sort_pill = Pill(bar, P, F, "", self._sort_menu, kind="ghost", font="sm", padx=12, pady=4)
        self.sort_pill.pack(side="right", padx=(0, 6))
        self._set_sort_text()
        self.info = _label(sw, bar, "", "xs", "dim")
        self.info.pack(side="right", padx=10)
        self.sf = sw._scroll_area(parent)
        self.sf.pack(fill="both", expand=True)
        self.photos = []
        readnext.state(sw.app)["listeners"].append(self._on_progress)

    # ---- plumbing
    def _on_progress(self):
        if not self.sf.winfo_exists():
            raise tk.TclError("page gone")
        if self.sw.page == "next":
            self.fill()
        else:
            self.sw.dirty.add("next")

    def _set_sort_text(self):
        p = self.sort_pill
        p.text = f"Sort: {self.sort} ▾"
        p.w = p.font.measure(p.text) + 24
        p.configure(width=p.w)
        p._draw()

    def _sort_menu(self):
        sw = self.sw
        m = sw._menu_obj()
        for s in readnext.SORTS:
            m.add_command(label=("● " if s == self.sort else "    ") + s, command=lambda s=s: self._set_sort(s))
        sw._popup(m, self.sort_pill.winfo_rootx(), self.sort_pill.winfo_rooty() + self.sort_pill.winfo_height() + 2)

    def _set_sort(self, s):
        self.sort = s
        self.sw.app.cfg["read_next_sort"] = s
        self.sw.app.save_config()
        self._set_sort_text()
        self.fill()

    def _refresh(self):
        app = self.sw.app
        if not app.cfg.get("vndb_user"):
            app.status("link your VNDB account in Settings first", 4000)
        elif app.refresh_read_next(force=False):
            app.status("refreshing wishlist…", 2500)
        self.fill()

    # ---- content
    def fill(self):
        sw = self.sw
        P, app, lib = sw.P, sw.app, sw.lib
        sw.dirty.discard("next")
        st = readnext.state(app)
        if (app.cfg.get("vndb_user") and not st["running"] and readnext.last_refresh(sw.store) is None
                and not st["error"]):
            app.refresh_read_next(force=False)  # first visit: fetch the wishlist once
        rs = readnext.sort_rows(readnext.rows(app), self.sort)
        sf = self.sf
        y = sf.canvas.yview()[0]
        for w in sf.inner.winfo_children():
            w.destroy()
        self.photos = []
        wish = sum(1 for r in rs if r["source"] == "wishlist")
        self.count.configure(text=f"{len(rs)} to read · {wish} from your wishlist")
        if st["running"]:
            self.info.configure(text=f"fetching difficulty {st['done']}/{st['total']}…" if st["total"]
                                else "fetching…")
        elif st["error"]:
            self.info.configure(text="refresh failed: " + st["error"], fg=P["bad"])
        else:
            self.info.configure(text=f"updated {_ago(readnext.last_refresh(sw.store))}", fg=P["dim"])
        if not rs:
            if app.cfg.get("vndb_user"):
                msg = "nothing to suggest yet\n\nadd VNs to your VNDB wishlist, then press Refresh"
            else:
                msg = "link your VNDB account in Settings to see your wishlist here"
            if app.cute():
                msg = "(・ω・) " + msg
            _label(sw, sf.inner, msg, "md", "dim", "bg", justify="center").pack(pady=60)
        for r in rs[:MAX_ROWS]:
            self._row(sf.inner, r)
        if len(rs) > MAX_ROWS:
            _label(sw, sf.inner, f"showing {MAX_ROWS} of {len(rs)} (sort to see others)", "sm", "dim").pack(pady=8)
        sw._finish_scroll(sf, y)

    def _row(self, parent, r):
        sw = self.sw
        P, F, app, lib = sw.P, sw.F, sw.app, sw.lib
        card = Card(parent, P, radius=14, pad=10)
        card.pack(fill="x", pady=4, padx=(0, 8))
        b = card.body
        b.columnconfigure(1, weight=1)
        img = app.cover_photo(r["vn"], 58, 82, radius=8)
        self.photos.append(img)
        pic = tk.Label(b, image=img, bg=P["card"], bd=0)
        pic.grid(row=0, column=0, rowspan=3, padx=(0, 14))
        _label(sw, b, r["title"], "mdb", "fg", "card", anchor="w", justify="left", wraplength=420).grid(
            row=0, column=1, sticky="sw")
        if r["alttitle"] and r["alttitle"] != r["title"]:
            _label(sw, b, r["alttitle"], "xs", "dim", "card", anchor="w").grid(row=1, column=1, sticky="nw")
        facts = [readnext.length_text(lib.fmt_int, r["chars"], r["chars_est"]),
                 "difficulty " + readnext.diff_text(r["diff"])]
        if r["rating"]:
            facts.append(f"VNDB {r['rating']:.0f}")
        _label(sw, b, "  ·  ".join(facts), "sm", "dim", "card", anchor="w").grid(row=2, column=1, sticky="nw",
                                                                                        pady=(2, 0))
        side = tk.Frame(b, bg=P["card"])
        side.grid(row=0, column=2, rowspan=3, padx=(12, 4), sticky="e")
        chip_text = "in library" if r["in_library"] else "wishlist"
        Pill(side, P, F, chip_text, kind="chip", color=P["good"] if r["in_library"] else P["accent"], font="xs",
             padx=10, pady=2).pack(anchor="e", pady=(0, 6))
        btns = tk.Frame(side, bg=P["card"])
        btns.pack(anchor="e")
        if not (r["in_library"] and r["status"] == "Reading"):
            Pill(btns, P, F, "Start reading", lambda r=r: self._start(r), kind="accent", font="sm", padx=14,
                 pady=4).pack(side="left", padx=(0, 6))
        Pill(btns, P, F, "Open on VNDB", lambda r=r: webbrowser.open(f"https://vndb.org/{r['vid']}"), kind="soft",
             font="sm", padx=14, pady=4).pack(side="left")

    def _start(self, r):
        self.sw.app.start_reading(r)
        self.fill()


# ====================================================================== Settings section
def _entry(parent, P, F, var, **kw):
    return tk.Entry(parent, textvariable=var, font=F["md"], bg=P["bg"], fg=P["fg"], insertbackground=P["fg"],
                    relief="flat", bd=0, highlightthickness=1, highlightbackground=P["line"],
                    highlightcolor=P["accent"], selectbackground=P["accent"], selectforeground=P["accent_fg"], **kw)


def build_settings(app, win, section, row, switch_row, SoftPill, width):
    """Sections "VNDB status sync" and "lookups & read next" for ui_settings.open_settings."""
    P, F, cfg = app.P, app.F, app.cfg

    sec = section("VNDB status sync")
    switch_row(sec, "Send status changes to my VNDB list", "vndb_push_enabled", True)
    r = row(sec, "API token", pady=4)
    var = tk.StringVar(value=str(cfg.get("vndb_token") or ""))
    ent = _entry(r, P, F, var, width=30, show="•")
    ent.pack(side="right", ipady=3)
    masked = tk.Label(sec, text="", bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w")
    result = tk.Label(sec, text="", bg=P["card"], fg=P["dim"], font=F["sm"], anchor="w", justify="left",
                      wraplength=width - 90)

    def show_masked():
        t = (cfg.get("vndb_token") or "").strip()
        masked.configure(text=("saved: " + vndb_push.mask_token(t)) if t else "no token saved")

    def store(*_):
        v = var.get().strip()
        if v != (cfg.get("vndb_token") or ""):
            cfg["vndb_token"] = v
            app.save_config()
            result.configure(text="", fg=P["dim"])
        show_masked()

    ent.bind("<Return>", store)
    ent.bind("<FocusOut>", store)
    win.vndb_token_var = var
    win.vndb_token_store = store

    def test():
        store()
        result.configure(text="checking…", fg=P["dim"])

        def shown(text, ok):
            try:
                result.configure(text=text, fg=P["good"] if ok else P["bad"])
            except tk.TclError:
                pass

        app.vndb_test_token(shown)

    btns = tk.Frame(sec, bg=P["card"])
    btns.pack(fill="x", pady=(2, 2))
    win.vndb_test_btn = SoftPill(btns, P, F, "Test token", test)
    win.vndb_test_btn.pack(side="left", padx=(0, 6))
    SoftPill(btns, P, F, "Get a token", lambda: webbrowser.open("https://vndb.org/u/tokens")).pack(side="left")
    masked.pack(fill="x", pady=(4, 0))
    result.pack(fill="x", pady=(2, 0))
    show_masked()
    tk.Label(sec, text="Create a token at vndb.org/u/tokens with the “list write” permission. When you change "
                       "a Library status (Reading / Finished / On hold / Dropped) the VN's label on VNDB follows, "
                       "with started / finished dates. Only VNs with a VNDB id are sent.",
             bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
             wraplength=width - 90).pack(fill="x", pady=(4, 0))

    sec2 = section("lookups")
    switch_row(sec2, "Count dictionary lookups (meikipop popups)", "lookups_enabled", True)
    tk.Label(sec2, text="Each time meikipop's popup opens over the text box counts as one lookup for the VN you "
                        "are reading. The Library shows lookups per 1,000 characters as a difficulty hint.",
             bg=P["card"], fg=P["dim"], font=F["xs"], anchor="w", justify="left",
             wraplength=width - 90).pack(fill="x", pady=(4, 0))
