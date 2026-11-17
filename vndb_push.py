"""Send a Library status change back to the user's VNDB list. No GUI and no `import tracker`.

Needs a VNDB API token with the `listwrite` permission (https://vndb.org/u/tokens), cfg["vndb_token"], and
cfg["vndb_push_enabled"]. API: https://api.vndb.org/kana
  PATCH /ulist/<vid>   {"labels_set": [..], "labels_unset": [..], "started": "YYYY-MM-DD", "finished": ...}
                       (header `Authorization: Token <token>`, answers 204)
  GET   /authinfo      -> {"id", "username", "permissions": ["listread", "listwrite"]}
Built-in labels: 1 Playing, 2 Finished, 3 Stalled, 4 Dropped, 5 Wishlist. We set the label of the new status
and unset the other four (Wishlist too: a VN you now read isn't a wish anymore). Other labels (custom ones,
Voted) are never touched. The network call runs on `app.worker`; the HTTP function is `app.lib._http`.
"""
import datetime as dt
import json
import re

API = "https://api.vndb.org/kana"
LABELS = {"Reading": 1, "Finished": 2, "On hold": 3, "Dropped": 4}
STATUS_LABEL_IDS = (1, 2, 3, 4, 5)
VNDB_ID_RE = re.compile(r"^v\d+$")


def mask_token(token):
    """'abcd-efgh-...' -> 'abcd...wxyz' (never show a whole token)."""
    t = (token or "").strip()
    if not t:
        return ""
    return t if len(t) <= 8 else t[:4] + "…" + t[-3:]


def enabled(cfg):
    return bool((cfg.get("vndb_token") or "").strip()) and bool(cfg.get("vndb_push_enabled", True))


def build_body(status, started=None, finished=None):
    """The PATCH body for a status, or None for a status VNDB has no label for."""
    lid = LABELS.get(status)
    if not lid:
        return None
    body = {"labels_set": [lid], "labels_unset": [i for i in STATUS_LABEL_IDS if i != lid]}
    if started:
        body["started"] = started
    if finished:
        body["finished"] = finished
    return body


def started_date(store, grp):
    """Day of the first tracked line of this library group, 'YYYY-MM-DD', or None if nothing was read."""
    keys = store.group_keys(grp)
    if not keys:
        return None
    marks = ",".join("?" * len(keys))
    row = store.db.execute(f"SELECT MIN(ts) FROM lines WHERE game IN ({marks})", keys).fetchone()
    if not row or not row[0]:
        return None
    h = int(store.cfg.get("day_start_hour", 4))
    return (dt.datetime.fromtimestamp(row[0]) - dt.timedelta(hours=h)).date().isoformat()


def request_for(store, grp, status):
    """(vid, body) for the PATCH, or None when this group can't / needn't be pushed."""
    if not VNDB_ID_RE.match(grp or ""):
        return None
    started = None
    if status in ("Reading", "Finished"):
        started = started_date(store, grp)
    finished = store.today_str() if status == "Finished" else None
    body = build_body(status, started, finished)
    return (grp, body) if body else None


def patch_ulist(http, token, vid, body):
    data = json.dumps(body).encode("utf-8")
    return http(f"{API}/ulist/{vid}", data, timeout=20, method="PATCH",
                headers={"Authorization": "Token " + token.strip()})


def authinfo(http, token):
    """{"id", "username", "permissions"} for a token (raises on a bad one: HTTP 401)."""
    return json.loads(http(f"{API}/authinfo", timeout=20, headers={"Authorization": "Token " + token.strip()}))


def push_status(app, grp, status, quiet=False):
    """Pushes one status change on the worker. Returns True if a request was started."""
    cfg = app.cfg
    if not enabled(cfg):
        return False
    req = request_for(app.store, grp, status)
    if not req:
        return False
    vid, body = req
    token, http = cfg["vndb_token"], app.lib._http

    def job():
        return patch_ulist(http, token, vid, body)

    def done(_res, err):
        if err:
            msg = str(err)
            if "401" in msg:
                msg = "token rejected (check listwrite)"
            elif "403" in msg:
                msg = "token lacks listwrite"
            app.status(f"VNDB push failed: {msg}", 6000)
        elif not quiet:
            app.status(f"VNDB: {vid} marked {status}", 4000)

    app.worker.submit(job, done)
    return True


def test_token(app, callback):
    """Checks the token on the worker. callback(text, ok) on the UI thread."""
    token = (app.cfg.get("vndb_token") or "").strip()
    if not token:
        callback("no token set", False)
        return
    http = app.lib._http

    def done(info, err):
        if err:
            msg = "token rejected" if "401" in str(err) else f"failed: {err}"
            callback(msg, False)
            return
        perms = info.get("permissions") or []
        who = info.get("username") or info.get("id") or "?"
        if "listwrite" in perms:
            callback(f"OK, {who} (can write your list)", True)
        else:
            callback(f"{who}: token has no listwrite permission", False)

    app.worker.submit(lambda: authinfo(http, token), done)


def install(app):
    """Hooks Store.set_status so every status change (menu, auto-finish, Start reading) is pushed."""
    def on_status(grp, status):
        try:
            push_status(app, grp, status)
        except Exception as e:  # noqa: BLE001 - never break a status change
            app.status(f"VNDB push failed: {e}", 5000)
    app.store.on_status = on_status
