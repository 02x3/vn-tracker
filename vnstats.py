"""Per-VN reading speed over time (for the VN detail chart). No GUI, no `import tracker`.

    speed_by_session(store, grp) -> [(start_ts, chars, seconds, chars_per_hour)]  oldest first
    speed_by_day(store, grp)     -> [(day_iso, chars, seconds, chars_per_hour)]   oldest first
Points with less than MIN_SECONDS of reading time are left out (their speed is meaningless).
`grp` is a Library group (VNDB id or "name:<title>"); manual entries are skipped (their time is a guess).
"""
MIN_SECONDS = 120


def _keys(store, grp):
    return [k for k in store.group_keys(grp) if not k.startswith("manual:")]


def speed_by_session(store, grp, limit=60):
    keys = set(_keys(store, grp))
    out = []
    for s in store.sessions(5000):
        if s["game"] in keys and s["seconds"] >= MIN_SECONDS and s["reason"] != "manual":
            out.append((s["start"], s["chars"], s["seconds"], s["chars"] * 3600.0 / s["seconds"]))
    out.sort()
    return out[-limit:]


def speed_by_day(store, grp, limit=60):
    keys = _keys(store, grp)
    if not keys:
        return []
    q = ",".join("?" * len(keys))
    rows = store.db.execute(
        f"SELECT {store._day_expr()} d, SUM(chars), SUM(seconds) FROM lines WHERE game IN ({q}) "
        "AND text NOT LIKE '[manual]%' GROUP BY d ORDER BY d", keys).fetchall()
    out = [(d, c, s, c * 3600.0 / s) for d, c, s in rows if s and s >= MIN_SECONDS]
    return out[-limit:]


def summary(store, grp):
    """{sessions, first, last, avg_speed} for the detail window (speed = chars/hour over measured time)."""
    keys = _keys(store, grp)
    if not keys:
        return dict(sessions=0, first=None, last=None, avg_speed=None)
    q = ",".join("?" * len(keys))
    c, s, a, b = store.db.execute(
        f"SELECT COALESCE(SUM(chars),0), COALESCE(SUM(seconds),0), MIN(ts), MAX(ts) FROM lines WHERE game IN ({q})",
        keys).fetchone()
    n = sum(1 for x in store.sessions(5000) if x["game"] in set(keys))
    return dict(sessions=n, first=a, last=b, avg_speed=(c * 3600.0 / s) if s >= MIN_SECONDS else None)
