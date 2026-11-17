"""What to read next: your VNDB wishlist plus Library VNs you haven't started, with length and difficulty.
No GUI and no `import tracker`; the HTTP function is `app.lib._http`.

Sources
  * wishlist: POST https://api.vndb.org/kana/ulist {"user": cfg["vndb_user"], "filters": ["label","=",5]}
    (sent with the VNDB token too when one is set, so a private wishlist works)
  * Library VNs with no characters read yet and a status of Reading / On hold
  * difficulty and length: jiten.moe  GET /api/media-deck/by-link-id/2/<vndb id>  then  /api/media-deck/<id>/detail
    -> data.mainDeck.characterCount and data.mainDeck.difficultyRaw (0..5, float; `difficulty` is the rounded int)
    Fallbacks when jiten doesn't know the VN: length from VNDB length_minutes x chars_per_minute (marked as an
    estimate), difficulty unknown (sorted last), VNDB rating is shown.

Cache: table `read_next(vid, data JSON, fetched_at)`; the special row vid="_wishlist" holds the wishlist ids.
Network runs on `app.worker` in small batches; the DB is only touched on the UI thread.
"""
import json
import time

import progress

PAUSE = 0.6
BATCH = 4
STALE_DAYS = 30            # a jiten answer is refreshed this rarely
FAIL_BACKOFF = 600
SORTS = ["Easiest first", "Shortest first", "Best rated"]
WISHLIST_LABEL = 5
FIELDS = ("id, labels.id, vn.title, vn.alttitle, vn.released, vn.length_minutes, vn.rating, "
          "vn.image.url, vn.image.sexual")


# ------------------------------------------------------------------ cache
def ensure(store):
    if getattr(store, "_readnext_ready", False):
        return
    store.db.execute("CREATE TABLE IF NOT EXISTS read_next(vid TEXT PRIMARY KEY, data TEXT, fetched_at REAL)")
    store.db.commit()
    store._readnext_ready = True


def cache_all(store):
    ensure(store)
    out = {}
    for vid, data, at in store.db.execute("SELECT vid, data, fetched_at FROM read_next"):
        try:
            d = json.loads(data) if data else {}
        except ValueError:
            d = {}
        d["_at"] = at
        out[vid] = d
    return out


def save(store, vid, patch):
    """Merges `patch` into the cached entry of `vid`."""
    ensure(store)
    row = store.db.execute("SELECT data FROM read_next WHERE vid=?", (vid,)).fetchone()
    try:
        d = json.loads(row[0]) if row and row[0] else {}
    except ValueError:
        d = {}
    d.update(patch)
    store.db.execute("INSERT OR REPLACE INTO read_next VALUES(?,?,?)",
                     (vid, json.dumps(d, ensure_ascii=False), time.time()))
    store.db.commit()


def last_refresh(store):
    ensure(store)
    row = store.db.execute("SELECT fetched_at FROM read_next WHERE vid='_wishlist'").fetchone()
    return row[0] if row else None


# ------------------------------------------------------------------ network (worker thread, no DB)
def fetch_wishlist(http, api_vn_url, uid, token=None):
    """[{"id": "v17", "title", "alttitle", "released", "length_minutes", "rating", "cover_url", "cover_sexual"}]"""
    url = api_vn_url.rsplit("/", 1)[0] + "/ulist"
    out, page = [], 1
    while True:
        body = json.dumps({"user": uid, "filters": ["label", "=", WISHLIST_LABEL], "fields": FIELDS,
                           "results": 100, "page": page}, ensure_ascii=False).encode("utf-8")
        hdr = {"Authorization": "Token " + token.strip()} if token else None
        data = json.loads(http(url, body, timeout=30, headers=hdr) if hdr else http(url, body, timeout=30))
        for it in data.get("results", []):
            vn = it.get("vn") or {}
            img = vn.get("image") or {}
            out.append(dict(id=it["id"], title=vn.get("title"), alttitle=vn.get("alttitle"),
                            released=vn.get("released"), length_minutes=vn.get("length_minutes"),
                            rating=vn.get("rating"), cover_url=img.get("url"), cover_sexual=img.get("sexual")))
        if not data.get("more"):
            return out
        page += 1


