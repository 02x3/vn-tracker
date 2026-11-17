"""Automatic backups of reading.db with the sqlite3 backup API (safe while the app has it open)."""
import datetime as dt
import os
import re
import sqlite3

_NAME_RE = re.compile(r"^reading-(\d{4}-\d{2}-\d{2})\.db$")


def backups_dir(data_dir):
    return os.path.join(data_dir, "backups")


def list_backups(folder):
    """Existing backups, oldest first: [(date string, path)]."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = sorted((m.group(1), os.path.join(folder, n)) for n in names if (m := _NAME_RE.match(n)))
    return found


def last_backup(folder):
    """(path, mtime) of the newest backup, or None."""
    items = list_backups(folder)
    if not items:
        return None
    path = items[-1][1]
    try:
        return path, os.path.getmtime(path)
    except OSError:
        return None


def has_backup_for(folder, day):
    return os.path.exists(os.path.join(folder, f"reading-{day}.db"))


def backup_now(db_path, folder, keep=7, today=None):
    """Copies db_path to folder/reading-YYYY-MM-DD.db (replacing today's earlier one), then keeps only
    the newest `keep` backups. Uses its own connection, so it can run on any thread. Returns the new path."""
    os.makedirs(folder, exist_ok=True)
    day = today or dt.date.today().isoformat()
    final = os.path.join(folder, f"reading-{day}.db")
    tmp = final + ".part"
    src = sqlite3.connect(db_path, timeout=10)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(tmp, final)
    rotate(folder, keep)
    return final


def rotate(folder, keep):
    keep = max(1, int(keep or 7))
    items = list_backups(folder)
    for _, path in items[:-keep] if len(items) > keep else []:
        try:
            os.remove(path)
        except OSError:
            pass
