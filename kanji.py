"""Unique kanji seen: which kanji you met, how often, and when each was first seen.

No GUI, no `import tracker` (takes the Store object). Tables (created by `ensure`):
  kanji_seen(game, ch, first_ts, count)   per game key; PRIMARY KEY(game, ch)
  kanji_meta(k, v)                         sync bookkeeping: last_id, n_lines
`sync(store)` is incremental (only lines newer than last_id). If lines were deleted since the last sync (the
count of old lines changed), it rebuilds the whole table from `lines`. First call = one-time backfill.
Manual entries ("[manual] note", game key manual:*) are never scanned.
Per-VN means per Library group (VNDB id, or "name:<title>"), same grouping as Store.library().
"""
import datetime as dt
import re

# BMP kanji only (Tk 8.6 can't draw anything above U+FFFF): CJK ext A, unified, compatibility.
KANJI_RE = re.compile("[㐀-䶿一-鿿豈-﫿]")
GRP = "COALESCE(g.vndb_id, 'name:' || COALESCE(g.name, k.game))"
MANUAL_SQL = "game NOT LIKE 'manual:%' AND text NOT LIKE '[manual]%'"


def ensure(store):
    store.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS kanji_seen(
            game TEXT NOT NULL, ch TEXT NOT NULL, first_ts REAL NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY(game, ch));
        CREATE INDEX IF NOT EXISTS idx_kanji_first ON kanji_seen(first_ts);
        CREATE INDEX IF NOT EXISTS idx_kanji_ch ON kanji_seen(ch);
        CREATE TABLE IF NOT EXISTS kanji_meta(k TEXT PRIMARY KEY, v INTEGER);
        """)
    store.db.commit()


def _meta(store, k, default=None):
    r = store.db.execute("SELECT v FROM kanji_meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def _set_meta(store, k, v):
    store.db.execute("INSERT OR REPLACE INTO kanji_meta(k, v) VALUES(?,?)", (k, v))


def kanji_in(text):
    return KANJI_RE.findall(text or "")


def _add_rows(store, rows):
    """rows: iterable of (ts, game, text). Upserts counts and first_ts."""
    acc = {}
    for ts, game, text in rows:
        for ch in kanji_in(text):
            cur = acc.get((game, ch))
            if cur is None:
                acc[(game, ch)] = [ts, 1]
            else:
                cur[0] = min(cur[0], ts)
                cur[1] += 1
    for (game, ch), (ts, n) in acc.items():
        store.db.execute(
            "INSERT INTO kanji_seen(game, ch, first_ts, count) VALUES(?,?,?,?) "
            "ON CONFLICT(game, ch) DO UPDATE SET count=count+excluded.count, "
            "first_ts=MIN(first_ts, excluded.first_ts)", (game, ch, ts, n))


def rebuild(store):
    """Recomputes everything from the lines table (backfill / after deletions)."""
    ensure(store)
    store.db.execute("DELETE FROM kanji_seen")
    rows = store.db.execute(f"SELECT ts, game, text FROM lines WHERE {MANUAL_SQL} ORDER BY ts").fetchall()
    _add_rows(store, rows)
    _stamp(store)
    store.db.commit()


def _stamp(store):
    n, mx = store.db.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM lines").fetchone()
    r = store.db.execute("SELECT ts FROM lines WHERE id=?", (mx,)).fetchone()
    _set_meta(store, "n_lines", n)
    _set_meta(store, "last_id", mx)
    _set_meta(store, "last_ts", r[0] if r else 0)


def sync(store):
    """Brings the kanji table up to date. Returns the number of lines newly scanned (-1 after a rebuild)."""
    ensure(store)
    last = _meta(store, "last_id")
    if last is None:
        rebuild(store)
        return -1
    n_old = _meta(store, "n_lines", 0)
    n = store.db.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
    new_n = store.db.execute("SELECT COUNT(*) FROM lines WHERE id>?", (last,)).fetchone()[0]
    tail = store.db.execute("SELECT ts FROM lines WHERE id=?", (last,)).fetchone()
    tail_ok = (tail is None and n_old == 0) or (tail is not None and tail[0] == _meta(store, "last_ts"))
    if n - new_n != n_old or not tail_ok:  # lines were deleted (undo, delete group...): counts would be stale
        rebuild(store)
        return -1
    if not new_n:
        return 0
    rows = store.db.execute(f"SELECT ts, game, text FROM lines WHERE id>? AND {MANUAL_SQL} ORDER BY id",
                            (last,)).fetchall()
    _add_rows(store, rows)
    _stamp(store)
    store.db.commit()
    return new_n


# ------------------------------------------------------------------ queries (all call sync first; it's cheap)
def unique_count(store, grp=None):
    sync(store)
    if grp is None:
        return store.db.execute("SELECT COUNT(DISTINCT ch) FROM kanji_seen").fetchone()[0]
    return store.db.execute(
        f"SELECT COUNT(DISTINCT k.ch) FROM kanji_seen k LEFT JOIN games g ON g.key=k.game WHERE {GRP}=?",
        (grp,)).fetchone()[0]


def per_vn_counts(store):
    """{grp: unique kanji count}."""
    sync(store)
    return dict(store.db.execute(
        f"SELECT {GRP}, COUNT(DISTINCT k.ch) FROM kanji_seen k LEFT JOIN games g ON g.key=k.game GROUP BY 1"
    ).fetchall())


def kanji_list(store, grp=None, sort="first"):
    """[(ch, first_ts, count, first_game_name)] for everything (grp=None) or one Library group.
    first_ts / count are within the chosen scope. sort: "first" (newest first), "oldest", "freq", "rare"."""
    sync(store)
    where, args = "", []
    if grp is not None:
        where, args = f"WHERE {GRP}=?", [grp]
    rows = store.db.execute(
        f"""SELECT k.ch, MIN(k.first_ts), SUM(k.count),
                   (SELECT COALESCE(g2.name, k2.game) FROM kanji_seen k2 LEFT JOIN games g2 ON g2.key=k2.game
                    WHERE k2.ch=k.ch ORDER BY k2.first_ts LIMIT 1)
            FROM kanji_seen k LEFT JOIN games g ON g.key=k.game {where} GROUP BY k.ch""", args).fetchall()
    keyf = {"first": lambda r: (-r[1], r[0]), "oldest": lambda r: (r[1], r[0]),
            "freq": lambda r: (-r[2], r[0]), "rare": lambda r: (r[2], r[0])}.get(sort, lambda r: (-r[1], r[0]))
    return sorted(rows, key=keyf)


def new_between(store, since, until=None):
    """Kanji whose very first sighting (any game) falls in [since, until]; list of (first_ts, ch)."""
    sync(store)
    until = float("inf") if until is None else until
    rows = store.db.execute("SELECT ch, MIN(first_ts) f FROM kanji_seen GROUP BY ch").fetchall()
    return sorted((f, ch) for ch, f in rows if since <= f <= until)


def new_per_day(store, days=30):
    """[(day_iso, new kanji count)] newest first, counting each kanji on the day it was first seen overall
    (days follow store.cfg day_start_hour)."""
    sync(store)
    h = int(store.cfg.get("day_start_hour", 4))
    rows = store.db.execute(
        f"SELECT date(f, 'unixepoch', 'localtime', '-{h} hours') d, COUNT(*) FROM "
        "(SELECT MIN(first_ts) f FROM kanji_seen GROUP BY ch) GROUP BY d ORDER BY d DESC LIMIT ?",
        (int(days),)).fetchall()
    return rows


def new_per_vn_day(store, grp, days=30):
    """Same as new_per_day but kanji new to this VN (first sighting within the group)."""
    rows = kanji_list(store, grp, "first")
    h = int(store.cfg.get("day_start_hour", 4))
    out = {}
    for ch, ts, n, _ in rows:
        d = (dt.datetime.fromtimestamp(ts) - dt.timedelta(hours=h)).date().isoformat()
        out[d] = out.get(d, 0) + 1
    return sorted(out.items(), reverse=True)[:days]


def new_today(store):
    return len(new_between(store, store.day_start_epoch()))
