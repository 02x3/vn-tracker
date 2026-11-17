"""Progress per VN: total characters (yours, from jiten.moe, or an estimate), percent read, time left.

Table `vn_totals(vid, total_chars, source, fetched_at)`; vid is the VNDB id (or the library group key
"name:<title>" for a VN without a VNDB match, which can only have a user-set total).
source: "user" (set by hand, wins), "jiten" (character count from jiten.moe), "none" (jiten has no count;
re-checked after RETRY_NONE_DAYS). The "≈ estimate" (VNDB length_minutes x CPM_DEFAULT chars/min, cfg "chars_per_minute") is never stored.

jiten.moe: public JSON API https://api.jiten.moe (OpenAPI at /swagger/v1/swagger.json, MIT-licensed project,
no key for read endpoints):
  GET /api/media-deck/by-link-id/2/{vndb id}  -> [deckId, ...]        (link type 2 = VNDB)
  GET /api/media-deck/{deckId}/detail         -> data.mainDeck.characterCount
Requests are sequential with a pause, a few VNs per batch, and every result is cached in the DB.
No GUI and no `import tracker`: the HTTP function comes from the caller (`app.lib._http`).
"""
import json
import re
import time

API = "https://api.jiten.moe"
VNDB_ID_RE = re.compile(r"^v\d+$")
RETRY_NONE_DAYS = 14        # a VN jiten doesn't know is looked up again after this long
REFRESH_DAYS = 120          # a known count is refreshed this rarely
FAIL_BACKOFF = 600          # seconds before retrying a VN whose request failed (offline etc.)
BATCH = 3                   # VNs per worker job
PAUSE = 0.6                 # seconds between requests (be gentle to a free community API)
CPM_DEFAULT = 450           # characters per VNDB "length minute" (voiced play time), for the estimate
MIN_SPEED_SECONDS = 600    # a VN needs this much reading time before its own speed is trusted


# ------------------------------------------------------------------ storage
def ensure(store) -> None:
    if getattr(store, "_totals_ready", False):
        return
    store.db.execute(
        """CREATE TABLE IF NOT EXISTS vn_totals(
               vid TEXT PRIMARY KEY, total_chars INTEGER, source TEXT, fetched_at REAL)""")
    store.db.commit()
    store._totals_ready = True


def all_totals(store) -> dict:
    ensure(store)
    return {v: dict(vid=v, total=t, source=s, fetched=f)
            for v, t, s, f in store.db.execute("SELECT vid, total_chars, source, fetched_at FROM vn_totals")}


def set_user_total(store, vid: str, total) -> None:
    """A positive number sets your own total; 0 / None clears it (online / estimate apply again)."""
    ensure(store)
    if total and int(total) > 0:
        store.db.execute("INSERT OR REPLACE INTO vn_totals VALUES(?,?,?,?)", (vid, int(total), "user", time.time()))
    else:
        store.db.execute("DELETE FROM vn_totals WHERE vid=? AND source='user'", (vid,))
    store.db.commit()


def save_online(store, vid: str, total, source="jiten") -> None:
    """Caches a lookup result (never overwrites a user-set total)."""
    ensure(store)
    row = store.db.execute("SELECT source FROM vn_totals WHERE vid=?", (vid,)).fetchone()
    if row and row[0] == "user":
        return
    if total and int(total) > 0:
        store.db.execute("INSERT OR REPLACE INTO vn_totals VALUES(?,?,?,?)", (vid, int(total), source, time.time()))
    else:
        store.db.execute("INSERT OR REPLACE INTO vn_totals VALUES(?,?,?,?)", (vid, None, "none", time.time()))
    store.db.commit()


def forget_online(store, vid: str) -> None:
    ensure(store)
    store.db.execute("DELETE FROM vn_totals WHERE vid=? AND source!='user'", (vid,))
    store.db.commit()


# ------------------------------------------------------------------ jiten.moe (worker thread: no DB access)
def fetch_jiten(vid: str, http, pause: float = PAUSE):
    """Character count of a VN on jiten.moe, or None if it isn't there. `http(url)` returns bytes.
    Network errors raise (the caller then retries later instead of caching a miss)."""
    ids = json.loads(http(f"{API}/api/media-deck/by-link-id/2/{vid}"))
    best = None
    for did in (ids or [])[:3]:
        time.sleep(pause)
        deck = (json.loads(http(f"{API}/api/media-deck/{did}/detail")).get("data") or {}).get("mainDeck") or {}
        n = int(deck.get("characterCount") or 0)
        if n > 0 and (best is None or deck.get("mediaType") == 7):
            best = n
            if deck.get("mediaType") == 7:
                break
    return best


