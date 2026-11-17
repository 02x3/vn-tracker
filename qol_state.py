"""Tiny persistent key/value + "already shown" flags in the reading DB (table qol_state).
Kept in the DB instead of config.json so "Reset all settings" never makes milestones repeat.
No GUI, no `import tracker`."""


def ensure(store):
    store.db.execute("CREATE TABLE IF NOT EXISTS qol_state(k TEXT PRIMARY KEY, v TEXT)")
    store.db.commit()


def get(store, k, default=None):
    ensure(store)
    r = store.db.execute("SELECT v FROM qol_state WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def put(store, k, v):
    ensure(store)
    store.db.execute("INSERT OR REPLACE INTO qol_state(k, v) VALUES(?,?)", (k, str(v)))
    store.db.commit()


def seen(store, k):
    return get(store, k) is not None


def mark(store, k):
    """Returns True if `k` was not marked before (i.e. the caller should show it now)."""
    if seen(store, k):
        return False
    put(store, k, "1")
    return True
