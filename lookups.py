"""Dictionary lookups per VN (a difficulty signal). No GUI and no `import tracker`.

Every time meikipop's popup appears over the text box (rising edge, debounced) while a game is being read,
one row goes into table `lookups(id, ts, game)` (game = the game key, like `lines.game`). Per VN we show
the count and lookups per 1,000 characters; Stats shows an overall tile and a weekly trend.

The popup edge detection (`PopupEdge`) is fed by the OCR watcher thread; counting happens on the UI thread
(`count_popup(app)`), which refuses while paused or when no game is being read.
"""
import datetime as dt
import time

DEBOUNCE = 1.0          # popup gone for less than this = same appearance
ACTIVE_GAP = 1800       # a game counts as "being read" if its last line is at most this many seconds old
MIN_CHARS = 300         # per-1k figures need at least this many characters to mean anything


class PopupEdge:
    """Turns a per-tick 'is the popup covering the box' signal into one event per appearance."""

    def __init__(self, debounce=DEBOUNCE):
        self.debounce = debounce
        self.last_seen = None   # last time the popup was seen covering

    def feed(self, blocked, now=None):
        """True exactly when a new appearance starts (popup seen after being gone for > debounce)."""
        now = time.monotonic() if now is None else now
        if not blocked:
            return False
        fresh = self.last_seen is None or now - self.last_seen > self.debounce
        self.last_seen = now
        return fresh


# ------------------------------------------------------------------ storage
def ensure(store):
    if getattr(store, "_lookups_ready", False):
        return
    store.db.execute("CREATE TABLE IF NOT EXISTS lookups(id INTEGER PRIMARY KEY, ts REAL NOT NULL, game TEXT NOT NULL)")
    store.db.execute("CREATE INDEX IF NOT EXISTS idx_lookups_ts ON lookups(ts)")
    store.db.execute("CREATE INDEX IF NOT EXISTS idx_lookups_game ON lookups(game)")
    store.db.commit()
    store._lookups_ready = True


def add(store, game, ts=None):
    ensure(store)
    store.db.execute("INSERT INTO lookups(ts, game) VALUES(?,?)", (ts if ts is not None else time.time(), game))
    store.db.commit()


def delete_games(store, keys):
    """Drops the lookups of removed game keys (call after deleting a library entry)."""
    ensure(store)
    store.db.executemany("DELETE FROM lookups WHERE game=?", [(k,) for k in keys])
    store.db.commit()


def game_active(app, now=None):
    """The game key lookups belong to right now, or None (paused, nothing read recently, lookups off)."""
    t = app.tracker
    if not app.cfg.get("lookups_enabled", True) or t.paused:
        return None
    key = t.locked_game or t.last_game
    if not key or key == "unknown" or not app.store.has_game(key):
        return None
    now = time.time() if now is None else now
    if t.last_ts is not None and now - t.last_ts > ACTIVE_GAP:
        return None
    return key


def count_popup(app, now=None):
    """One popup appearance seen over the text box. Returns the game key it was counted for, or None."""
    key = game_active(app, now)
    if key:
        add(app.store, key, now)
    return key


# SQL: library group of a game key, same rule as tracker.GROUP_SQL
_GRP = "COALESCE(g.vndb_id, 'name:' || g.name)"


def by_group(store):
    """{library group: lookup count}."""
    ensure(store)
    rows = store.db.execute(
        f"SELECT {_GRP}, COUNT(*) FROM lookups k JOIN games g ON g.key=k.game GROUP BY 1").fetchall()
    return {g: n for g, n in rows}


def total(store):
    ensure(store)
    return store.db.execute("SELECT COUNT(*) FROM lookups k JOIN games g ON g.key=k.game").fetchone()[0]


def per_1k(count, chars):
    """Lookups per 1,000 characters, or None when there is too little text to say."""
    if not chars or chars < MIN_CHARS:
        return None
    return count * 1000.0 / chars


def fmt_rate(rate):
    if rate is None:
        return "-"
    return f"{rate:.1f}" if rate < 100 else f"{rate:.0f}"


def card_text(count, chars):
    """Library card line, e.g. "12 lookups · 3.4 / 1k 字". '' when nothing was looked up."""
    if not count:
        return ""
    r = per_1k(count, chars)
    s = f"{count} lookup{'s' if count != 1 else ''}"
    return s + (f" · {fmt_rate(r)} / 1k 字" if r is not None else "")


def overall(store):
    """(lookups, chars, per_1k) over everything (only lookups of known games count)."""
    chars = store.db.execute("SELECT COALESCE(SUM(chars),0) FROM lines").fetchone()[0]
    n = total(store)
    return n, chars, per_1k(n, chars)


def _week_start(day, week_starts):
    back = day.weekday() if week_starts != "sunday" else (day.weekday() + 1) % 7
    return day - dt.timedelta(days=back)


def weekly(store, grp=None, weeks=12, week_starts="monday"):
    """Per week (oldest first, `weeks` entries ending with this week): [(week_start date, lookups, chars, per_1k)].
    grp = a library group (vndb id / "name:<title>") or None for everything. Weeks follow day_start_hour."""
    ensure(store)
    day = store._day_expr()
    keys = None
    if grp:
        keys = store.group_keys(grp)
        if not keys:
            keys = ["\0none"]
    cond, args = "", []
    if keys is not None:
        cond = " AND game IN (%s)" % ",".join("?" * len(keys))
        args = list(keys)
    chars = {d: c for d, c in store.db.execute(
        f"SELECT {day}, SUM(chars) FROM lines WHERE 1=1{cond} GROUP BY 1", args)}
    looks = {d: c for d, c in store.db.execute(
        f"SELECT {day}, COUNT(*) FROM lookups WHERE game IN (SELECT key FROM games){cond} GROUP BY 1", args)}
    today = dt.date.fromisoformat(store.today_str())
    this = _week_start(today, week_starts)
    out = {}
    for i in range(weeks):
        out[this - dt.timedelta(days=7 * (weeks - 1 - i))] = [0, 0]
    for src, idx in ((chars, 1), (looks, 0)):
        for d, v in src.items():
            try:
                w = _week_start(dt.date.fromisoformat(d), week_starts)
            except (TypeError, ValueError):
                continue
            if w in out:
                out[w][idx] += v or 0
    return [(w, n, c, per_1k(n, c)) for w, (n, c) in sorted(out.items())]