def fetch_jiten_info(http, vid, pause=PAUSE):
    """{"chars": int|None, "diff": float|None} from jiten.moe, or None if jiten doesn't have the VN.
    Network errors raise (the caller retries later instead of caching a miss)."""
    ids = json.loads(http(f"{progress.API}/api/media-deck/by-link-id/2/{vid}"))
    best = None
    for did in (ids or [])[:3]:
        time.sleep(pause)
        deck = (json.loads(http(f"{progress.API}/api/media-deck/{did}/detail")).get("data") or {}).get("mainDeck") or {}
        n = int(deck.get("characterCount") or 0)
        raw = deck.get("difficultyRaw")
        if raw is None or raw < 0:
            raw = deck.get("difficulty") if (deck.get("difficulty") or -1) >= 0 else None
        info = {"chars": n or None, "diff": float(raw) if raw is not None else None}
        if best is None or deck.get("mediaType") == 7:
            best = info
            if deck.get("mediaType") == 7:
                break
    return best


# ------------------------------------------------------------------ rows
def _est_chars(length_minutes, cpm):
    return int(length_minutes * (cpm if cpm and cpm > 0 else progress.CPM_DEFAULT)) if length_minutes else None


def rows(app):
    """Everything shown on the Read next page (UI thread): one dict per VN, unsorted.
    {vid, title, alttitle, vn (for app.cover_photo), chars, chars_est, diff, rating, length_minutes,
     in_library, status, source ("wishlist"|"library")}"""
    store, cfg = app.store, app.cfg
    cache = cache_all(store)
    totals = progress.all_totals(store)
    cpm = cfg.get("chars_per_minute")
    out, seen = [], set()

    def make(vid, base, in_lib, status, source):
        c = cache.get(vid, {})
        tot = totals.get(vid)
        chars = (tot or {}).get("total") or c.get("chars")
        est = False
        lm = base.get("length_minutes")
        if not chars and lm:
            chars, est = _est_chars(lm, cpm), True
        vn = dict(base, id=vid)
        return dict(vid=vid, title=base.get("title") or vid, alttitle=base.get("alttitle"), vn=vn, chars=chars,
                    chars_est=est, diff=c.get("diff"), rating=base.get("rating"), length_minutes=lm,
                    in_library=in_lib, status=status, source=source)

    lib = {it["vn"]["id"]: it for it in store.library() if it.get("vn")}
    for vid, it in lib.items():
        if it["chars"] == 0 and it["status"] in ("Reading", "On hold") and not it["unknown"]:
            out.append(make(vid, it["vn"], True, it["status"], "library"))
            seen.add(vid)
    meta = cache.get("_wishlist", {})
    for vid in meta.get("ids", []):
        if vid in seen:
            continue
        if vid in lib:
            continue  # already in the library (read or started): not "next"
        c = cache.get(vid, {})
        base = dict(title=c.get("title"), alttitle=c.get("alttitle"), length_minutes=c.get("length_minutes"),
                    rating=c.get("rating"), cover_path=c.get("cover_path"), cover_sexual=c.get("cover_sexual"),
                    cover_url=c.get("cover_url"), released=c.get("released"))
        out.append(make(vid, base, False, None, "wishlist"))
    return out


def sort_rows(rs, mode):
    big = float("inf")
    if mode == "Shortest first":
        return sorted(rs, key=lambda r: (r["chars"] or big, r["diff"] if r["diff"] is not None else big))
    if mode == "Best rated":
        return sorted(rs, key=lambda r: -(r["rating"] or 0))
    return sorted(rs, key=lambda r: (r["diff"] is None, r["diff"] if r["diff"] is not None else 0,
                                     r["chars"] or big))


def diff_text(d):
    return "?" if d is None else f"{d:.1f} / 5"


def length_text(fmt_int, chars, est):
    if not chars:
        return "length unknown"
    return ("≈ " if est else "") + f"{fmt_int(chars)} 字"


# ------------------------------------------------------------------ refresh
def state(app):
    st = getattr(app, "_rn_state", None)
    if st is None:
        st = app._rn_state = {"running": False, "done": 0, "total": 0, "failed": {}, "error": None,
                              "listeners": []}
    return st


def _notify(app):
    st = state(app)
    keep = []
    for fn in st["listeners"]:
        try:
            fn()
            keep.append(fn)
        except Exception:  # noqa: BLE001 - window gone
            pass
    st["listeners"] = keep


def pending(app, force=False, now=None):
    """VNDB ids whose jiten info (or wishlist cover) is missing or stale."""
    now = now or time.time()
    st = state(app)
    cache = cache_all(app.store)
    out = []
    for r in rows(app):
        vid = r["vid"]
        if not vid.startswith("v") or now - st["failed"].get(vid, 0) < FAIL_BACKOFF:
            continue
        c = cache.get(vid, {})
        need_cover = r["source"] == "wishlist" and c.get("cover_url") and not c.get("cover_path")
        stale = force or "jiten_at" not in c or now - c["jiten_at"] > STALE_DAYS * 86400
        if stale or need_cover:
            out.append(vid)
    return out


