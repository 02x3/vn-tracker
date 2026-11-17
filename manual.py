"""Manual reading entries (phone, manga, a VN without a usable text box) and per-day line lookups.

A manual entry is a normal `lines` row with text "[manual] note", stored under a dedicated game key
`manual:log:<group>` so it merges into the same Library card (same vndb_id / same name) but never
mixes with that game's OCR sessions. It also gets a matching `sessions` row with reason "manual".
No GUI, no `import tracker`.
"""
import datetime as dt
import time

TAG = "[manual]"
KEY_PREFIX = "manual:log:"


def is_manual(text) -> bool:
    return (text or "").startswith(TAG)


def display_text(text) -> str:
    """"[manual] note" -> "manual · note" (for the Lines page)."""
    if not is_manual(text):
        return text or ""
    note = text[len(TAG):].strip()
    return "manual · " + note if note else "manual"


def entry_timestamp(cfg, day: dt.date, now=None) -> float:
    """Where on the timeline a manual entry for `day` sits: mid-afternoon of that reading day
    (or right now if that is still in the future, i.e. today before then)."""
    h = int(cfg.get("day_start_hour", 4))
    t = (dt.datetime.combine(day, dt.time()) + dt.timedelta(hours=h + 12)).timestamp()
    return min(t, now if now is not None else time.time())


def add_entry(store, grp, name, chars, minutes, day, note="", now=None):
    """Adds a manual entry to library group `grp` (a vndb id or "name:<title>"); with grp None it is a
    new / other title called `name`. Returns (game_key, line_id)."""
    chars = int(chars)
    if chars <= 0:
        raise ValueError("characters must be positive")
    minutes = max(0.0, float(minutes or 0))
    if not grp:
        name = (name or "").strip()
        if not name:
            raise ValueError("name needed")
        grp = "name:" + name
    key = KEY_PREFIX + grp
    store.ensure_game(key, name or grp)
    if grp.startswith("name:"):
        store.db.execute("UPDATE games SET name=?, vndb_id=NULL, matched=-1 WHERE key=?", (grp[5:], key))
    else:
        vn = store.vn(grp)
        store.db.execute("UPDATE games SET name=?, vndb_id=?, matched=2 WHERE key=?",
                         ((vn or {}).get("title") or name or grp, grp, key))
    store.db.commit()
    ts = entry_timestamp(store.cfg, day, now)
    while store.db.execute("SELECT 1 FROM lines WHERE game=? AND ts=?", (key, ts)).fetchone():
        ts += 0.01  # a manual session is a single instant, so its window must not catch another entry
    text = (TAG + " " + (note or "").strip()).strip()
    lid = store.add_line(ts, key, chars, minutes * 60, text)
    sid = store.start_session(key, ts)
    store.end_session(sid, ts, "manual")
    return key, lid


def cleanup(store) -> None:
    """After lines were deleted: drop manual sessions that lost their line, and empty manual game keys
    (so a deleted-out entry does not leave a 0-character card behind)."""
    store.db.execute(
        "DELETE FROM sessions WHERE reason='manual' AND NOT EXISTS (SELECT 1 FROM lines l WHERE l.game=sessions.game"
        " AND l.ts BETWEEN sessions.start_ts AND sessions.end_ts)")
    store.db.execute("DELETE FROM games WHERE key LIKE 'manual:log:%' AND key NOT IN (SELECT DISTINCT game FROM lines)")
    store.db.commit()


def lines_for_day(store, day_iso: str, limit: int = 2000) -> list:
    """Same tuples as Store.recent_lines(), but only the lines of one reading day (YYYY-MM-DD)."""
    return store.db.execute(
        f"""SELECT l.id, l.ts, COALESCE(g.name, l.game), l.chars, l.seconds, l.text
            FROM lines l LEFT JOIN games g ON g.key=l.game
            WHERE {store._day_expr()}=? ORDER BY l.id DESC LIMIT ?""", (day_iso, limit)).fetchall()


def parse_day(text: str, today: dt.date):
    """Date field: YYYY-MM-DD, MM-DD, MM/DD, or "today" / "yesterday". Returns a date or None."""
    s = (text or "").strip().lower()
    if s in ("today", ""):
        return today
    if s == "yesterday":
        return today - dt.timedelta(days=1)
    s = s.replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%m-%d"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        return d.replace(year=today.year) if fmt == "%m-%d" else d
    return None
