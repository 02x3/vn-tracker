"""
VN Character Tracker
====================
Automatically counts how many Japanese characters you read in visual novels.

How it works: your text hooker (Textractor, LunaHook, LunaTranslator, GameSentenceMiner, ...)
copies every new line to the clipboard. This app watches the clipboard, counts the Japanese
characters in each new line, and attributes it to whatever game window is in the foreground.
Reading time is the gap between lines, capped at an AFK timeout.

New games are looked up on VNDB (api.vndb.org/kana) from the window title / install folder,
tagged with the VN's title and cover art, and shown in a Library with per-VN totals.

Everything is stored locally in data/reading.db (SQLite), covers in data/covers/,
settings in data/config.json. Windows only. Pillow is optional (needed to show covers).
"""

import csv
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import queue
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("VN_TRACKER_DATA") or os.path.join(APP_DIR, "data")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
DB_PATH = os.path.join(DATA_DIR, "reading.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

VNDB_API = "https://api.vndb.org/kana/vn"
VNDB_FIELDS = "id,title,alttitle,aliases,titles.title,titles.latin,released,length_minutes,rating,image.url,image.sexual,developers.name"
USER_AGENT = "vn-char-tracker/1.0"

DEFAULT_CONFIG = {
    # A gap between two lines longer than this counts as at most this many seconds.
    "afk_seconds": 60,
    # Reading after midnight but before this hour counts toward the previous day.
    "day_start_hour": 4,
    # Daily character goal shown as a progress bar (0 = off).
    "daily_goal": 0,
    # Weekly character goal (0 = off); weeks start on "monday" or "sunday" (and follow day_start_hour).
    "weekly_goal": 0,
    "week_starts": "monday",
    # Which goal bar(s) the overlay shows: "daily", "weekly" or "both" (two thin bars).
    "overlay_goal_mode": "daily",
    # Library progress estimate for VNs jiten.moe doesn't know: VNDB length_minutes x this (chars per minute).
    "chars_per_minute": 450,
    # Clipboard text with more Japanese characters than this is ignored (probably not a VN line).
    "max_line_chars": 400,
    # A line identical to one of the last N lines is not counted again (backlog, re-hooks).
    "dedupe_window": 8,
    "poll_ms": 200,
    "overlay_alpha": 0.95,
    "overlay_x": None,
    "overlay_y": None,
    # Look new games up on VNDB automatically.
    "vndb_auto_match": True,
    # Linked VNDB account (Settings > VNDB account): id like "u12345", its name, last sync time.
    "vndb_user": None,
    "vndb_username": None,
    "vndb_last_sync": None,
    "vndb_sync_on_start": True,
    # Send Library status changes back to VNDB (needs a token with listwrite from vndb.org/u/tokens).
    "vndb_token": "",
    "vndb_push_enabled": True,
    # Count meikipop popups over the text box as dictionary lookups (per-VN difficulty).
    "lookups_enabled": True,
    "read_next_sort": "Easiest first",   # Stats > Read next: Easiest first | Shortest first | Best rated
    # Blur covers whose VNDB sexual rating is at least this (0 safe, 1 suggestive, 2 explicit).
    "blur_nsfw_covers": True,
    "nsfw_threshold": 1.5,
    # Where text comes from: "ocr" (watch the game's text box with meikiocr),
    # "clipboard" (text hookers that copy lines), or "both".
    "text_source": "ocr",
    # OCR: screen rectangle [left, top, right, bottom] of the text box (overlay → Select text box).
    "ocr_region": None,
    # The same text box relative to the game window: {"rel": [fractions of the client area], "exe": ..., "abs": [...]}
    "ocr_region_spec": None,
    # Backups of reading.db in data/backups: one at startup and one a day; this many are kept.
    "backup_keep": 7,
    # Global hotkeys (action -> "ctrl+alt+p"); registered while hotkeys_enabled.
    "hotkeys_enabled": True,
    "hotkeys": {"pause": "ctrl+alt+p", "undo": "ctrl+alt+z", "hide": "ctrl+alt+h",
                "region": "ctrl+alt+t", "library": "ctrl+alt+l"},
    # Discord status (needs your own Application ID from discord.com/developers/applications).
    "discord_enabled": False,
    "discord_client_id": "",
    "discord_title_lang": "english",   # english | japanese
    "discord_show_cover": True,
    "discord_show_chars": True,
    # Windows integration + notifications (Settings > windows & notifications); see UI_CONTRACT.md "QoL pack".
    "autostart": False,            # shortcut in the Startup folder (the shortcut file is the truth)
    "tray_enabled": False,         # notification-area icon
    "tray_close_to_tray": False,   # x / close hides the overlay to the tray instead of quitting
    "toast_session": True,         # summary toast when a session ends
    "toast_milestones": True,      # popups for 100k / 250k / ... characters, finished VNs
    "auto_finish_prompt": True,    # ask once to mark a VN Finished when it reaches 100% of a known total
    "break_reminder": False,       # gentle toast after this many minutes of continuous reading
    "break_reminder_minutes": 60,
    "kanji_sort": "first",         # Kanji page sort: first | oldest | freq | rare
    "ocr_interval": 0.25,  # seconds between screen checks
    "ocr_settle": 0.4,     # text must stop changing this long before it's read (typewriter effect)
    "ocr_max_wait": 1.5,   # ...but read anyway after this long (animated backgrounds never settle)
    # OCR pauses while a window from a process whose path contains one of these covers the text box.
    "ocr_block_processes": ["meikipop"],
    # Game picked by hand (overlay → Choose / add game). None = auto-detect.
    "locked_game": None,
    # A reading session ends when the game closes, you quit, you switch games, or after this much idle time.
    "session_gap_minutes": 30,
    # Look: theme preset, custom color overrides, font, overlay style.
    "theme": "Sakura",
    "theme_custom": {},
    "font": "Yu Gothic UI",
    "cute": True,             # kaomoji, ✿ and ♡ touches
    "overlay_compact": False,  # just the number and the goal bar
    "overlay_cover": True,
    "open_library_on_start": True,
    # More look options (Settings > look / overlay / stats).
    "ui_scale": 1.0,            # text size: 0.9 small, 1.0 normal, 1.15 large, 1.3 extra large
    "corner_style": "round",    # round | soft | sharp
    "number_font": "",          # font for big numbers ("" = same as "font")
    "number_format": "comma",   # comma 12,345 | dot 12.345 | space 12 345 | man 1.2万
    "cute_symbol": "✿",         # ✿ ❀ ✦ ★ ♡ ♪ (only shown when "cute" is on)
    "overlay_main": "today",    # which number is big: today | session | total
    "overlay_unit": "字",       # label next to it: 字 | chars | none
    "overlay_size": "normal",   # small | normal | large (big number and cover)
    "overlay_show_title": True,
    "overlay_show_sub": True,       # time · speed line
    "overlay_show_session": True,   # the extra "session N" / "today N" figure on that line
    "overlay_show_goal": True,
    "stats_default_page": "library",  # library | days | sessions | lines
    "library_card_size": "medium",    # small | medium | large
    "chart_days": 30,                 # 14 | 30 | 60 | 90
    "library_sort": "Last read",
    # When one of these is in front (or under the text box), text goes to the last game you were reading.
    "passthrough_processes": [
        "textractor.exe", "lunatranslator.exe", "lunatranslator_main.exe", "lunahost32.exe",
        "lunahost64.exe", "gamesentenceminer.exe", "python.exe", "pythonw.exe", "py.exe",
        "pyw.exe", "explorer.exe", "meikipop.exe", "windowsterminal.exe", "cmd.exe",
        "powershell.exe", "searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe",
        "steam.exe", "steamwebhelper.exe", "obs64.exe", "epicgameslauncher.exe", "magpie.exe",
        "applicationframehost.exe", "textinputhost.exe", "lockapp.exe",
    ],
    # When one of these is in the foreground, clipboard changes are NOT counted (normal copying).
    "ignored_processes": [
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
        "discord.exe", "code.exe", "anki.exe", "obsidian.exe", "notepad.exe", "notepad++.exe",
        "winword.exe", "claude.exe", "telegram.exe", "slack.exe", "spotify.exe",
        "taskmgr.exe", "systemsettings.exe", "mmc.exe", "regedit.exe", "control.exe", "snippingtool.exe",
        "screenclippinghost.exe", "msedgewebview2.exe", "whatsapp.exe", "soundcloud.exe", "voicemeeter.exe",
        "voicemeeterpro.exe", "voicemeeter8x64.exe", "obsidian.exe", "excel.exe", "powerpnt.exe",
        "vlc.exe", "mpc-hc64.exe", "mpv.exe", "potplayermini64.exe", "zoom.exe", "teams.exe", "ms-teams.exe",
    ],
}

# Lists where entries added in a newer version should reach configs saved by an older one.
_MERGED_LISTS = ("passthrough_processes", "ignored_processes", "ocr_block_processes")

STATUSES = ["Reading", "Finished", "On hold", "Dropped"]

# Characters that count as "read": kana, kanji, iteration marks, long vowel mark,
# full-width digits/letters, half-width katakana. Punctuation, spaces and ASCII don't count.
JP_CHAR_RE = re.compile(
    "["
    "ぁ-ゖゝ-ゟ"  # hiragana (+ ゝゞゟ)
    "ァ-ヺー-ヿ"  # katakana (+ ー ヽヾヿ), excludes ・
    "々-〇"               # 々 〆 〇
    "㐀-䶿一-鿿豈-﫿"  # kanji
    "\U00020000-\U0003134F"       # rare kanji (extensions B+)
    "０-９Ａ-Ｚａ-ｚ"  # full-width 0-9 A-Z a-z
    "ｦ-ﾟ"               # half-width katakana
    "]"
)


def count_chars(text: str) -> int:
    return len(JP_CHAR_RE.findall(text))


# ----------------------------------------------------------------------------- config

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print("config.json unreadable, using defaults:", e, file=sys.stderr)
    for key in _MERGED_LISTS:  # keep the user's entries, add any new built-in ones
        user = cfg.get(key) if isinstance(cfg.get(key), list) else []
        have = {str(p).lower() for p in user}
        cfg[key] = user + [p for p in DEFAULT_CONFIG[key] if p.lower() not in have]
    return cfg


def save_config(cfg: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


# ----------------------------------------------------------------------------- formatting

NUMBER_FORMAT = "comma"  # app-wide; set from cfg["number_format"] with set_number_format()


def set_number_format(name) -> None:
    global NUMBER_FORMAT
    NUMBER_FORMAT = name if name in ("comma", "dot", "space", "man") else "comma"


def fmt_int(n) -> str:
    n = int(n or 0)
    fmt = NUMBER_FORMAT
    if fmt == "man":
        if abs(n) >= 10000:
            s = f"{n / 10000:.1f}"
            return (s[:-2] if s.endswith(".0") else s) + "万"
        return str(n)
    s = f"{n:,}"
    if fmt == "dot":
        return s.replace(",", ".")
    if fmt == "space":
        return s.replace(",", " ")
    return s


def fmt_dur(seconds) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def fmt_speed(chars, seconds) -> str:
    if not seconds or seconds < 60:
        return "—"
    return f"{fmt_int(round(chars / seconds * 3600))}/h"


# ----------------------------------------------------------------------------- VNDB

# Folder / exe names that say nothing about which VN it is.
GENERIC_NAMES = {
    "game", "games", "bin", "x64", "x86", "data", "system", "app", "main", "start", "launcher",
    "play", "program files", "program files (x86)", "common", "steamapps", "steam", "desktop",
    "downloads", "windows", "siglusengine", "siglusengine_steam", "bgi", "malie", "nw", "rio",
    "advhd", "cmvs32", "cmvs64", "krkr", "tvp", "kirikiri", "unity", "renpy", "lib", "release",
    "unknown", "c:", "d:", "e:", "f:",
}

_VERSION_RE = re.compile(r"(?i)\b(?:ver(?:sion)?\.?\s*|v)\d[\w.]*")
_BRACKETS_RE = re.compile(r"\[[^\]]*\]|【[^】]*】|［[^］]*］|\((?:32|64)\s*bit\)", re.I)


def clean_title(s: str) -> str:
    s = _BRACKETS_RE.sub(" ", s or "")
    s = _VERSION_RE.sub(" ", s)
    s = re.sub(r"[_\s]+", " ", s)
    return s.strip(" |:・")


def search_candidates(exe_path: str, window_title: str) -> list[str]:
    """Best guesses for the VN's name, most specific first."""
    out: list[str] = []

    def add(s):
        s = clean_title(s)
        if len(s) >= 2 and s.lower() not in GENERIC_NAMES and s not in out:
            out.append(s)

    t = window_title or ""
    add(t)
    for sep in (" - ", " | ", " – ", " — ", "　"):
        if sep in t:
            add(t.split(sep)[0])
    if exe_path and exe_path != "unknown":
        folder = os.path.dirname(exe_path)
        for _ in range(3):  # walk up past generic folders like "bin" or "game"
            name = os.path.basename(folder)
            if not name:
                break
            if clean_title(name).lower() not in GENERIC_NAMES:
                add(name)
                break
            folder = os.path.dirname(folder)
        add(os.path.splitext(os.path.basename(exe_path))[0])
    return out


def _ssl_context():
    import ssl
    try:
        import certifi  # fresher CA bundle than some Windows cert stores
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL_CTX = None


def _http(url: str, body: bytes | None = None, timeout=15, method: str | None = None,
          headers: dict | None = None) -> bytes:
    """GET (no body) / POST (body) by default; `method` e.g. "PATCH" and extra `headers` (Authorization...)."""
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = _ssl_context()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT}, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for hk, hv in (headers or {}).items():
        req.add_header(hk, hv)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return r.read()
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
    # Python's OpenSSL rejected the chain; Windows' own curl.exe (schannel) still verifies it properly.
    import subprocess
    curl = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    cmd = [curl, "-sSf", "-m", str(timeout), "-A", USER_AGENT, url]
    if method:
        cmd += ["-X", method]
    for hk, hv in (headers or {}).items():
        cmd += ["-H", f"{hk}: {hv}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    out = subprocess.run(cmd, input=body, capture_output=True, timeout=timeout + 5,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise OSError(f"curl failed: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout


def vndb_search(query: str, results: int = 8) -> list[dict]:
    body = json.dumps({
        "filters": ["search", "=", query],
        "fields": VNDB_FIELDS,
        "sort": "searchrank",
        "results": results,
    }, ensure_ascii=False).encode("utf-8")
    return json.loads(_http(VNDB_API, body)).get("results", [])


def _norm(s: str) -> str:
    import unicodedata
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").lower())


def match_score(query: str, vn: dict) -> float:
    """0..1 similarity between a guessed name and any of the VN's titles/aliases."""
    from difflib import SequenceMatcher
    q = _norm(query)
    names = [vn.get("title"), vn.get("alttitle"), *(vn.get("aliases") or [])]
    for t in vn.get("titles") or []:
        names += [t.get("title"), t.get("latin")]
    best = 0.0
    for name in filter(None, names):
        n = _norm(name)
        if not n or not q:
            continue
        if n == q:
            return 1.0
        score = SequenceMatcher(None, q, n).ratio()
        prefix = len(os.path.commonprefix([q, n]))
        if prefix >= min(len(q), len(n), 8):  # "dies irae ~x~" vs "dies irae ~y~", "アトリ" vs "アトリエ"
            score = max(score, 0.8)
        best = max(best, score)
    return best


def vndb_auto_match(exe_path: str, window_title: str) -> tuple[dict | None, str | None]:
    """Tries each name guess; picks the best-scoring of the top results, if convincing."""
    for q in search_candidates(exe_path, window_title)[:4]:
        res = vndb_search(q, 5)
        if not res:
            continue
        scored = [(match_score(q, vn), -i, vn) for i, vn in enumerate(res)]
        score, _, vn = max(scored, key=lambda t: (t[0], t[1]))
        if score >= 0.6:
            return vn, q
    return None, None


VNDB_ULIST_FIELDS = ("id, labels.id, labels.label, vote, started, finished, vn.title, vn.alttitle, "
                     "vn.released, vn.length_minutes, vn.rating, vn.image.url, vn.image.sexual, "
                     "vn.developers.name, vn.aliases, vn.titles.title, vn.titles.latin")
# VNDB built-in label id -> library status (Wishlist 5, Blacklist 6, Voted 7 are not imported)
VNDB_LABEL_STATUS = [(1, "Reading"), (2, "Finished"), (3, "On hold"), (4, "Dropped")]


def vndb_user(name: str) -> dict | None:
    """Resolves a VNDB username (or an id like u12345) to {"id": "u12345", "username": ...}, or None."""
    name = (name or "").strip()
    if not name:
        return None
    url = VNDB_API.rsplit("/", 1)[0] + "/user?q=" + urllib.parse.quote(name)
    res = json.loads(_http(url)).get(name)
    return res if res and res.get("id") else None


def vndb_ulist(uid: str) -> list[dict]:
    """The user's whole public list: [{"id": "v17", "labels": [{"id": 2, "label": "Finished"}], "vn": {...}}].
    Each item's "vn" dict also carries the "id", so it can go straight into Store.set_match."""
    url = VNDB_API.rsplit("/", 1)[0] + "/ulist"
    out, page = [], 1
    while True:
        body = json.dumps({"user": uid, "fields": VNDB_ULIST_FIELDS, "results": 100, "page": page},
                          ensure_ascii=False).encode("utf-8")
        data = json.loads(_http(url, body, timeout=30))
        for it in data.get("results", []):
            if it.get("vn"):
                it["vn"]["id"] = it["id"]
            out.append(it)
        if not data.get("more"):
            return out
        page += 1


def download_cover(vn: dict) -> str | None:
    img = vn.get("image") or {}
    url = img.get("url")
    if not url:
        return None
    os.makedirs(COVERS_DIR, exist_ok=True)
    path = os.path.join(COVERS_DIR, vn["id"] + (os.path.splitext(url)[1] or ".jpg"))
    if not os.path.exists(path):
        data = _http(url)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    return path


# ----------------------------------------------------------------------------- storage

GROUP_SQL = "COALESCE(g.vndb_id, 'name:' || COALESCE(g.name, l.game))"


class Store:
    def __init__(self, path: str, cfg: dict):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.cfg = cfg
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS lines(
                id INTEGER PRIMARY KEY,
                ts REAL NOT NULL,          -- unix time the line appeared
                game TEXT NOT NULL,        -- game key (exe path, lowercase)
                chars INTEGER NOT NULL,    -- Japanese characters counted
                seconds REAL NOT NULL,     -- reading time credited to this line
                text TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_lines_ts ON lines(ts);
            CREATE INDEX IF NOT EXISTS idx_lines_game ON lines(game);
            CREATE TABLE IF NOT EXISTS games(
                key TEXT PRIMARY KEY,      -- exe path, lowercase
                name TEXT NOT NULL         -- display name
            );
            CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY,
                game TEXT NOT NULL,
                start_ts REAL NOT NULL,
                end_ts REAL NOT NULL,      -- updated as you read, so a crash still keeps the session
                reason TEXT                -- NULL while in progress; game closed / quit / switched game / idle
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_ts);
            CREATE TABLE IF NOT EXISTS vns(
                id TEXT PRIMARY KEY,       -- VNDB id, e.g. v27448
                title TEXT, alttitle TEXT, released TEXT, developer TEXT,
                length_minutes INTEGER, rating REAL,
                cover_url TEXT, cover_sexual REAL, cover_path TEXT
            );
            """
        )
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(games)")}
        for col, decl in [("title_hint", "TEXT"), ("vndb_id", "TEXT"),
                          ("matched", "INTEGER NOT NULL DEFAULT 0"),  # 0 untried, 1 auto, 2 manual, -1 none
                          ("status", "TEXT"),
                          ("region", "TEXT"),  # OCR text box for this game, JSON [l, t, r, b]
                          ("source", "TEXT")]:  # 'vndb' = imported from the user's VNDB list
            if col not in cols:
                self.db.execute(f"ALTER TABLE games ADD COLUMN {col} {decl}")
        self.db.commit()

    # --- day helpers
    def _day_expr(self) -> str:
        h = int(self.cfg.get("day_start_hour", 4))
        return f"date(ts, 'unixepoch', 'localtime', '-{h} hours')"

    def day_start_epoch(self, when: dt.datetime | None = None) -> float:
        h = int(self.cfg.get("day_start_hour", 4))
        now = when or dt.datetime.now()
        day = (now - dt.timedelta(hours=h)).date()
        return (dt.datetime.combine(day, dt.time()) + dt.timedelta(hours=h)).timestamp()

    def today_str(self) -> str:
        h = int(self.cfg.get("day_start_hour", 4))
        return (dt.datetime.now() - dt.timedelta(hours=h)).date().isoformat()

    # --- games
    def ensure_game(self, key: str, default_name: str, title_hint: str = "") -> bool:
        """Registers a game key. Returns True if it is new."""
        cur = self.db.execute("INSERT OR IGNORE INTO games(key, name, title_hint) VALUES(?,?,?)",
                              (key, default_name, title_hint))
        self.db.commit()
        return cur.rowcount > 0

    def game_name(self, key: str | None) -> str:
        if not key:
            return "—"
        row = self.db.execute("SELECT name FROM games WHERE key=?", (key,)).fetchone()
        return row[0] if row else os.path.splitext(os.path.basename(key))[0]

    def game_vn(self, key: str | None) -> dict | None:
        if not key:
            return None
        row = self.db.execute("SELECT vndb_id FROM games WHERE key=?", (key,)).fetchone()
        return self.vn(row[0]) if row and row[0] else None

    def unmatched_games(self) -> list[tuple[str, str]]:
        return self.db.execute(
            "SELECT key, COALESCE(title_hint,'') FROM games WHERE matched=0 AND key!='unknown'").fetchall()

    def group_keys(self, grp: str) -> list[str]:
        if grp.startswith("name:"):
            rows = self.db.execute("SELECT key FROM games WHERE name=? AND vndb_id IS NULL", (grp[5:],))
        else:
            rows = self.db.execute("SELECT key FROM games WHERE vndb_id=?", (grp,))
        return [r[0] for r in rows]

    def rename_key(self, key: str, name: str) -> None:
        self.db.execute("UPDATE games SET name=? WHERE key=?", (name, key))
        self.db.commit()

    def rename_group(self, grp: str, name: str) -> None:
        """Renaming an unmatched game to another unmatched game's name merges them."""
        keys = self.group_keys(grp)
        self.db.executemany("UPDATE games SET name=? WHERE key=?", [(name, k) for k in keys])
        self.db.commit()

    def delete_group(self, grp: str) -> list[str]:
        """Remove a library entry completely: its games, lines and sessions (and its VNDB info if
        nothing else uses it). Returns the deleted game keys."""
        keys = self.group_keys(grp)
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        vids = {r[0] for r in self.db.execute(f"SELECT vndb_id FROM games WHERE key IN ({marks})", keys) if r[0]}
        self.db.execute(f"DELETE FROM lines WHERE game IN ({marks})", keys)
        self.db.execute(f"DELETE FROM sessions WHERE game IN ({marks})", keys)
        try:
            self.db.execute(f"DELETE FROM lookups WHERE game IN ({marks})", keys)  # lookups.py
        except sqlite3.OperationalError:
            pass
        self.db.execute(f"DELETE FROM games WHERE key IN ({marks})", keys)
        for vid in vids:
            if not self.db.execute("SELECT 1 FROM games WHERE vndb_id=?", (vid,)).fetchone():
                self.db.execute("DELETE FROM vns WHERE id=?", (vid,))
        self.db.commit()
        return keys

    def set_status(self, grp: str, status: str) -> None:
        keys = self.group_keys(grp)
        marks = ",".join("?" * len(keys))
        old = {r[0] or "Reading" for r in self.db.execute(
            f"SELECT status FROM games WHERE key IN ({marks})", keys)} if keys else set()
        self.db.executemany("UPDATE games SET status=? WHERE key=?", [(status, k) for k in keys])
        self.db.commit()
        hook = getattr(self, "on_status", None)  # set by vndb_push.install: pushes the change to VNDB
        if hook and keys and old != {status}:
            hook(grp, status)

    def set_match(self, keys: list[str], vn: dict, matched: int, cover_path: str | None) -> None:
        img = vn.get("image") or {}
        dev = ", ".join(d.get("name", "") for d in vn.get("developers") or [])[:120]
        self.db.execute(
            """INSERT OR REPLACE INTO vns(id,title,alttitle,released,developer,length_minutes,rating,
                                          cover_url,cover_sexual,cover_path)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (vn["id"], vn.get("title"), vn.get("alttitle"), vn.get("released"), dev,
             vn.get("length_minutes"), vn.get("rating"), img.get("url"), img.get("sexual"), cover_path),
        )
        self.db.executemany("UPDATE games SET vndb_id=?, matched=?, name=? WHERE key=?",
                            [(vn["id"], matched, vn.get("title") or vn["id"], k) for k in keys])
        self.db.commit()

    def import_vndb_list(self, items: list[dict], skip=()) -> tuple[int, int]:
        """Adds the VNs of a VNDB user list (Playing/Finished/Stalled/Dropped) that aren't in the library yet.
        VNs already in the library are left exactly as they are (status included), and VNs the user
        deleted (`skip`) aren't brought back. Returns (added, 0)."""
        added = updated = 0
        skip = set(skip)
        for it in items:
            vn = it.get("vn") or {}
            vid = vn.get("id") or it.get("id")
            if not vid:
                continue
            vn = dict(vn, id=vid)
            ids = {l.get("id") for l in it.get("labels") or []}
            status = next((s for lid, s in VNDB_LABEL_STATUS if lid in ids), None)
            if not status:  # Wishlist / Blacklist / Voted only
                continue
            if vid in skip or self.group_keys(vid):
                continue  # deleted by the user, or already in the library: leave it alone
            key = "manual:" + vid
            self.ensure_game(key, vn.get("title") or vid)
            self.set_match([key], vn, 2, None)
            self.db.execute("UPDATE games SET status=?, source='vndb' WHERE key=?", (status, key))
            self.db.commit()
            added += 1
        return added, updated

    def vndb_missing_covers(self) -> list[dict]:
        """Imported VNs that have a cover on VNDB but none on disk yet (minimal vn dicts for download_cover)."""
        rows = self.db.execute(
            """SELECT v.id, v.cover_url FROM vns v JOIN games g ON g.vndb_id=v.id
               WHERE g.source='vndb' AND v.cover_url IS NOT NULL
                 AND (v.cover_path IS NULL OR v.cover_path='') GROUP BY v.id""").fetchall()
        return [{"id": i, "image": {"url": u}} for i, u in rows]

    def set_no_match(self, keys: list[str]) -> None:
        self.db.executemany("UPDATE games SET vndb_id=NULL, matched=-1 WHERE key=?", [(k,) for k in keys])
        self.db.commit()

    def set_cover_path(self, vid: str, path: str | None) -> None:
        self.db.execute("UPDATE vns SET cover_path=? WHERE id=?", (path, vid))
        self.db.commit()

    def get_region_spec(self, key: str | None) -> dict | None:
        """The game's text box as {"rel", "exe", "abs"} (rel/exe only when saved relative to the window).
        Reads the old plain [l, t, r, b] format too."""
        if not key:
            return None
        row = self.db.execute("SELECT region FROM games WHERE key=?", (key,)).fetchone()
        try:
            import winregion
            return winregion.parse_spec(json.loads(row[0])) if row and row[0] else None
        except ValueError:
            return None

    def get_region(self, key: str | None) -> list[int] | None:
        """The game's text box as absolute screen pixels [l, t, r, b] (as last seen)."""
        spec = self.get_region_spec(key)
        return spec.get("abs") if spec else None

    def set_region(self, key: str, region) -> None:  # region: [l, t, r, b] or a winregion spec dict
        self.db.execute("UPDATE games SET region=? WHERE key=?", (json.dumps(region), key))
        self.db.commit()

    # --- sessions
    def start_session(self, game: str, ts: float) -> int:
        cur = self.db.execute("INSERT INTO sessions(game, start_ts, end_ts) VALUES(?,?,?)", (game, ts, ts))
        self.db.commit()
        return cur.lastrowid

    def touch_session(self, sid: int, ts: float) -> None:
        self.db.execute("UPDATE sessions SET end_ts=? WHERE id=?", (ts, sid))
        self.db.commit()

    def end_session(self, sid: int, ts: float, reason: str) -> None:
        self.db.execute("UPDATE sessions SET end_ts=MAX(end_ts, ?), reason=? WHERE id=?", (ts, reason, sid))
        self.db.commit()

    def close_stale_sessions(self) -> None:
        """Sessions left open by a crash / power cut end at their last activity."""
        self.db.execute("UPDATE sessions SET reason='tracker stopped' WHERE reason IS NULL")
        self.db.commit()

    def sessions(self, limit: int = 300) -> list[dict]:
        rows = self.db.execute(
            """SELECT s.id, s.game, COALESCE(g.name, s.game), s.start_ts, s.end_ts, s.reason,
                      COALESCE(SUM(l.chars), 0), COALESCE(SUM(l.seconds), 0), COUNT(l.id)
               FROM sessions s
               LEFT JOIN games g ON g.key = s.game
               LEFT JOIN lines l ON l.game = s.game AND l.ts BETWEEN s.start_ts AND s.end_ts
               GROUP BY s.id ORDER BY s.start_ts DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(id=i, game=g, name=n, start=a, end=b, reason=r, chars=c, seconds=s, lines=k)
                for i, g, n, a, b, r, c, s, k in rows if k]  # sessions whose lines were all deleted vanish

    def has_game(self, key: str | None) -> bool:
        return bool(key) and self.db.execute("SELECT 1 FROM games WHERE key=?", (key,)).fetchone() is not None

    def vn(self, vid: str) -> dict | None:
        cur = self.db.execute("SELECT * FROM vns WHERE id=?", (vid,))
        row = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], row)) if row else None

    # --- lines
    def add_line(self, ts: float, game: str, chars: int, seconds: float, text: str) -> int:
        cur = self.db.execute(
            "INSERT INTO lines(ts, game, chars, seconds, text) VALUES(?,?,?,?,?)",
            (ts, game, chars, seconds, text),
        )
        self.db.commit()
        return cur.lastrowid

    def delete_lines(self, ids) -> None:
        self.db.executemany("DELETE FROM lines WHERE id=?", [(i,) for i in ids])
        self.db.commit()

    def sum_since(self, since: float) -> tuple[int, float]:
        return self.db.execute(
            "SELECT COALESCE(SUM(chars),0), COALESCE(SUM(seconds),0) FROM lines WHERE ts>=?", (since,)
        ).fetchone()

    def totals(self) -> tuple[int, float, int]:
        return self.db.execute(
            f"SELECT COALESCE(SUM(chars),0), COALESCE(SUM(seconds),0), COUNT(DISTINCT {self._day_expr()}) FROM lines"
        ).fetchone()

    def daily(self, days: int | None = None) -> list[tuple[str, int, float, int]]:
        q = f"SELECT {self._day_expr()} AS d, SUM(chars), SUM(seconds), COUNT(*) FROM lines"
        args = []
        if days:
            q += " WHERE ts>=?"
            args.append(self.day_start_epoch() - (days - 1) * 86400 - 3600)
        q += " GROUP BY d ORDER BY d DESC"
        return self.db.execute(q, args).fetchall()

    def library(self) -> list[dict]:
        """One entry per visual novel (games matched to the same VNDB id are merged)."""
        rows = self.db.execute(
            f"""SELECT {GROUP_SQL} AS grp, MAX(COALESCE(g.name, l.game)), MAX(g.vndb_id),
                       SUM(l.chars), SUM(l.seconds), COUNT(*), MIN(l.ts), MAX(l.ts),
                       MAX(g.status), MIN(l.game='unknown'), MAX(g.source)
                FROM lines l LEFT JOIN games g ON g.key=l.game
                GROUP BY grp ORDER BY MAX(l.ts) DESC"""
        ).fetchall()
        out = []
        for grp, name, vid, c, s, n, first, last, status, unknown, source in rows:
            out.append(dict(grp=grp, name=name, vn=self.vn(vid) if vid else None, chars=c, seconds=s,
                            lines=n, first=first, last=last, status=status or "Reading",
                            unknown=bool(unknown), source=source))
        # games added by hand show up even before anything was read
        seen = {it["grp"] for it in out}
        for key, name, vid, status, source in self.db.execute(
                "SELECT key, name, vndb_id, status, source FROM games WHERE key LIKE 'manual:%' "
                "AND key NOT IN (SELECT DISTINCT game FROM lines)").fetchall():
            grp = vid or "name:" + name
            if grp not in seen:
                seen.add(grp)
                out.append(dict(grp=grp, name=name, vn=self.vn(vid) if vid else None, chars=0, seconds=0,
                                lines=0, first=0, last=0, status=status or "Reading", unknown=False,
                                source=source))
        return out

    def recent_lines(self, limit=300) -> list[tuple]:
        return self.db.execute(
            """SELECT l.id, l.ts, COALESCE(g.name, l.game), l.chars, l.seconds, l.text
               FROM lines l LEFT JOIN games g ON g.key=l.game
               ORDER BY l.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def all_lines(self):
        return self.db.execute(
            f"""SELECT {self._day_expr()}, datetime(l.ts,'unixepoch','localtime'),
                       COALESCE(g.name, l.game), g.vndb_id, l.chars, ROUND(l.seconds,1), l.text
                FROM lines l LEFT JOIN games g ON g.key=l.game ORDER BY l.ts"""
        )

    def streak(self) -> int:
        days = {r[0] for r in self.db.execute(
            f"SELECT DISTINCT {self._day_expr()} FROM lines WHERE ts>=?",
            (self.day_start_epoch() - 400 * 86400,),
        )}
        day = dt.date.fromisoformat(self.today_str())
        if day.isoformat() not in days:
            day -= dt.timedelta(days=1)  # streak still alive if you read yesterday
        n = 0
        while day.isoformat() in days:
            n += 1
            day -= dt.timedelta(days=1)
        return n


# ----------------------------------------------------------------------------- tracking logic

class Tracker:
    """Decides whether a clipboard line counts, and how much reading time to credit."""

    def __init__(self, store: Store, cfg: dict):
        self.store = store
        self.cfg = cfg
        self.recent = deque(maxlen=int(cfg.get("dedupe_window", 8)))
        self.last_ts: float | None = None
        self.last_game: str | None = None
        self.session_start = time.time()
        self.session_ids: list[int] = []
        self.paused = False
        locked = cfg.get("locked_game")
        self.locked_game: str | None = locked if store.has_game(locked) else None
        if self.locked_game:
            self.last_game = self.locked_game

    def pending_seconds(self, now: float | None = None) -> float:
        """Time spent on the current line so far (not yet saved), capped at the AFK timeout."""
        if self.paused or self.last_ts is None:
            return 0.0
        return max(0.0, min((now or time.time()) - self.last_ts, float(self.cfg["afk_seconds"])))

    def add(self, text: str, game: str, now: float | None = None, chars: int | None = None,
            from_ocr: bool = False) -> tuple[int, str]:
        """Returns (chars_counted, reason). chars_counted == 0 means the line was skipped.
        OCR lines are already deduplicated by OcrDedupe and pass their own character count."""
        now = now or time.time()
        if self.paused:
            return 0, "paused"
        text = text.strip()
        if not text:
            return 0, "empty"
        if not from_ocr and text in self.recent:
            return 0, "duplicate"
        n = count_chars(text) if chars is None else chars
        if n == 0:
            return 0, "no Japanese"
        if not from_ocr and n > int(self.cfg["max_line_chars"]):
            return 0, "too long"
        secs = 0.0
        if self.last_ts is not None and game == self.last_game:
            secs = max(0.0, min(now - self.last_ts, float(self.cfg["afk_seconds"])))
        line_id = self.store.add_line(now, game, n, secs, text)
        self.session_ids.append(line_id)
        self.recent.append(text)
        self.last_ts = now
        self.last_game = game
        return n, "ok"

    def undo(self) -> bool:
        if not self.session_ids:
            return False
        self.store.delete_lines([self.session_ids.pop()])
        return True

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.last_ts = None  # don't credit the pause as reading time


class SessionLog:
    """Groups reading into sessions: one game, from its first line until the game closes,
    you quit, you switch games, or you go idle for `session_gap_minutes`."""

    def __init__(self, store: Store, cfg: dict):
        self.store, self.cfg = store, cfg
        self.current: dict | None = None  # {id, game, start, last, exe}
        store.close_stale_sessions()

    def gap(self) -> float:
        return float(self.cfg.get("session_gap_minutes", 30)) * 60

    def on_line(self, game: str, ts: float, exe: str | None) -> dict | None:
        """Call for every counted line. Returns the session that just ended, if any."""
        ended = None
        cur = self.current
        if cur and cur["game"] != game:
            ended = self.end("switched game")
        elif cur and ts - cur["last"] > self.gap():
            ended = self.end("idle")
        if not self.current:
            self.current = dict(id=self.store.start_session(game, ts), game=game, start=ts, last=ts, exe=None)
        self.current["last"] = ts
        if exe and not is_non_game(exe, self.cfg):
            self.current["exe"] = os.path.basename(exe).lower()
        self.store.touch_session(self.current["id"], ts)
        return ended

    def end(self, reason: str, now: float | None = None) -> dict | None:
        cur = self.current
        if not cur:
            return None
        self.current = None
        # credit the last line's reading time (capped like any other gap)
        end = cur["last"] + min(max(0.0, (now or cur["last"]) - cur["last"]), float(self.cfg["afk_seconds"]))
        self.store.end_session(cur["id"], end, reason)
        return next((s for s in self.store.sessions(20) if s["id"] == cur["id"]), None)

    def check(self, running: set[str] | None, now: float) -> dict | None:
        """Call periodically: ends the session if its game closed or you've been idle too long."""
        cur = self.current
        if not cur:
            return None
        if running is not None and cur["exe"] and cur["exe"] not in running:
            return self.end("game closed", now)
        if now - cur["last"] > self.gap():
            return self.end("idle", cur["last"])
        return None


def running_exe_names() -> set[str]:
    """Lowercase exe names of all running processes."""
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    names = set()
    if snap and snap != wt.HANDLE(-1).value:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(wt.HANDLE(snap), ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = kernel32.Process32NextW(wt.HANDLE(snap), ctypes.byref(entry))
        kernel32.CloseHandle(snap)
    return names


def _similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


class OcrDedupe:
    """Turns successive OCR reads of the text box into 'new text to count'.

    Compares only the countable Japanese characters, so OCR punctuation noise doesn't matter.
    - same line read again (noise, popup closed, text box re-shown, backlog)  -> nothing
    - text grew (typewriter caught mid-way, NVL page gaining lines)            -> just the added part
    - anything else                                                            -> the whole text
    """

    def __init__(self, window: int = 12, threshold: float = 0.8):
        self.last = ""
        self.recent: deque = deque(maxlen=window)
        self.threshold = threshold

    def feed(self, text: str) -> tuple[str, bool]:
        """Returns (new_countable_chars, is_whole_line)."""
        norm = "".join(JP_CHAR_RE.findall(text or ""))
        if not norm:
            return "", False  # empty / hidden text box: keep `last` so the same line coming back isn't recounted
        prev = self.last
        if norm == prev:
            return "", False
        known = [prev] + [r for r in reversed(self.recent) if r != prev] if prev else list(reversed(self.recent))
        for old in known:  # text grew from something already counted: count only the added part
            if old != prev and len(old) < 6:
                continue  # 「はい」 earlier doesn't make 「はい、そうです」 a continuation
            if len(norm) > len(old) and _similar(norm[:len(old)], old) >= self.threshold:
                self.last = norm
                if old in self.recent:
                    self.recent.remove(old)
                self.recent.append(norm)
                return norm[len(old):], False
        for old in known:  # same line again, or a partial read of it
            if _similar(norm, old) >= self.threshold or (
                    len(norm) < len(old) and _similar(norm, old[:len(norm)]) >= self.threshold):
                self.last = norm if len(norm) >= len(old) else old
                return "", False
        self.last = norm
        self.recent.append(norm)
        return norm, True


class Worker:
    """Runs network calls off the UI thread; callbacks run on the UI thread via pump()."""

    def __init__(self):
        self.jobs: queue.Queue = queue.Queue()
        self.results: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, fn, callback) -> None:
        self.jobs.put((fn, callback))

    def _run(self):
        while True:
            fn, cb = self.jobs.get()
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001 - reported to the callback
                res, err = None, e
            self.results.put((cb, res, err))

    def pump(self) -> None:
        while True:
            try:
                cb, res, err = self.results.get_nowait()
            except queue.Empty:
                return
            cb(res, err)


# ----------------------------------------------------------------------------- Windows glue

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClipboardSequenceNumber.restype = wt.DWORD
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsIconic.argtypes = [wt.HWND]
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    except OSError:
        dwmapi = None


def pid_exe(pid: int) -> str | None:
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        return buf.value if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
    finally:
        kernel32.CloseHandle(h)


def window_pid(hwnd) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def foreground_window() -> tuple[str | None, str]:
    """(full exe path or None, window title) of the foreground window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, ""
    return pid_exe(window_pid(hwnd)), window_title(hwnd)


def virtual_screen() -> tuple[int, int, int, int]:
    """(left, top, width, height) of the whole desktop across all monitors."""
    return tuple(user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


_parents_cache = {"t": 0.0, "map": {}}


def parent_pid(pid: int) -> int | None:
    """Parent process id (cached ~10 s). Venv launchers mean the real interpreter's parent is the
    venv python.exe, e.g. meikipop's popup runs in the base Python started by meikipop\\.venv."""
    if time.monotonic() - _parents_cache["t"] > 10:
        kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        parents = {}
        if snap and snap != wt.HANDLE(-1).value:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = kernel32.Process32FirstW(wt.HANDLE(snap), ctypes.byref(entry))
            while ok:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                ok = kernel32.Process32NextW(wt.HANDLE(snap), ctypes.byref(entry))
            kernel32.CloseHandle(snap)
        _parents_cache.update(t=time.monotonic(), map=parents)
    return _parents_cache["map"].get(pid)


def _cloaked(hwnd) -> bool:
    if not dwmapi:
        return False
    val = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(val), ctypes.sizeof(val))  # DWMWA_CLOAKED
    return bool(val.value)


def scan_windows(region, my_pid: int, block_names) -> dict:
    """Looks at the windows over the OCR region, topmost first.

    Returns {"game": (exe, title) of the window the text box belongs to, or None,
             "own": [rects of this app's windows covering it] (masked out of the capture),
             "blocked": exe of a window covering it (e.g. meikipop's popup), or None}.
    """
    l, t, r, b = region
    cx, cy = (l + r) // 2, (t + b) // 2
    out = {"game": None, "own": [], "blocked": None}
    exe_cache: dict = {}

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or _cloaked(hwnd):
            return True
        rc = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        if rc.right <= l or rc.left >= r or rc.bottom <= t or rc.top >= b or rc.right - rc.left < 2:
            return True  # doesn't touch the text box
        pid = window_pid(hwnd)
        if pid == my_pid:
            out["own"].append((rc.left, rc.top, rc.right, rc.bottom))
            return True
        if pid not in exe_cache:
            exe = pid_exe(pid) or ""
            ppid = parent_pid(pid)
            parent_exe = (pid_exe(ppid) or "") if ppid else ""
            exe_cache[pid] = (exe, parent_exe)
        exe, parent_exe = exe_cache[pid]
        for path in (exe, parent_exe):
            if path and any(name.lower() in path.lower() for name in block_names):
                out["blocked"] = os.path.basename(path)
                return False
        exstyle = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        if exstyle & 0x20 or exstyle & 0x80:  # click-through overlays, tool windows / tooltips
            return True
        if rc.left <= cx < rc.right and rc.top <= cy < rc.bottom:
            out["game"] = (exe or None, window_title(hwnd))
            out["hwnd"] = hwnd
            return False  # found the window the text box belongs to
        return True  # a normal window partly over the text box but not the game: ignore it

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return out


# ----------------------------------------------------------------------------- OCR text box watcher

class MeikiEngine:
    """meikipop's local OCR model, called the same way meikipop calls it."""

    def __init__(self, threads: int = 2):
        import numpy
        import onnxruntime as ort
        from meikiocr import MeikiOCR
        self.np = numpy
        # One line of text doesn't need every core: cap onnxruntime's threads so a read costs far
        # less total CPU (meikiocr builds its own SessionOptions, so patch the class while it loads).
        original = ort.SessionOptions

        class _FewThreads(original):
            def __init__(self):
                super().__init__()
                self.intra_op_num_threads = threads
                self.inter_op_num_threads = 1

        try:
            ort.SessionOptions = _FewThreads
            self.ocr = MeikiOCR()
        except TypeError:  # SessionOptions not subclassable in some onnxruntime build: use defaults
            ort.SessionOptions = original
            self.ocr = MeikiOCR()
        finally:
            ort.SessionOptions = original

    def read(self, img) -> str:
        res = self.ocr.run_ocr(self.np.array(img.convert("RGB")), det_threshold=0.5,
                               rec_threshold=0.1, punct_conf_factor=0.2)
        return "\n".join((line.get("text") or "").strip() for line in res if (line.get("text") or "").strip())


def is_non_game(exe: str | None, cfg: dict) -> bool:
    """Browsers, chat apps, the desktop, terminals, launchers... never count as the game under the text box.
    (python*.exe is allowed here: our own and meikipop's windows are already handled separately.)"""
    if not exe:
        return True
    path = os.path.normcase(os.path.abspath(exe))
    windows = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    store_apps = os.path.normcase(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "WindowsApps"))
    if path.startswith(windows + os.sep) or path.startswith(store_apps + os.sep):
        return True  # Task Manager, Settings, Notepad, Store apps... no VN lives in these folders
    base = os.path.basename(exe).lower()
    if base in {p.lower() for p in cfg["ignored_processes"]}:
        return True
    return base in {p.lower() for p in cfg["passthrough_processes"]} and not base.startswith(("python", "py"))


def _changed(a, b) -> bool:
    """Did two small grayscale frames change by more than noise?"""
    from PIL import ImageChops
    if a is None or b is None or a.size != b.size:
        return True
    hist = ImageChops.difference(a, b).histogram()
    return sum(hist[40:]) > max(3, a.size[0] * a.size[1] // 4000)


class OcrWatcher(threading.Thread):
    """Watches the text box; when its content changes and settles, OCRs it.
    Posts ("ready"|"error"|"warn", msg) and ("text", (text, game)) to `out`."""

    def __init__(self, cfg: dict, out: queue.Queue):
        super().__init__(daemon=True, name="OcrWatcher")
        self.cfg = cfg
        self.out = out
        self.region = cfg.get("ocr_region")
        self.enabled = True
        self.my_pid = os.getpid()
        self.reset = False

    def _grabber(self):
        try:
            import mss
            sct = mss.mss()

            def grab(r):
                from PIL import Image
                s = sct.grab({"left": r[0], "top": r[1], "width": r[2] - r[0], "height": r[3] - r[1]})
                return Image.frombytes("RGB", s.size, s.bgra, "raw", "BGRX")
        except ImportError:
            from PIL import ImageGrab

            def grab(r):
                return ImageGrab.grab(bbox=tuple(r), all_screens=True)
        return grab

    def run(self):
        try:
            engine = MeikiEngine()
        except Exception as e:  # noqa: BLE001
            self.out.put(("error", f"OCR unavailable ({e}). Start with VN Tracker.bat (meikipop's Python)."))
            return
        self.out.put(("ready", None))
        from PIL import ImageDraw
        grab = self._grabber()
        prev = ocr_thumb = None
        last_change = dirty_since = 0.0
        last_region = None
        import lookups
        popup_edge = lookups.PopupEdge()
        while True:
            time.sleep(float(self.cfg.get("ocr_interval", 0.25)))
            r = self.region
            if not self.enabled or not r:
                prev = None
                continue
            if r != last_region or self.reset:
                last_region, self.reset = r, False
                prev = ocr_thumb = None
            try:
                scene = scan_windows(r, self.my_pid, self.cfg.get("ocr_block_processes") or [])
                if scene["blocked"]:
                    if popup_edge.feed(True):  # one dictionary lookup per popup appearance (lookups.py)
                        self.out.put(("popup", scene["blocked"]))
                    prev = None  # wait until the popup is gone, then let the box settle again
                    continue
                if is_non_game(scene["game"][0] if scene["game"] else None, self.cfg):
                    prev = None  # game closed / minimized / alt-tabbed: don't OCR whatever is behind it
                    continue
                img = grab(r)
                if scene["own"]:  # our overlay/dialogs over the box: black them out
                    d = ImageDraw.Draw(img)
                    for (a, b_, c, e) in scene["own"]:
                        d.rectangle((a - r[0], b_ - r[1], c - r[0], e - r[1]), fill=(0, 0, 0))
                w, h = img.size
                scale = max(1, w // 320)
                thumb = img.convert("L").resize((max(1, w // scale), max(1, h // scale)))
                now = time.monotonic()
                if _changed(prev, thumb):
                    last_change = now
                prev = thumb
                if not _changed(ocr_thumb, thumb):
                    dirty_since = 0.0
                    continue
                dirty_since = dirty_since or now
                settled = now - last_change >= float(self.cfg.get("ocr_settle", 0.4))
                if settled or now - dirty_since >= float(self.cfg.get("ocr_max_wait", 1.5)):
                    ocr_thumb, dirty_since = thumb, 0.0
                    self.out.put(("text", (engine.read(img), scene["game"])))
            except Exception as e:  # noqa: BLE001 - keep watching
                self.out.put(("warn", f"OCR error: {e}"))
                time.sleep(1)


def clipboard_seq() -> int:
    return user32.GetClipboardSequenceNumber()


def _instance_name() -> str:
    # The default data folder keeps the historical mutex name; a custom VN_TRACKER_DATA (tests, a second
    # profile) gets its own mutex so it doesn't collide with the user's real tracker.
    name = "Local\\VNCharTrackerMutex"
    if os.environ.get("VN_TRACKER_DATA"):
        import hashlib
        name += "_" + hashlib.md5(os.path.abspath(DATA_DIR).lower().encode("utf-8")).hexdigest()[:12]
    return name


def single_instance() -> bool:
    kernel32.CreateMutexW(None, False, _instance_name())
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


if sys.platform == "win32":
    kernel32.CreateEventW.restype = wt.HANDLE
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    kernel32.SetEvent.argtypes = [wt.HANDLE]
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.WaitForSingleObject.restype = wt.DWORD


def show_event():
    """Auto-reset event a second launch sets to ask the running tracker to show the Library."""
    return kernel32.CreateEventW(None, False, False, _instance_name() + "_show")


# ----------------------------------------------------------------------------- UI

import tkinter as tk  # noqa: E402

from app_extras import ExtrasMixin  # noqa: E402  (text box follows the window, backups, hotkeys, Discord)


from app_more import MoreMixin  # noqa: E402  (dictionary lookups, VNDB status push, read next)


from app_qol import QolMixin  # noqa: E402  (tray, start with Windows, toasts, milestones, kanji upkeep)


class App(ExtrasMixin, MoreMixin, QolMixin):
    """The overlay plus everything the other UI modules talk to (see UI_CONTRACT.md)."""

    OVERLAY_W = 240       # minimum overlay width
    COMPACT_W = 190

    def __init__(self):
        import ui_theme
        self.ui_theme = ui_theme
        self.lib = sys.modules[__name__]
        self.cfg = load_config()
        save_config(self.cfg)  # writes defaults on first run so the file is there to edit
        self.store = Store(DB_PATH, self.cfg)
        self.tracker = Tracker(self.store, self.cfg)
        self.worker = Worker()
        self.sessions = SessionLog(self.store, self.cfg)
        self.listeners: list = []
        self.windows: dict = {}
        self.matching: set = set()
        self.ocr = {"watcher": None, "queue": queue.Queue(), "dedupe": OcrDedupe(), "ready": False}
        self._closing = False
        self._photo_cache: dict = {}
        self._status_after = None
        self._plus_after = None
        self._last_check = 0.0
        self._hover = False
        self._sig = None
        self._goal_frac = 0.0
        self._status_text = ""
        self._show_event = None
        self.card = None

        try:
            from PIL import Image, ImageFilter, ImageOps, ImageTk
            self._pil = (Image, ImageFilter, ImageOps, ImageTk)
        except ImportError:
            self._pil = None

        root = self.root = tk.Tk()
        root.title("VN Tracker")
        self._set_icons(root)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", float(self.cfg["overlay_alpha"]))
        root.configure(bg=ui_theme.TRANSPARENT)
        try:
            root.attributes("-transparentcolor", ui_theme.TRANSPARENT)
        except tk.TclError:
            pass

        set_number_format(self.cfg.get("number_format"))
        ui_theme.set_corner_style(self.cfg.get("corner_style"))
        self.P = ui_theme.palette(self.cfg)
        self.F = ui_theme.Fonts(root, self.cfg.get("font"), self.cfg)
        self.style = ui_theme.style_ttk(root, self.P, self.F)
        self._build_overlay()
        self._build_menu()
        self.refresh()

        # --- place on screen, clamped
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = max(root.winfo_reqwidth(), self.OVERLAY_W)
        x, y = self.cfg.get("overlay_x"), self.cfg.get("overlay_y")
        if x is None or y is None:
            x, y = sw - w - 30, 60
        x = max(0, min(int(x), sw - w))  # keep the whole overlay (and its buttons) on screen
        y = max(0, min(int(y), sh - 80))
        root.geometry(f"+{x}+{y}")
        root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.refresh()

        self.state = {"seq": clipboard_seq(), "retries": 0}
        for key, hint in self.store.unmatched_games():  # retry lookups that failed last time (e.g. offline)
            if not key.startswith("manual:"):
                self.auto_match(key, hint)
        self.ensure_watcher()
        self.init_extras()
        self.init_more()
        self.init_qol()  # tray, startup shortcut, toasts, kanji (app_qol.py)
        root.after(int(self.cfg["poll_ms"]), self.poll)
        root.after(1000, self.tick)
        root.after(100, self._hover_tick)
        self._show_event = show_event()
        if self.cfg.get("vndb_user") and self.cfg.get("vndb_sync_on_start", True):
            root.after(5000, self.sync_vndb)
        if self.cfg.get("open_library_on_start", True) or "--stats" in sys.argv:
            root.after(300, lambda: self.open_stats())  # opens the "stats_default_page"

    def run(self):
        self.root.mainloop()

    def _set_icons(self, root):
        """Crisp icons everywhere: hand Tk natively drawn PNGs (it picks the best size for the title bar
        and taskbar) instead of letting Windows shrink one image."""
        icon = os.path.join(APP_DIR, "icon.ico")
        try:
            root.iconbitmap(default=icon)  # fallback; also applies to every Toplevel
        except tk.TclError:
            pass
        pngs = [os.path.join(APP_DIR, "icons", f"icon_{s}.png") for s in (16, 20, 24, 32, 40, 48, 64, 256)]
        try:
            self._icon_photos = [tk.PhotoImage(master=root, file=p) for p in pngs if os.path.exists(p)]
            if self._icon_photos:
                root.iconphoto(True, *self._icon_photos)  # True = default for all future Toplevels
        except tk.TclError:
            pass
        # The taskbar uses the window's Win32 icons, which Tk builds by scaling one image (blurry).
        # Load the exact small/large sizes from the multi-size .ico and set them on every window as it maps.
        try:
            u = ctypes.windll.user32
            u.LoadImageW.restype = wt.HANDLE
            u.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
            u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            u.GetParent.restype = wt.HWND
            u.GetParent.argtypes = [wt.HWND]
            small, big = u.GetSystemMetrics(49), u.GetSystemMetrics(11)  # SM_CXSMICON, SM_CXICON (DPI-scaled)
            self._hicons = (u.LoadImageW(None, icon, 1, small, small, 0x10),  # IMAGE_ICON, LR_LOADFROMFILE
                            u.LoadImageW(None, icon, 1, big, big, 0x10))
        except Exception:
            self._hicons = (None, None)

        def apply(e):
            w = e.widget
            if not isinstance(w, (tk.Tk, tk.Toplevel)) or not all(self._hicons):
                return
            try:
                hwnd = ctypes.windll.user32.GetParent(w.winfo_id()) or w.winfo_id()
                ctypes.windll.user32.SendMessageW(hwnd, 0x80, 0, self._hicons[0])  # WM_SETICON, ICON_SMALL
                ctypes.windll.user32.SendMessageW(hwnd, 0x80, 1, self._hicons[1])  # ICON_BIG
            except tk.TclError:
                pass

        root.bind_class("Toplevel", "<Map>", apply, add="+")
        root.bind_class("Tk", "<Map>", apply, add="+")

    # ------------------------------------------------------------------ small helpers
    def cute(self) -> bool:
        return bool(self.cfg.get("cute", True))

    def sym(self) -> str:
        """The chosen cute symbol, or "" when cute extras are off."""
        return self.ui_theme.cute_symbol(self.cfg) if self.cute() else ""

    def mark(self) -> str:
        """" ✿" (space + the chosen symbol) for the end of a title, or "" when cute extras are off."""
        return " " + self.sym() if self.cute() else ""

    def save_config(self):
        save_config(self.cfg)

    def status_color(self, status):
        P = self.P
        return {"Reading": P["accent"], "Finished": P["good"], "On hold": P["warn"],
                "Dropped": P["bad"]}.get(status, P["accent"])

    def uses_ocr(self) -> bool:
        return self.cfg.get("text_source", "ocr") in ("ocr", "both")

    def uses_clipboard(self) -> bool:
        return self.cfg.get("text_source", "ocr") in ("clipboard", "both")

    def _alive(self, w) -> bool:
        try:
            return bool(w) and bool(w.winfo_exists())
        except tk.TclError:
            return False

    # ------------------------------------------------------------------ covers
    def cover_photo(self, vn, w, h, radius=0):
        cfg, P = self.cfg, self.P
        if radius:
            radius = max(1, round(self.ui_theme.rad(radius)))  # follows the corner style
        path = (vn or {}).get("cover_path")
        blur = bool(cfg.get("blur_nsfw_covers")) and ((vn or {}).get("cover_sexual") or 0) >= float(cfg["nsfw_threshold"])
        key = (path, w, h, radius, blur)
        if key in self._photo_cache:
            return self._photo_cache[key]
        photo = None
        if self._pil:
            Image, ImageFilter, ImageOps, ImageTk = self._pil
            try:
                if path and os.path.exists(path):
                    img = ImageOps.fit(Image.open(path).convert("RGB"), (w, h), Image.LANCZOS)
                    if blur:
                        img = img.filter(ImageFilter.GaussianBlur(max(w, h) / 12))
                else:
                    img = Image.new("RGB", (w, h), P["card2"])
                if radius:
                    img = self.ui_theme.rounded_image(img, radius)
                photo = ImageTk.PhotoImage(img)
            except Exception:
                photo = None
        if photo is None:
            photo = tk.PhotoImage(width=w, height=h)
            photo.put(P["card2"], to=(0, 0, w, h))
        self._photo_cache[key] = photo
        return photo

    # ------------------------------------------------------------------ overlay
    def _build_overlay(self):
        P, F, cfg, root = self.P, self.F, self.cfg, self.root
        ui = self.ui_theme
        if self.card is not None:
            try:
                self.card.destroy()
            except tk.TclError:
                pass
        self._sig = None
        self._hover = False
        compact = bool(cfg.get("overlay_compact"))

        card = self.card = ui.Card(root, P, fill="bg", outline="line", radius=16, pad=12, stretch=False)
        card.pack()
        body = self.body = card.body
        self._spacer = tk.Frame(body, bg=P["bg"], width=(self.COMPACT_W if compact else self.OVERLAY_W) - 24,
                                height=1)
        self._spacer.pack(side="top")
        self.row = tk.Frame(body, bg=P["bg"])
        self.row.pack(fill="x")
        self.cover_lbl = tk.Label(self.row, bg=P["bg"], bd=0)
        self.col = tk.Frame(self.row, bg=P["bg"])
        self.col.pack(side="left", fill="both", expand=True)
        self.title_lbl = tk.Label(self.col, text="", bg=P["bg"], fg=P["dim"], font=F["sm"], anchor="w")
        self.count_row = tk.Frame(self.col, bg=P["bg"])
        self.big_lbl = tk.Label(self.count_row, text="0", bg=P["bg"], fg=P["fg"], font=F["ov_num"])
        self.big_lbl.pack(side="left")
        osz = ui.OVERLAY_SIZES.get(cfg.get("overlay_size"), 1.0)
        self.unit_lbl = tk.Label(self.count_row, text="字", bg=P["bg"], fg=P["dim"], font=F["sm"])
        self.unit_lbl.pack(side="left", anchor="s", pady=(0, round(7 * osz * ui.scale_value(cfg))), padx=(4, 0))
        self.sub_lbl = tk.Label(self.col, text="", bg=P["bg"], fg=P["dim"], font=F["xs"], anchor="w")
        self.goal_cv = tk.Canvas(self.col, width=1, height=6, bg=P["bg"], highlightthickness=0, bd=0)
        self.goal_cv.bind("<Configure>", lambda e: self._draw_goal(self._goal_frac))
        self.goal2_cv = tk.Canvas(self.col, width=1, height=4, bg=P["bg"], highlightthickness=0, bd=0)  # 2nd bar ("both")
        self.goal2_cv.bind("<Configure>", lambda e: self._draw_goal(getattr(self, "_goal2_frac", 0.0), 2))
        self.status_lbl = tk.Label(body, text="", bg=P["bg"], fg=P["dim"], font=F["xs"], anchor="w",
                                   justify="left", wraplength=(self.COMPACT_W if compact else self.OVERLAY_W) - 24)
        self.plus_lbl = tk.Label(self.count_row, text="", bg=P["bg"], fg=P["accent"], font=F["mdb"])

        # hover buttons, floating top-right over the title
        self.btns = tk.Frame(card, bg=P["bg"])
        self.pause_btn = self._mkbtn("❚❚", self.toggle_pause)
        self._mkbtn("↶", self.undo)
        self._mkbtn("≡", lambda: self.open_stats())
        self._mkbtn("⚙", lambda: self.open_settings())
        self._mkbtn("✕", self.quit_app)

        self._bind_drag(card)
        if self._status_text:
            self._show_status_text(self._status_text)

    def _mkbtn(self, txt, cmd):
        P = self.P
        b = tk.Label(self.btns, text=txt, bg=P["bg"], fg=P["dim"], font=self.F["sm"], padx=4, cursor="hand2")
        b.pack(side="left")
        b.bind("<ButtonRelease-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=P["accent"]))
        b.bind("<Leave>", lambda e: b.configure(fg=P["dim"]))
        return b

    def _bind_drag(self, w):
        if w is self.btns:
            return
        w.bind("<ButtonPress-1>", self._start_drag)
        w.bind("<B1-Motion>", self._do_drag)
        w.bind("<ButtonRelease-1>", self._end_drag)
        w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        for c in w.winfo_children():
            self._bind_drag(c)
        if w is self.title_lbl:
            w.bind("<Double-Button-1>", lambda e: self.fix_current())

    def _start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _do_drag(self, e):
        dx, dy = getattr(self, "_drag", (0, 0))
        self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _end_drag(self, e):
        self.cfg["overlay_x"], self.cfg["overlay_y"] = self.root.winfo_x(), self.root.winfo_y()
        save_config(self.cfg)

    def _build_menu(self):
        P = self.P
        m = self.menu = tk.Menu(self.root, tearoff=0, bg=P["card"], fg=P["fg"], activebackground=P["accent"],
                                activeforeground=P["accent_fg"], bd=0, font=self.F["sm"])
        m.add_command(label="Pause / resume", command=self.toggle_pause)
        m.add_command(label="Undo last line", command=self.undo)
        m.add_separator()
        m.add_command(label="Select text box (OCR)…", command=self.select_region)
        m.add_command(label="Show text box", command=self.flash_region)
        m.add_command(label=f"Hide overlay  ({self.hotkey_text('hide')})", command=self.hide_overlay)
        m.add_separator()
        m.add_command(label="Choose / add game…", command=lambda: self.choose_game_dialog(self.root))
        m.add_command(label="Add reading…", command=lambda: self.manual_entry_dialog(self.root))
        m.add_command(label="Auto-detect game", command=self.unlock_game)
        m.add_command(label="Fix VNDB match for current game…", command=self.fix_current)
        m.add_command(label="Rename current game…", command=self.rename_current)
        m.add_separator()
        m.add_command(label="Stats & library…", command=lambda: self.open_stats())
        m.add_command(label="Settings…", command=lambda: self.open_settings())
        m.add_separator()
        m.add_command(label="Quit", command=self.quit_app)

    def _hover_tick(self):
        try:
            if not self._closing:
                px, py = self.root.winfo_pointerxy()
                x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
                w, h = self.root.winfo_width(), self.root.winfo_height()
                inside = x <= px < x + w and y <= py < y + h
                if inside != self._hover:
                    self._hover = inside
                    if inside:
                        self.btns.place(relx=1.0, x=-12, y=8, anchor="ne")
                        self.btns.lift()
                    else:
                        self.btns.place_forget()
        except tk.TclError:
            pass
        finally:
            if not self._closing:
                self.root.after(100, self._hover_tick)

    def _draw_goal(self, frac, bar=1):
        if bar == 2:
            self._goal2_frac = frac
        else:
            self._goal_frac = frac
        cv, P = (self.goal2_cv if bar == 2 else self.goal_cv), self.P
        cv.delete("all")
        w, h = cv.winfo_width(), int(cv.cget("height"))
        if w <= 4:
            return
        rr = self.ui_theme.rounded_rect
        rr(cv, 0, 0, w - 1, h - 1, 3, fill=P["line"], outline=P["line"])
        if frac > 0:
            col = P["good"] if frac >= 1 else P["accent"]
            rr(cv, 0, 0, max(h, int(w * frac)) - 1, h - 1, 3, fill=col, outline=col)

    # ------------------------------------------------------------------ status + floating "+N"
    def status(self, msg, ms=2500):
        self._status_text = msg
        if self._status_after:
            try:
                self.root.after_cancel(self._status_after)
            except tk.TclError:
                pass
        self._show_status_text(msg)
        try:
            self._status_after = self.root.after(ms, self._clear_status)
        except tk.TclError:
            pass

    def _show_status_text(self, msg):
        if self._alive(self.status_lbl):
            self.status_lbl.configure(text=msg)
            if msg and not self.status_lbl.winfo_ismapped():
                self.status_lbl.pack(fill="x", pady=(6, 0))
            self._bind_drag_one(self.status_lbl)

    def _bind_drag_one(self, w):
        if not getattr(w, "_drag_bound", False):
            w._drag_bound = True
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

    def _clear_status(self):
        self._status_text = ""
        if self._alive(self.status_lbl):
            self.status_lbl.configure(text="")
            self.status_lbl.pack_forget()

    def flash_plus(self, n):
        P = self.P
        text = f"+{n}{self.mark()}"
        lbl = self.plus_lbl
        if not self._alive(lbl):
            return
        if self._plus_after:
            try:
                self.root.after_cancel(self._plus_after)
            except tk.TclError:
                pass
        steps, cute = 12, self.cute()

        def step(i):
            if not self._alive(lbl):
                return
            t = i / steps
            fade = max(0.0, (t - 0.35) / 0.65)
            lbl.configure(text=text, fg=self.ui_theme.mix(P["accent"], P["bg"], fade))
            lbl.place(in_=self.count_row, relx=1.0, rely=0.5, anchor="e", x=-2, y=-int(10 * t) if cute else 0)
            if i < steps:
                self._plus_after = self.root.after(85, step, i + 1)
            else:
                lbl.place_forget()

        step(0)

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        try:
            self._refresh()
        except tk.TclError:
            pass

    def _refresh(self):
        if self._closing:
            return
        P, cfg, tracker, store = self.P, self.cfg, self.tracker, self.store
        cute = self.cute()
        now = time.time()
        pend = tracker.pending_seconds(now)
        t_chars, t_secs = store.sum_since(store.day_start_epoch())
        s_chars, s_secs = store.sum_since(tracker.session_start)
        t_secs += pend
        s_secs += pend
        compact = bool(cfg.get("overlay_compact"))
        goal = int(cfg.get("daily_goal") or 0)
        main = cfg.get("overlay_main") if cfg.get("overlay_main") in ("today", "session", "total") else "today"
        if main == "session":
            m_chars, m_secs = s_chars, s_secs
        elif main == "total":
            tot_chars, tot_secs, _days = store.totals()
            m_chars, m_secs = tot_chars, tot_secs + pend
        else:
            m_chars, m_secs = t_chars, t_secs
        show_title = bool(cfg.get("overlay_show_title", True))
        show_sub = bool(cfg.get("overlay_show_sub", True))
        show_extra = bool(cfg.get("overlay_show_session", True))
        import goals  # daily / weekly goal bars (overlay_goal_mode) + milestone toasts
        bars = goals.overlay_bars(cfg, store, t_chars) if cfg.get("overlay_show_goal", True) else []
        show_goal = bool(bars)
        reached = any(f >= 1 for f in bars)
        goals.check_milestones(self, t_chars)
        afk = float(cfg.get("afk_seconds", 60))
        idle = (cute and not tracker.paused and tracker.last_ts is not None and now - tracker.last_ts > afk)

        # title
        title_fg = P["dim"]
        if tracker.paused:
            title = "( ˘ω˘ ) paused" if cute else "paused"
            title_fg = P["warn"]
        elif tracker.locked_game:
            title = "⚑ " + store.game_name(tracker.locked_game)
        elif tracker.last_game:
            title = store.game_name(tracker.last_game)
        elif self.uses_ocr() and not self.watcher_region():
            title = "(・ω・) right-click → select text box" if cute else "right-click → select text box"
            title_fg = P["warn"]
        else:
            title = "(・ω・) ready" if cute else "ready"
        if len(title) > 34:
            title = title[:33] + "…"
        self.title_lbl.configure(text=title, fg=title_fg)
        self.big_lbl.configure(text=fmt_int(m_chars))
        unit = cfg.get("overlay_unit", "字")
        word = {"today": "today", "session": "this session", "total": "total"}[main]
        unit_txt = unit if unit in ("字", "chars") else ""
        self.unit_lbl.configure(text=f"{unit_txt} {word}".strip())

        # sub line: time · speed of the big number, plus the figure it isn't showing
        parts = [fmt_dur(m_secs), fmt_speed(m_chars, m_secs)]
        if show_extra:
            if main == "today" and s_chars != t_chars:
                parts.append(f"session {fmt_int(s_chars)}")
            elif main != "today" and t_chars != m_chars:
                parts.append(f"today {fmt_int(t_chars)}")
        sub = " · ".join(parts)
        if idle:
            sub += " · zzz"
        if reached and cute:
            sub += "  ♡"
        self.sub_lbl.configure(text=sub)
        self.pause_btn.configure(text="▶" if tracker.paused else "❚❚")

        # cover
        vn = store.game_vn(tracker.last_game)
        has_cover = bool(vn and vn.get("cover_path") and os.path.exists(vn["cover_path"]))
        show_cover = has_cover and bool(cfg.get("overlay_cover", True)) and not compact
        if show_cover:
            k = self.ui_theme.OVERLAY_SIZES.get(cfg.get("overlay_size"), 1.0)
            photo = self.cover_photo(vn, round(40 * k), round(56 * k), 8)
            self.cover_lbl.configure(image=photo)
            self.cover_lbl.image = photo

        # goal bar
        if show_goal:
            two = len(bars) > 1
            self.goal_cv.configure(height=4 if two else 6)
            self._draw_goal(bars[0])
            if two:
                self._draw_goal(bars[1], 2)

        sig = (compact, show_cover, show_goal, show_title, show_sub, len(bars))
        if sig != self._sig:
            self._sig = sig
            for w in (self.cover_lbl, self.title_lbl, self.count_row, self.sub_lbl, self.goal_cv, self.goal2_cv):
                w.pack_forget()
            if show_cover:
                self.cover_lbl.pack(side="left", padx=(0, 10), anchor="n", before=self.col)
            if not compact and show_title:
                self.title_lbl.pack(fill="x")
            self.count_row.pack(fill="x")
            if not compact and show_sub:
                self.sub_lbl.pack(fill="x")
            if show_goal:
                self.goal_cv.pack(fill="x", pady=(5, 0))
                if len(bars) > 1:
                    self.goal2_cv.pack(fill="x", pady=(3, 0))
            self._bind_drag(self.row)

    def data_changed(self):
        self.refresh()
        for fn in list(self.listeners):
            try:
                fn()
            except tk.TclError:
                if fn in self.listeners:
                    self.listeners.remove(fn)

    # ------------------------------------------------------------------ lazy UI modules
    def _ui_call(self, module, fn, *args, **kw):
        try:
            import importlib
            mod = importlib.import_module(module)
            return getattr(mod, fn)(self, *args, **kw)
        except Exception as e:  # noqa: BLE001 - shown on the overlay; the other modules may not exist yet
            import traceback
            traceback.print_exc()
            self.status(f"{module}.{fn} unavailable: {type(e).__name__}: {e}", 6000)
            return None

    def _open_window(self, name, module, fn, page=None, geometry=None, state=None):
        win = self.windows.get(name)
        if self._alive(win) and geometry is None:
            win.deiconify()
            win.lift()
            win.focus_force()
            if page and hasattr(win, "select_page"):
                win.select_page(page)
            return
        if page and state is None:
            state = {"page": page}
        self._ui_call(module, fn, geometry=geometry, state=state)

    def open_stats(self, page=None, geometry=None, state=None):
        self._open_window("stats", "ui_stats", "open_stats", page, geometry, state)

    def open_settings(self, geometry=None, state=None):
        self._open_window("settings", "ui_settings", "open_settings", None, geometry, state)

    def fix_match_dialog(self, grp, name, parent):
        return self._ui_call("ui_dialogs", "fix_match_dialog", grp, name, parent)

    def choose_game_dialog(self, parent):
        return self._ui_call("ui_dialogs", "choose_game_dialog", parent)

    def manual_entry_dialog(self, parent=None, grp=None):
        """Add reading done elsewhere (phone, manga...); grp pre-selects a library entry."""
        return self._ui_call("ui_dialogs", "manual_entry_dialog", parent or self.root, grp)

    # ------------------------------------------------------------------ theme
    def apply_theme(self):
        ui, cfg, root = self.ui_theme, self.cfg, self.root
        self.P.clear()
        self.P.update(ui.palette(cfg))
        set_number_format(cfg.get("number_format"))
        ui.set_corner_style(cfg.get("corner_style"))
        self.F.update_from(cfg)
        self.style = ui.style_ttk(root, self.P, self.F)
        self._photo_cache.clear()
        try:
            root.attributes("-alpha", float(cfg["overlay_alpha"]))
        except tk.TclError:
            pass
        self._build_overlay()  # tiny and instant; not frozen (WM_SETREDRAW misbehaves on the color-keyed window)
        self._build_menu()
        self.refresh()
        # Restyle open windows in place: same window, same position, contents rebuilt while painting is
        # paused, then one repaint, so the theme just changes instead of the windows closing and reopening.
        for name, module, fn in (("stats", "ui_stats", "rebuild_stats"), ("settings", "ui_settings", "open_settings")):
            win = self.windows.get(name)
            if not self._alive(win):
                continue
            state = getattr(win, "ui_state", None)
            with self._frozen(win):
                if name == "stats":
                    self._ui_call(module, fn, win, state)
                else:
                    self._ui_call(module, fn, state=state, into=win)
        self.rebuild_qol()  # tray / startup follow the settings; detail window restyled

    def _frozen(self, win):
        """Context manager: suspend painting of a window (WM_SETREDRAW) and repaint once at the end."""
        import contextlib

        @contextlib.contextmanager
        def cm():
            u = ctypes.windll.user32
            try:
                hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
            except tk.TclError:
                hwnd = None
            if hwnd:
                u.SendMessageW(hwnd, 0x000B, 0, 0)  # WM_SETREDRAW off
            try:
                yield
            finally:
                if hwnd:
                    try:
                        win.update_idletasks()
                    except tk.TclError:
                        pass
                    u.SendMessageW(hwnd, 0x000B, 1, 0)  # WM_SETREDRAW on
                    # RDW_ERASE | RDW_FRAME | RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW
                    u.RedrawWindow(wt.HWND(hwnd), None, None, 0x4 | 0x400 | 0x1 | 0x80 | 0x100)
        return cm()

    # ------------------------------------------------------------------ OCR source
    def watcher_region(self):
        w = self.ocr["watcher"]
        return w.region if w else self.cfg.get("ocr_region")

    def ensure_watcher(self):
        if self.uses_ocr() and not self.ocr["watcher"]:
            self.ocr["watcher"] = OcrWatcher(self.cfg, self.ocr["queue"])
            self.ocr["watcher"].start()
            self.status("loading OCR…", 6000)

    def set_text_source(self, src):
        self.cfg["text_source"] = src
        save_config(self.cfg)
        self.ensure_watcher()
        if self.ocr["watcher"]:
            self.ocr["watcher"].enabled = self.uses_ocr() and not self.tracker.paused
        self.refresh()

    def set_watch_region(self, region, announce=False):
        w = self.ocr["watcher"]
        if w and region and w.region != region:
            w.region = region
            self.ocr["dedupe"] = OcrDedupe()
            if announce:
                self.status("switched to this game's text box")

    def follow_game_region(self):
        """Each game remembers its own text box (relative to its window, so it follows the window);
        switch when you switch games. See app_extras.follow_region."""
        self.follow_region()

    def resolve_game(self, exe, title, source):
        """Which game a line belongs to. None = don't count it."""
        cfg, store, tracker = self.cfg, self.store, self.tracker
        if tracker.locked_game:
            return tracker.locked_game
        base = os.path.basename(exe).lower() if exe else ""
        ignored = {p.lower() for p in cfg["ignored_processes"]}
        if source == "clipboard" and base in ignored:
            return None  # ordinary copying in a browser, Discord, ...
        passthrough = base in {p.lower() for p in cfg["passthrough_processes"]}
        if not exe or base in ignored or passthrough or is_non_game(exe, cfg):
            # never create a "game" for Windows' own programs, launchers, chat apps...
            key = tracker.last_game or "unknown"
            if key == "unknown":
                store.ensure_game(key, "Unknown game")
            return key
        key = exe.lower()
        default = clean_title(title)[:60] or os.path.splitext(os.path.basename(exe))[0]
        if store.ensure_game(key, default, title):
            self.auto_match(key, title)
        return key

    def ocr_window_ok(self, exe):
        """Is the window under the text box plausibly the game (not a browser, chat app, desktop...)?"""
        if is_non_game(exe, self.cfg):
            return False
        base = os.path.basename(exe).lower()
        tracker = self.tracker
        if tracker.locked_game:  # locked: stick to the program the text box first belonged to
            bound = self.ocr.setdefault("bound", {})
            if bound.get(tracker.locked_game, exe.lower()) != exe.lower():
                self.status(f"text box shows {base}, not your game — not counted", 3000)
                return False
            bound[tracker.locked_game] = exe.lower()
        return True

    def _line_counted(self, key, exe, n):
        self.flash_plus(n)
        ended = self.sessions.on_line(key, self.tracker.last_ts or time.time(), exe)
        if ended:
            self._session_ended(ended)
        self.qol_line(key, n)  # kanji upkeep, milestones, "mark finished?", break timer
        self.refresh()

    def _session_ended(self, s):
        mark = self.mark()
        self.status(f"session logged{mark} {s['name']} · {fmt_int(s['chars'])} 字 · {fmt_dur(s['seconds'])}", 6000)
        self.data_changed()
        self.qol_session_ended(s)  # summary toast

    def on_ocr_text(self, text, game):
        exe, title = game if game else (None, "")
        if not self.ocr_window_ok(exe):
            return
        new, whole = self.ocr["dedupe"].feed(text)
        if not new:
            return
        key = self.resolve_game(exe, title, "ocr")
        if not key:
            return
        if key != "unknown" and not self.store.get_region(key) and self.watcher_region():
            self.store.set_region(key, self.current_region_spec(exe))  # remember this game's text box
        n, why = self.tracker.add(text if whole else new, key, chars=len(new), from_ocr=True)
        if n:
            self._line_counted(key, exe, n)

    def pump_ocr(self):
        while True:
            try:
                kind, payload = self.ocr["queue"].get_nowait()
            except queue.Empty:
                return
            if kind == "text":
                self.on_ocr_text(*payload)
            elif kind == "ready":
                self.ocr["ready"] = True
                self.status("OCR ready" if self.watcher_region() else "OCR ready — right-click → Select text box", 6000)
            elif kind == "error":
                self.status(payload, 15000)
            elif kind == "warn":
                self.status(payload, 4000)
            elif kind == "popup":
                self.on_popup()

    def select_region(self):
        root, P = self.root, self.P
        vx, vy, vw, vh = virtual_screen()
        sel = tk.Toplevel(root)
        sel.overrideredirect(True)
        sel.attributes("-topmost", True)
        sel.attributes("-alpha", 0.35)
        sel.geometry(f"{vw}x{vh}+{vx}+{vy}")
        cv = tk.Canvas(sel, bg="black", highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        px, py = root.winfo_pointerxy()
        cv.create_text(px - vx, py - vy - 40, fill="white", font=self.F["h1"],
                       text="Drag a box around the game's text box  ·  Esc to cancel")
        st = {}

        def down(e):
            st["x"], st["y"] = e.x_root, e.y_root
            st["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline=P["good"], width=3)

        def move(e):
            if "rect" in st:
                cv.coords(st["rect"], st["x"] - vx, st["y"] - vy, e.x_root - vx, e.y_root - vy)

        def up(e):
            if "x" not in st:
                return
            x0, x1 = sorted((st["x"], e.x_root))
            y0, y1 = sorted((st["y"], e.y_root))
            sel.destroy()
            if x1 - x0 >= 30 and y1 - y0 >= 15:
                self.apply_region([x0, y0, x1, y1])

        cv.bind("<ButtonPress-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)
        sel.bind("<Escape>", lambda e: sel.destroy())
        sel.bind("<Button-3>", lambda e: sel.destroy())
        sel.focus_force()

    def apply_region(self, region):
        cfg, store, tracker, root = self.cfg, self.store, self.tracker, self.root
        cfg["ocr_region"] = region
        spec = cfg["ocr_region_spec"] = self._cur_spec = self.region_spec_for_selection(region)  # follows the window
        if cfg.get("text_source") == "clipboard":
            cfg["text_source"] = "ocr"
        save_config(cfg)
        self.ensure_watcher()
        if self.ocr["watcher"]:
            self.ocr["watcher"].region = region
            self.ocr["watcher"].reset = True
        self.ocr["dedupe"] = OcrDedupe()
        key = tracker.locked_game or tracker.last_game
        if key and key != "unknown":
            store.set_region(key, spec)
        self.flash_region(region)
        ox, oy, ow, oh = root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height()
        if ox < region[2] and ox + ow > region[0] and oy < region[3] and oy + oh > region[1]:
            self.status("the overlay covers the text box — drag it somewhere else", 6000)
        else:
            self.status("text box set — reading starts with the next line", 5000)
        self.refresh()

    def flash_region(self, region=None):
        region = region or self.watcher_region()
        if not region:
            self.status("no text box selected yet")
            return
        x0, y0, x1, y1 = region
        key = "#010203"
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-transparentcolor", key)
        w.configure(bg=key)
        w.geometry(f"{x1 - x0}x{y1 - y0}+{x0}+{y0}")
        c = tk.Canvas(w, bg=key, highlightthickness=0)
        c.pack(fill="both", expand=True)
        self.ui_theme.rounded_rect(c, 3, 3, x1 - x0 - 3, y1 - y0 - 3, 12, fill="", outline=self.P["accent"], width=4)
        w.after(1500, w.destroy)

    # ------------------------------------------------------------------ manual game choice
    def delete_group(self, grp, ignore_program=False):
        """Delete a library entry (see Store.delete_group). With ignore_program, the program(s) it was
        detected from go into ignored_processes so they're never picked up as a game again."""
        keys = self.store.delete_group(grp)
        if not keys:
            return
        if not grp.startswith("name:"):  # a VNDB entry: don't let the next VNDB sync bring it back
            deleted = self.cfg.setdefault("vndb_deleted", [])
            if grp not in deleted:
                deleted.append(grp)
        t = self.tracker
        if ignore_program:
            names = [os.path.basename(k).lower() for k in keys if not k.startswith("manual:") and k != "unknown"]
            have = {p.lower() for p in self.cfg["ignored_processes"]}
            self.cfg["ignored_processes"] += [n for n in names if n not in have]
        if t.locked_game in keys:
            t.locked_game = None
            self.cfg["locked_game"] = None
        if t.last_game in keys:
            t.last_game, t.last_ts = None, None
        if self.sessions.current and self.sessions.current["game"] in keys:
            self.sessions.current = None
        alive = {r[0] for r in self.store.db.execute("SELECT id FROM lines WHERE id IN (%s)" % ",".join(
            str(int(i)) for i in t.session_ids))} if t.session_ids else set()
        t.session_ids = [i for i in t.session_ids if i in alive]
        self.save_config()
        self.data_changed()

    def lock_game(self, key):
        self.ocr.get("bound", {}).pop(key, None)
        t = self.tracker
        t.locked_game = key
        t.last_game = key
        t.last_ts = None
        self.cfg["locked_game"] = key
        save_config(self.cfg)
        self.set_watch_region(self.store.get_region(key))
        self.status(f"counting toward {self.store.game_name(key)}", 4000)
        self.data_changed()

    def unlock_game(self):
        self.tracker.locked_game = None
        self.cfg["locked_game"] = None
        save_config(self.cfg)
        self.status("auto-detecting the game again", 4000)
        self.refresh()

    def add_vndb_game(self, vn):
        store = self.store
        existing = store.group_keys(vn["id"])
        if existing:
            return existing[0]  # already in the library (e.g. auto-detected earlier)
        key = "manual:" + vn["id"]
        store.ensure_game(key, vn.get("title") or vn["id"])
        store.set_match([key], vn, 2, None)

        def done(path, err):
            if path:
                store.set_cover_path(vn["id"], path)
                self.data_changed()

        self.worker.submit(lambda: download_cover(vn), done)
        return key

    def sync_vndb(self, callback=None):
        """Pulls the linked VNDB user's list into the Library. callback((added, updated), error) when done."""
        uid = self.cfg.get("vndb_user")
        if not uid or getattr(self, "_vndb_syncing", False):
            if callback and not uid:
                callback(None, RuntimeError("no VNDB account linked"))
            return
        self._vndb_syncing = True

        def done(items, err):
            self._vndb_syncing = False
            if err:
                self.status("VNDB sync failed: " + str(err)[:60], 4000)
                if callback:
                    callback(None, err)
                return
            added, updated = self.store.import_vndb_list(items, skip=self.cfg.get("vndb_deleted") or [])
            self.cfg["vndb_last_sync"] = time.time()
            self.save_config()
            self.status(f"VNDB: added {added} new" if added else "VNDB: up to date", 4000)
            self.data_changed()
            self._fetch_vndb_covers()
            if callback:
                callback((added, updated), None)

        self.worker.submit(lambda: vndb_ulist(uid), done)

    def _fetch_vndb_covers(self):
        """Downloads covers of imported VNs a few at a time (a batch must finish before the next starts,
        so other worker jobs, like auto-match, are not stuck behind hundreds of downloads)."""
        todo = self.store.vndb_missing_covers()
        if not todo or getattr(self, "_covers_running", False):
            return
        self._covers_running = True

        def batch():
            chunk = [todo.pop() for _ in range(min(6, len(todo)))]
            if not chunk:
                self._covers_running = False
                return

            def fetch_one(vn):
                try:
                    return vn, download_cover(vn)
                except Exception:  # noqa: BLE001 - retried on the next sync
                    return vn, None

            def job():
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=len(chunk)) as ex:
                    return list(ex.map(fetch_one, chunk))

            def done(res, err):
                for vn, path in res or []:
                    if path:
                        self.store.set_cover_path(vn["id"], path)
                self.data_changed()
                batch()

            self.worker.submit(job, done)

        batch()

    # ------------------------------------------------------------------ VNDB matching
    def auto_match(self, key, hint):
        if key in self.matching or key == "unknown" or not self.cfg.get("vndb_auto_match", True):
            return
        self.matching.add(key)

        def job():
            vn, q = vndb_auto_match(key, hint)
            return vn, q, (download_cover(vn) if vn else None)

        def done(res, err):
            self.matching.discard(key)
            if err:
                self.status("VNDB lookup failed — will retry next launch", 4000)
                return
            vn, q, path = res
            if vn:
                self.store.set_match([key], vn, 1, path)
                self.status(f"VNDB: {vn.get('title')}  (right-click ≡ to fix)", 5000)
            else:
                self.store.set_no_match([key])
                self.status("not found on VNDB — fix it in Stats › Library", 5000)
            self.data_changed()

        self.worker.submit(job, done)

    # ------------------------------------------------------------------ clipboard + main loops
    def on_text(self, text):
        if not self.uses_clipboard():
            return
        exe, title = foreground_window()
        key = self.resolve_game(exe, title, "clipboard")
        if not key:
            return
        n, why = self.tracker.add(text, key)
        if n:
            self._line_counted(key, exe, n)
        elif why == "too long":
            self.status(f"skipped clipboard ({why})")

    def poll(self):
        try:
            self.worker.pump()
            self.pump_ocr()
            self.pump_extras()  # global hotkeys, finished backups
            if self._show_event and kernel32.WaitForSingleObject(self._show_event, 0) == 0:
                self.show_overlay()  # a hidden overlay comes back when the shortcut is clicked again
                self.open_stats()  # the shortcut was clicked again
                win = self.windows.get("stats")
                if win is not None and win.winfo_exists():
                    win.deiconify()
                    win.attributes("-topmost", True)
                    win.after(200, lambda: win.winfo_exists() and win.attributes("-topmost", False))
            seq = clipboard_seq()
            st = self.state
            if seq != st["seq"]:
                try:
                    text = self.root.clipboard_get()
                except tk.TclError:
                    text = None  # not text, or clipboard locked by the writer
                if text is None and st["retries"] < 3:
                    st["retries"] += 1  # try again next poll
                else:
                    st["seq"], st["retries"] = seq, 0
                    if text:
                        self.on_text(text)
        except Exception as e:  # never let the poll loop die
            self.status(f"error: {e}", 5000)
        finally:
            if not self._closing:
                self.root.after(int(self.cfg["poll_ms"]), self.poll)

    def tick(self):
        try:
            if self.ocr["watcher"]:
                self.ocr["watcher"].enabled = self.uses_ocr() and not self.tracker.paused
                self.follow_game_region()
            now = time.time()
            if now - self._last_check >= 3:
                self._last_check = now
                ended = self.sessions.check(running_exe_names(), now)
                if ended:
                    self._session_ended(ended)
            self.tick_extras()  # daily backup, Discord status
            self.tick_qol()  # break reminder, tray tooltip
            self.refresh()
        except Exception as e:  # noqa: BLE001
            self.status(f"error: {e}", 5000)
        finally:
            if not self._closing:
                self.root.after(1000, self.tick)

    # ------------------------------------------------------------------ actions
    def toggle_pause(self):
        self.tracker.set_paused(not self.tracker.paused)
        self.status("paused" if self.tracker.paused else "resumed")
        self.refresh()

    def undo(self):
        self.status("removed last line" if self.tracker.undo() else "nothing to undo")
        self.data_changed()

    def rename_current(self):
        from tkinter import simpledialog
        t, store = self.tracker, self.store
        if not t.last_game:
            self.status("no game yet")
            return
        name = simpledialog.askstring("Rename game", "Name for this game:",
                                      initialvalue=store.game_name(t.last_game), parent=self.root)
        if name and name.strip():
            store.rename_key(t.last_game, name.strip())
            self.data_changed()

    def fix_current(self):
        t, store = self.tracker, self.store
        if not t.last_game or t.last_game == "unknown":
            self.status("no game yet")
            return
        vn = store.game_vn(t.last_game)
        grp = vn["id"] if vn else "name:" + store.game_name(t.last_game)
        self.fix_match_dialog(grp, store.game_name(t.last_game), self.root)

    def quit_app(self):
        if self._closing or self.qol_close_to_tray():  # "close to tray" hides instead
            return
        self._closing = True
        try:
            self.cfg["overlay_x"], self.cfg["overlay_y"] = self.root.winfo_x(), self.root.winfo_y()
            save_config(self.cfg)
        except tk.TclError:
            pass
        try:
            self.sessions.end("quit", time.time())
        finally:
            self.shutdown_extras()  # unregister hotkeys, clear the Discord status
            self.shutdown_qol()  # remove the tray icon
            try:
                self.store.db.close()
            finally:
                self.root.destroy()


def run_gui():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:  # own taskbar identity, so its windows group under the 字 icon instead of Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VNCharTracker.App")
    except Exception:
        pass
    if not single_instance():
        ev = show_event()  # already running: ask that copy to bring up the Library, then leave quietly
        if ev:
            kernel32.SetEvent(ev)
        return
    App().run()


if __name__ == "__main__":
    run_gui()