def refresh(app, force=False, callback=None):
    """Re-reads the wishlist, then fills in jiten difficulty / length and covers in small worker batches
    (only missing / stale ones unless force).
    Safe to call often: does nothing while a run is active. `callback(error)` after the wishlist step."""
    st = state(app)
    if st["running"]:
        return False
    st["running"], st["error"], st["done"], st["total"] = True, None, 0, 0
    uid, token = app.cfg.get("vndb_user"), (app.cfg.get("vndb_token") or "").strip() or None
    http, api = app.lib._http, app.lib.VNDB_API

    def job():
        if not uid:
            return None
        try:
            return fetch_wishlist(http, api, uid, token)
        except Exception:  # noqa: BLE001 - a token without listread: try the public list
            if token:
                return fetch_wishlist(http, api, uid, None)
            raise

    def done(items, err):
        if err:
            st["running"], st["error"] = False, str(err)[:80]
            _notify(app)
            if callback:
                callback(err)
            return
        if items is not None:
            for it in items:
                save(app.store, it["id"], {k: v for k, v in it.items() if k != "id"})
            save(app.store, "_wishlist", {"ids": [it["id"] for it in items]})
        if callback:
            callback(None)
        todo = pending(app, force=force)
        st["total"] = len(todo)
        _notify(app)
        _next_batch(app, todo, force)

    app.worker.submit(job, done)
    return True


def _next_batch(app, todo, force):
    st = state(app)
    if not todo:
        st["running"] = False
        _notify(app)
        return
    batch, rest = todo[:BATCH], todo[BATCH:]
    http, cache = app.lib._http, cache_all(app.store)
    download = app.lib.download_cover

    def job():
        res = {}
        for vid in batch:
            item = {}
            try:
                item["jiten"] = ("ok", fetch_jiten_info(http, vid))
            except Exception as e:  # noqa: BLE001 - offline / rate limited: retry later
                item["jiten"] = ("err", str(e))
            c = cache.get(vid, {})
            if c.get("cover_url") and not c.get("cover_path"):
                try:
                    item["cover"] = download({"id": vid, "image": {"url": c["cover_url"]}})
                except Exception:  # noqa: BLE001
                    pass
            res[vid] = item
            time.sleep(PAUSE)
        return res

    def done(res, err):
        for vid, item in (res or {}).items():
            kind, val = item.get("jiten", ("err", ""))
            patch = {}
            if kind == "ok":
                info = val or {}
                patch.update(chars=info.get("chars"), diff=info.get("diff"), jiten_at=time.time())
                progress.save_online(app.store, vid, info.get("chars"))
            else:
                st["failed"][vid] = time.time()
            if item.get("cover"):
                patch["cover_path"] = item["cover"]
            if patch:
                save(app.store, vid, patch)
            st["done"] += 1
        _notify(app)
        if err:
            st["running"], st["error"] = False, str(err)[:80]
            _notify(app)
            return
        try:
            app.root.after(300, lambda: _next_batch(app, rest, force))
        except Exception:  # noqa: BLE001 - window closing
            st["running"] = False

    app.worker.submit(job, done)


# ------------------------------------------------------------------ actions
def start_reading(app, r):
    """"Start reading": a wishlist VN joins the Library as Reading (and VNDB gets Playing, wishlist unset);
    a Library VN just becomes Reading. Returns the library group key."""
    import vndb_push
    store, vid = app.store, r["vid"]
    if r["in_library"]:
        store.set_status(vid, "Reading")  # pushes through the Store.on_status hook when the status changed
        if r["status"] == "Reading":
            vndb_push.push_status(app, vid, "Reading", quiet=True)
        return vid
    key = "manual:" + vid
    vn = dict(r["vn"], image={"url": r["vn"].get("cover_url"), "sexual": r["vn"].get("cover_sexual")})
    store.ensure_game(key, r["title"])
    store.set_match([key], vn, 2, r["vn"].get("cover_path"))
    store.db.execute("UPDATE games SET status='Reading', source='vndb' WHERE key=?", (key,))
    store.db.commit()
    gone = app.cfg.get("vndb_deleted")
    if gone and vid in gone:
        app.cfg["vndb_deleted"] = [g for g in gone if g != vid]
        app.save_config()
    vndb_push.push_status(app, vid, "Reading")
    return vid
