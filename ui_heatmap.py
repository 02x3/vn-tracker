"""GitHub-style calendar heatmap for the Days page: one rounded square per day, last ~26 weeks.

Colour steps run from P["line"] to P["accent"]; days that met the daily goal get a `good` outline,
today a faint outline. Hover shows "Mon Nov 10 · 12,345 字 · 1h 32m", click calls on_click("YYYY-MM-DD").
Doesn't import tracker (uses app.lib for number formats).
"""
import datetime as dt
import tkinter as tk

import goals
from ui_theme import mix, rad, rounded_rect

LEVEL_MIX = (0.0, 0.3, 0.52, 0.76, 1.0)   # 0 = no reading ... 4 = goal (or your best days)
CELL, GAP = 13, 3


class Heatmap(tk.Canvas):
    def __init__(self, parent, app, weeks=26, on_click=None):
        self.app, self.P, self.F = app, app.P, app.F
        self.weeks, self.on_click = weeks, on_click
        self.data = {}
        self.left = max(self.F["xs"].measure("M"), self.F["xs"].measure("W")) + 8
        self.top = self.F["xs"].metrics("linespace") + 6
        self.legend_h = self.F["xs"].metrics("linespace") + 12
        w = self.left + weeks * (CELL + GAP) - GAP
        h = self.top + 7 * (CELL + GAP) - GAP + self.legend_h
        super().__init__(parent, width=w, height=h, bg=app.P["card"], highlightthickness=0, bd=0)
        self.cells = {}
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._leave())
        self.bind("<ButtonRelease-1>", self._click)

    # ------------------------------------------------------------------ data
    def set_data(self, rows):
        """rows: store.daily() tuples (day, chars, seconds, lines)."""
        self.data = {d: (c or 0, s or 0) for d, c, s, n in rows}
        self.draw()

    def _levels(self):
        goal = goals.daily_goal(self.app.cfg)
        if goal:
            ref = goal
        else:
            vals = sorted(c for c, s in self.data.values() if c > 0)
            ref = max(vals[min(len(vals) - 1, int(len(vals) * 0.9))], 1) if vals else 1  # your 90th percentile day
        return goal, ref

    def level(self, v, ref):
        if v <= 0:
            return 0
        r = v / ref
        return 1 if r < 0.25 else 2 if r < 0.5 else 3 if r < 1 else 4

    def color(self, lv):
        P = self.P
        if lv == 0:
            return mix(P["line"], P["card"], 0.25)
        return mix(P["line"], P["accent"], LEVEL_MIX[lv])

    # ------------------------------------------------------------------ drawing
    def draw(self):
        P, F, cv = self.P, self.F, self
        cv.delete("all")
        self.cells.clear()
        cfg = self.app.cfg
        today = goals.logical_today(cfg)
        ws_today = goals.week_start_day(cfg, today)
        first = ws_today - dt.timedelta(days=7 * (self.weeks - 1))
        goal, ref = self._levels()
        step = CELL + GAP
        r = rad(4)
        sunday = cfg.get("week_starts") == "sunday"
        # weekday labels (M / W / F)
        for row, lab in ((1, "M"), (3, "W"), (5, "F")) if sunday else ((0, "M"), (2, "W"), (4, "F")):
            cv.create_text(self.left - 7, self.top + row * step + CELL / 2, text=lab, fill=P["dim"], anchor="e",
                           font=F["xs"])
        last_month, last_x = None, -99
        for col in range(self.weeks):
            ws = first + dt.timedelta(days=7 * col)
            x0 = self.left + col * step
            m = (ws + dt.timedelta(days=3)).month
            if m != last_month:
                if last_month is not None or col == 0:
                    if last_x < 0 or x0 - last_x >= F["xs"].measure("Mar") + 6:
                        cv.create_text(x0, 2, text=(ws + dt.timedelta(days=3)).strftime("%b"), fill=P["dim"],
                                       anchor="nw", font=F["xs"])
                        last_x = x0
                last_month = m
            for row in range(7):
                d = ws + dt.timedelta(days=row)
                if d > today:
                    break
                y0 = self.top + row * step
                c, s = self.data.get(d.isoformat(), (0, 0))
                fill = self.color(self.level(c, ref))
                met = goal > 0 and c >= goal
                outline = P["good"] if met else (P["dim"] if d == today else fill)
                item = rounded_rect(cv, x0, y0, x0 + CELL, y0 + CELL, r, fill=fill, outline=outline,
                                    width=1, tags=("cell",))
                self.cells[item] = d
        # legend: less [5 squares] more   and the goal outline key
        ly = self.top + 7 * step - GAP + 10
        x = self.left
        cv.create_text(x, ly + 5, text="less", fill=P["dim"], anchor="w", font=F["xs"])
        x += F["xs"].measure("less") + 6
        for lv in range(5):
            rounded_rect(cv, x, ly, x + 10, ly + 10, rad(3), fill=self.color(lv), outline=self.color(lv))
            x += 13
        cv.create_text(x + 3, ly + 5, text="more", fill=P["dim"], anchor="w", font=F["xs"])
        x += F["xs"].measure("more") + 18
        if goal:
            rounded_rect(cv, x, ly, x + 10, ly + 10, rad(3), fill=self.color(4), outline=P["good"], width=1)
            cv.create_text(x + 16, ly + 5, text="goal met", fill=P["dim"], anchor="w", font=F["xs"])

    # ------------------------------------------------------------------ interaction
    def _day_at(self, e):
        for item in self.find_overlapping(e.x, e.y, e.x, e.y):
            if item in self.cells:
                return item, self.cells[item]
        return None, None

    def _motion(self, e):
        item, d = self._day_at(e)
        if d is None:
            self._leave()
            return
        self.configure(cursor="hand2" if self.on_click else "")
        if getattr(self, "_tip_day", None) == d:
            return
        self._tip_day = d
        lib, P, F = self.app.lib, self.P, self.F
        c, s = self.data.get(d.isoformat(), (0, 0))
        text = d.strftime("%a %b %d")
        text += f" · {lib.fmt_int(c)} 字 · {lib.fmt_dur(s)}" if c else " · no reading"
        self.delete("tip")
        t = self.create_text(0, 0, text=text, font=F["sm"], fill=P["fg"], tags="tip")
        x0, y0, x1, y1 = self.bbox(t)
        tw, th = x1 - x0, y1 - y0
        bx0, by0, bx1, by1 = self.bbox(item)
        W = int(self["width"])
        cx = min(max((bx0 + bx1) / 2, tw / 2 + 12), W - tw / 2 - 12)
        cy = by0 - th / 2 - 12
        if cy < th / 2 + 4:
            cy = by1 + th / 2 + 12
        self.coords(t, cx, cy)
        rr = rounded_rect(self, cx - tw / 2 - 9, cy - th / 2 - 4, cx + tw / 2 + 9, cy + th / 2 + 4, rad(9),
                          fill=P["card2"], outline=P["line"], tags="tip")
        self.tag_lower(rr, t)

    def _leave(self):
        self._tip_day = None
        self.delete("tip")
        self.configure(cursor="")

    def _click(self, e):
        _, d = self._day_at(e)
        if d is not None and self.on_click:
            self.on_click(d.isoformat())
