"""Daily / weekly goals: week boundaries, weekly totals, overlay goal bars and milestone toasts.

No GUI and no `import tracker` (see UI_CONTRACT.md). Weeks follow `day_start_hour` like days do:
the day before `day_start_hour` still belongs to the previous day, so a week starts at
`day_start_hour` o'clock on its first day (Monday or Sunday, `week_starts`).
"""
import datetime as dt


def day_start_hour(cfg) -> int:
    try:
        return int(cfg.get("day_start_hour", 4))
    except (TypeError, ValueError):
        return 4


def logical_today(cfg, now=None) -> dt.date:
    """The reading day `now` belongs to (before day_start_hour it is still yesterday)."""
    return ((now or dt.datetime.now()) - dt.timedelta(hours=day_start_hour(cfg))).date()


def week_start_day(cfg, day: dt.date) -> dt.date:
    """First day of the week containing `day`; `week_starts` is "monday" (default) or "sunday"."""
    back = (day.weekday() + 1) % 7 if cfg.get("week_starts") == "sunday" else day.weekday()
    return day - dt.timedelta(days=back)


def week_start_epoch(cfg, now=None) -> float:
    ws = week_start_day(cfg, logical_today(cfg, now))
    return (dt.datetime.combine(ws, dt.time()) + dt.timedelta(hours=day_start_hour(cfg))).timestamp()


def daily_goal(cfg) -> int:
    try:
        return max(0, int(cfg.get("daily_goal") or 0))
    except (TypeError, ValueError):
        return 0


def weekly_goal(cfg) -> int:
    try:
        return max(0, int(cfg.get("weekly_goal") or 0))
    except (TypeError, ValueError):
        return 0


def week_total(store, now=None) -> tuple:
    """(characters, seconds) read this week so far."""
    return store.sum_since(week_start_epoch(store.cfg, now))


def week_summary(store, now=None) -> dict:
    cfg = store.cfg
    chars, secs = week_total(store, now)
    goal = weekly_goal(cfg)
    start = week_start_day(cfg, logical_today(cfg, now))
    return {"chars": chars, "seconds": secs, "goal": goal, "start": start,
            "frac": min(1.0, chars / goal) if goal else 0.0}


def overlay_bars(cfg, store, today_chars: int, now=None) -> list:
    """Fractions (0..1) of the overlay goal bar(s) to show: [] (none), one bar, or two ("both").
    overlay_goal_mode daily|weekly|both. With "daily" and no daily goal but a weekly one, the weekly bar shows."""
    mode = cfg.get("overlay_goal_mode")
    if mode not in ("daily", "weekly", "both"):
        mode = "daily"
    dg, wg = daily_goal(cfg), weekly_goal(cfg)
    want_d = dg > 0 and mode in ("daily", "both")
    want_w = wg > 0 and mode in ("weekly", "both")
    if not want_d and not want_w and mode == "daily" and wg > 0:
        want_w = True
    bars = []
    if want_d:
        bars.append(min(1.0, today_chars / dg))
    if want_w:
        bars.append(min(1.0, week_total(store, now)[0] / wg))
    return bars


def check_milestones(app, today_chars: int, now=None) -> None:
    """Toasts (app.status) the first time the daily goal is reached each day and the weekly goal each week.
    Quiet when nothing was read since the last check (app just started, goal lowered in Settings)."""
    cfg, store = app.cfg, app.store
    dg, wg = daily_goal(cfg), weekly_goal(cfg)
    if dg <= 0 and wg <= 0:
        app._goal_prev = None
        return
    w_chars = week_total(store, now)[0] if wg > 0 else 0
    today = logical_today(cfg, now).isoformat()
    week = week_start_day(cfg, logical_today(cfg, now)).isoformat()
    prev = getattr(app, "_goal_prev", None)
    app._goal_prev = (today_chars, w_chars)
    d_hit = dg > 0 and today_chars >= dg and cfg.get("goal_toast_day") != today
    w_hit = wg > 0 and w_chars >= wg and cfg.get("goal_toast_week") != week
    if not (d_hit or w_hit):
        return
    if d_hit:
        cfg["goal_toast_day"] = today
    if w_hit:
        cfg["goal_toast_week"] = week
    app.save_config()
    if prev is None or not (today_chars > prev[0] or w_chars > prev[1]):
        return
    sym = app.sym()
    tail = f" {sym}" if sym else ""
    if d_hit and w_hit:
        msg = f"daily + weekly goals reached!{tail}"
    elif w_hit:
        msg = ("weekly goal reached, what a week!" if app.cute() else "weekly goal reached!") + tail
    else:
        msg = ("daily goal reached, nice work!" if app.cute() else "daily goal reached!") + tail
    app.status(msg, 6000)