def pending(store, now=None) -> list:
    """VNDB ids in the library that still need a jiten lookup (missing, or the cached answer is stale)."""
    ensure(store)
    now = now or time.time()
    have = all_totals(store)
    out = []
    for (vid,) in store.db.execute("SELECT DISTINCT vndb_id FROM games WHERE vndb_id IS NOT NULL"):
        if not VNDB_ID_RE.match(vid or ""):
            continue
        row = have.get(vid)
        if row is None:
            out.append(vid)
        elif row["source"] == "none" and now - row["fetched"] > RETRY_NONE_DAYS * 86400:
            out.append(vid)
        elif row["source"] == "jiten" and now - row["fetched"] > REFRESH_DAYS * 86400:
            out.append(vid)
    return out


def start_fetch(app) -> None:
    """Looks up missing totals in the background: BATCH VNs per worker job, then the next batch a moment later.
    Safe to call often; does nothing while a run is active. Calls app.data_changed() when something was learned."""
    if getattr(app, "_totals_running", False):
        return
    failed = getattr(app, "_totals_failed", None)
    if failed is None:
        failed = app._totals_failed = {}
    now = time.time()
    todo = [v for v in pending(app.store, now) if now - failed.get(v, 0) > FAIL_BACKOFF]
    if not todo:
        return
    app._totals_running = True
    batch = todo[:BATCH]
    http = app.lib._http

    def job():
        res = {}
        for vid in batch:
            try:
                res[vid] = ("ok", fetch_jiten(vid, http))
            except Exception as e:  # noqa: BLE001 - offline, rate limited...: retry later
                res[vid] = ("err", str(e))
            time.sleep(PAUSE)
        return res

    def done(res, err):
        app._totals_running = False
        learned = False
        for vid, (kind, val) in (res or {}).items():
            if kind == "ok":
                save_online(app.store, vid, val)
                learned = learned or bool(val)
            else:
                failed[vid] = time.time()
        if learned:
            app.data_changed()
        more = [v for v in pending(app.store) if time.time() - failed.get(v, 0) > FAIL_BACKOFF]
        if more and not err:
            try:
                app.root.after(1500, lambda: start_fetch(app))
            except Exception:  # noqa: BLE001 - window closing
                pass

    app.worker.submit(job, done)


# ------------------------------------------------------------------ the numbers shown on a Library card
def speed_per_second(item, overall_chars, overall_seconds):
    """chars/second from this VN if it has enough reading time, else the overall average, else None."""
    if item["seconds"] >= MIN_SPEED_SECONDS and item["chars"] > 0:
        return item["chars"] / item["seconds"]
    if overall_seconds >= MIN_SPEED_SECONDS and overall_chars > 0:
        return overall_chars / overall_seconds
    return None


def card_progress(item, totals, overall_chars, overall_seconds, cpm=None):
    """What a Library card shows, or None for nothing.
    {frac, pct, source: user|jiten|estimate|finished, total, left_seconds, estimate: bool}
    Estimate = VNDB length_minutes x `cpm` characters per minute (default CPM_DEFAULT; cfg "chars_per_minute")."""
    finished = item["status"] == "Finished"
    if not finished and not item["chars"]:
        return None
    vid = item["vn"]["id"] if item.get("vn") else item["grp"]
    row = totals.get(vid)
    total, source = None, None
    if row and row["total"]:
        total, source = row["total"], row["source"]
    spd = speed_per_second(item, overall_chars, overall_seconds)
    if total is None:
        mins = (item.get("vn") or {}).get("length_minutes")
        if mins:
            total, source = int(mins * (cpm if cpm and cpm > 0 else CPM_DEFAULT)), "estimate"
    if finished:
        return dict(frac=1.0, pct=100, source=source or "finished", total=total, left_seconds=0,
                    estimate=source == "estimate", finished=True)
    if not total:
        return None
    frac = min(0.99, item["chars"] / total)
    left = max(0, total - item["chars"]) / spd if spd else None
    return dict(frac=frac, pct=int(frac * 100), source=source, total=total, left_seconds=left,
                estimate=source == "estimate", finished=False)


def fmt_left(seconds) -> str:
    if seconds is None:
        return ""
    if seconds >= 3600:
        h = seconds / 3600
        return f"~{h:.0f}h left" if h >= 10 else f"~{h:.1f}h".replace(".0h", "h") + " left"
    return f"~{max(1, round(seconds / 60))}m left"


def card_texts(prog, fmt_int):
    """(main line, small line) for a card, e.g. ("42% · ~8h left", "of 237,761 字"); estimates get "≈"."""
    if prog["finished"]:
        return "100% · finished", ""
    main = f"{prog['pct']}%"
    left = fmt_left(prog["left_seconds"])
    if left:
        main += " · " + left
    if prog["estimate"]:
        return "≈ " + main, "≈ estimate"
    who = " (yours)" if prog["source"] == "user" else ""
    return main, f"of {fmt_int(prog['total'])} 字{who}"
