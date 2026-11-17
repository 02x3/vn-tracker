"""App mixin: tray icon, start with Windows, session summary toast, milestone popups, "mark finished?" prompt,
break reminder, unique-kanji upkeep, VN detail window. Kept out of tracker.py so that file only needs small
hook calls. Must not `import tracker`: use `self.lib`.

Hooks called from tracker.py:  init_qol (end of App.__init__), qol_line (every counted line),
qol_session_ended (a session ended), tick_qol (every second), qol_close_to_tray (top of quit_app),
shutdown_qol (quit), rebuild_qol (apply_theme).
"""
import os
import time
import tkinter as tk

import autostart
import kanji
import progress
import qol_state
import tray

TOTAL_STEPS = [100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000]
VN_STEPS = [100_000, 250_000, 500_000, 1_000_000]
FINISHED_STEPS = [1, 5, 10, 25, 50, 100]
BREAK_GAP = 300          # seconds without a counted line = you took a break (the reminder timer restarts)
CHECK_EVERY = 10         # seconds between milestone / finish checks while reading

T_TOGGLE, T_LIBRARY, T_PAUSE, T_QUIT = 1, 2, 3, 4


class QolMixin:
    # ------------------------------------------------------------------ setup / teardown
    def init_qol(self):
        self._qol = dict(cont_start=None, last_line=None, reminded=0, last_check=0.0, last_slow=0.0)
        self._force_quit = False
        self.tray = None
        self.toast_log = []
        try:
            qol_state.ensure(self.store)
            kanji.ensure(self.store)
            if not qol_state.seen(self.store, "ms_seeded"):  # first run: don't announce what you already reached
                self.milestone_scan(seed=True)
                qol_state.put(self.store, "ms_seeded", "1")
            self.cfg["autostart"] = autostart.is_enabled()  # the shortcut is the truth
        except Exception as e:  # noqa: BLE001
            self.status(f"extras: {e}", 4000)
        self.apply_qol()
        self.root.after(2500, self._kanji_warmup)

    def _kanji_warmup(self):
        try:
            kanji.sync(self.store)  # one-time backfill from existing lines (a no-op afterwards)
        except Exception as e:  # noqa: BLE001
            self.status(f"kanji: {e}", 4000)

    def shutdown_qol(self):
        try:
            if self.tray is not None:
                self.tray.remove()
                self.tray = None
        except Exception:  # noqa: BLE001 - never block quitting
            pass

    def apply_qol(self):
        """Makes the tray icon and the Startup shortcut match the settings (called at start and on rebuilds)."""
        cfg = self.cfg
        want = bool(cfg.get("tray_enabled", False))
        if want and self.tray is None:
            t = tray.TrayIcon(self._tray_event, self._tray_menu, "VN Tracker")
            if t.add():
                self.tray = t
            else:
                self.status("tray icon unavailable", 4000)
        elif not want and self.tray is not None:
            self.tray.remove()
            self.tray = None
        try:
            if bool(cfg.get("autostart", False)) != autostart.is_enabled():
                autostart.set_enabled(bool(cfg.get("autostart", False)))
        except Exception as e:  # noqa: BLE001
            cfg["autostart"] = autostart.is_enabled()
            self.status(f"start with Windows failed: {e}", 5000)

    def set_autostart(self, on, callback=None):
        """Settings toggle: creates / removes the Startup shortcut off the UI thread. callback(ok, err)."""
        def done(res, err):
            self.cfg["autostart"] = autostart.is_enabled()
            self.save_config()
            if err:
                self.status(f"start with Windows failed: {err}", 5000)
            if callback:
                try:
                    callback(not err, err)
                except tk.TclError:
                    pass
        self.cfg["autostart"] = bool(on)
        self.save_config()
        self.worker.submit(lambda: autostart.set_enabled(bool(on)), done)

    def rebuild_qol(self):
        """From apply_theme: re-sync tray / startup, restyle the detail window."""
        self.apply_qol()
        win = self.windows.get("vn_detail")
        if win is not None and self._alive(win):
            self._ui_call("ui_vndetail", "rebuild_vn_detail", win)

    # ------------------------------------------------------------------ tray
    def tray_active(self):
        return self.tray is not None and self.tray.added

    def _tray_menu(self):
        hidden = self.overlay_hidden()
        paused = self.tracker.paused
        return [(T_TOGGLE, "Show overlay" if hidden else "Hide overlay"),
                (T_LIBRARY, "Open Library"),
                (T_PAUSE, "Resume reading" if paused else "Pause reading"),
                None,
                (T_QUIT, "Quit")]

    def _tray_event(self, kind, arg):
        try:
            self.root.after(0, lambda: self.tray_action(kind, arg))  # leave the Win32 message handler first
        except tk.TclError:
            pass

    def tray_action(self, kind, arg=None):
        if kind == "click" or (kind == "menu" and arg == T_TOGGLE):
            self.tray_toggle_overlay()
        elif kind == "menu" and arg == T_LIBRARY:
            self.show_library()
        elif kind == "menu" and arg == T_PAUSE:
            self.toggle_pause()
        elif kind == "menu" and arg == T_QUIT:
            self._force_quit = True
            self.quit_app()

    def tray_toggle_overlay(self):
        if self.overlay_hidden():
            self.show_overlay()
        else:  # not hide_overlay(): that needs the hotkey, and the tray can always bring it back
            self._overlay_hidden = True
            self.root.withdraw()

    def qol_close_to_tray(self):
        """Top of quit_app: with "close to tray" on, the overlay's x / window close hides to the tray instead."""
        if self._force_quit or not self.cfg.get("tray_close_to_tray") or not self.tray_active():
            return False
        self._overlay_hidden = True
        self.root.withdraw()
        return True

    # ------------------------------------------------------------------ per line / per second
    def qol_line(self, key, n):
        now = time.time()
        q = self._qol
        try:
            kanji.sync(self.store)  # incremental: only the new line
        except Exception as e:  # noqa: BLE001
            self.status(f"kanji: {e}", 4000)
        if q["last_line"] is None or now - q["last_line"] > BREAK_GAP:
            q["cont_start"], q["reminded"] = now, 0
        q["last_line"] = now
        if now - q["last_check"] >= CHECK_EVERY:
            q["last_check"] = now
            self.qol_checks(key)

    def qol_checks(self, key=None):
        try:
            for m in self.milestone_scan(key):
                if self.cfg.get("toast_milestones", True):
                    self.toast(m["title"], m["lines"], kind="milestone", ms=9000)
            self.check_auto_finish(key or self.tracker.last_game)
        except Exception as e:  # noqa: BLE001
            self.status(f"extras: {e}", 4000)

    def tick_qol(self):
        now = time.time()
        q = self._qol
        if self.tray is not None and now - q.get("tray_tip", 0) > 5:  # tooltip shows today's number
            q["tray_tip"] = now
            try:
                chars = self.store.sum_since(self.store.day_start_epoch())[0]
                self.tray.set_tooltip(f"VN Tracker - {self.lib.fmt_int(chars)} today")
            except Exception:  # noqa: BLE001
                pass
        # break reminder
        if q["cont_start"] and q["last_line"]:
            if now - q["last_line"] > BREAK_GAP:
                q["cont_start"], q["reminded"] = None, 0   # you stopped for a while
            elif self.cfg.get("break_reminder") and not self.tracker.paused:
                mins = max(1.0, float(self.cfg.get("break_reminder_minutes") or 60))
                if now - q["cont_start"] >= mins * 60 * (q["reminded"] + 1):
                    q["reminded"] += 1
                    done = int((now - q["cont_start"]) // 60)
                    self.toast(f"time for a break{self.mark()}",
                               [f"you've been reading for {done} min", "rest your eyes, stretch, drink some water"],
                               kind="break", ms=12000)
        # slow checks (manual entries, new totals, finished count) even when no line arrives
        if now - q["last_slow"] >= 30:
            q["last_slow"] = now
            self.qol_checks(None)

    # ------------------------------------------------------------------ toasts
    def toast(self, title, lines=(), buttons=(), ms=7000, kind="info"):
        return self._ui_call("ui_toast", "show_toast", title, lines, buttons, ms, kind)

    def session_toast_data(self, s):
        """(title, lines) of the end-of-session summary for a SessionLog.end() dict."""
        lib = self.lib
        new = kanji.new_between(self.store, s["start"], s["end"] + 1)
        lines = [f"{lib.fmt_int(s['chars'])} 字 · {lib.fmt_dur(s['seconds'])} · {lib.fmt_speed(s['chars'], s['seconds'])}"]
        if new:
            shown = "".join(ch for _, ch in new[:14]) + ("…" if len(new) > 14 else "")
            lines.append(f"{len(new)} new kanji: {shown}")
        else:
            lines.append("no new kanji this time")
        return f"session done{self.mark()}  {s['name']}", lines

    def qol_session_ended(self, s):
        q = self._qol
        q["cont_start"], q["reminded"] = None, 0  # a session end is a break
        try:
            kanji.sync(self.store)
            if self.cfg.get("toast_session", True) and s:
                title, lines = self.session_toast_data(s)
                self.toast(title, lines, kind="info", ms=8000)
            self.qol_checks(s["game"] if s else None)
        except Exception as e:  # noqa: BLE001
            self.status(f"extras: {e}", 4000)

    # ------------------------------------------------------------------ milestones
    def _group_of(self, key):
        row = self.store.db.execute("SELECT vndb_id, name FROM games WHERE key=?", (key,)).fetchone()
        if not row or key == "unknown":
            return None, None
        return (row[0] or "name:" + row[1]), row[1]

    def _group_chars(self, grp):
        keys = self.store.group_keys(grp)
        if not keys:
            return 0
        q = ",".join("?" * len(keys))
        return self.store.db.execute(f"SELECT COALESCE(SUM(chars),0) FROM lines WHERE game IN ({q})", keys).fetchone()[0]

    def _cross(self, prefix, steps, value):
        """Marks every step <= value that wasn't marked yet. Returns those steps (ascending)."""
        crossed = []
        for st in steps:
            if value >= st and qol_state.mark(self.store, f"ms:{prefix}:{st}"):
                crossed.append(st)
        return crossed

    def milestone_scan(self, key=None, seed=False):
        """Finds milestones reached and not shown yet, marks them as shown (always, so they never repeat even
        with popups off) and returns [{id, title, lines}] to display. seed=True marks everything already reached
        across the whole Library and returns []."""
        store, lib, out = self.store, self.lib, []
        mark = self.mark()
        total = store.totals()[0]
        c = self._cross("total", TOTAL_STEPS, total)
        if c and not seed:
            out.append(dict(id=f"total:{c[-1]}", title=f"{lib.fmt_int(c[-1])} characters read{mark}",
                            lines=[f"{lib.fmt_int(total)} 字 in total. Keep going!"]))
        fin = store.db.execute(
            "SELECT COUNT(DISTINCT COALESCE(vndb_id, 'name:' || name)) FROM games WHERE status='Finished' "
            "AND key IN (SELECT DISTINCT game FROM lines)").fetchone()[0]
        c = self._cross("finished", FINISHED_STEPS, fin)
        if c and not seed:
            n = c[-1]
            out.append(dict(id=f"finished:{n}", title="first VN finished" + mark if n == 1 else f"{n} VNs finished{mark}",
                            lines=["Congratulations!" if n == 1 else f"{n} visual novels completed."]))
        groups = []
        if seed:
            groups = [(it["grp"], it["name"], it["chars"]) for it in store.library() if not it["unknown"]]
        elif key:
            grp, name = self._group_of(key)
            if grp:
                groups = [(grp, name, self._group_chars(grp))]
        for grp, name, chars in groups:
            c = self._cross(f"vn:{grp}", VN_STEPS, chars)
            if c and not seed:
                out.append(dict(id=f"vn:{grp}:{c[-1]}", title=f"{lib.fmt_int(c[-1])} characters in {name}{mark}",
                                lines=[f"{lib.fmt_int(chars)} 字 in this VN so far."]))
        return out

    # ------------------------------------------------------------------ mark finished at 100%
    def finish_candidate(self, key):
        """(grp, name, chars, total) when this key's VN has read >= its known (non-estimate) total, hasn't been
        marked Finished/Dropped and wasn't asked about yet; else None."""
        if not key:
            return None
        grp, name = self._group_of(key)
        if not grp or qol_state.seen(self.store, f"fin_asked:{grp}"):
            return None
        row = self.store.db.execute(
            "SELECT status FROM games WHERE key=?", (key,)).fetchone()
        status = (row[0] if row else None) or "Reading"
        if status in ("Finished", "Dropped"):
            return None
        chars = self._group_chars(grp)
        vid = grp if not grp.startswith("name:") else None
        item = dict(grp=grp, vn=self.store.vn(vid) if vid else None, chars=chars, seconds=0, status=status)
        prog = progress.card_progress(item, progress.all_totals(self.store), chars, 0,
                                      cpm=self.cfg.get("chars_per_minute"))
        if not prog or prog["estimate"] or not prog["total"] or chars < prog["total"]:
            return None
        return grp, name, chars, prog["total"]

    def check_auto_finish(self, key):
        if not self.cfg.get("auto_finish_prompt", True):
            return None
        cand = self.finish_candidate(key)
        if not cand:
            return None
        grp, name, chars, total = cand
        qol_state.mark(self.store, f"fin_asked:{grp}")  # ask once, whatever the answer

        def yes():
            self.store.set_status(grp, "Finished")
            self.data_changed()  # same path as the Library menu, so anything hooked on status changes runs
        self.toast(f"{name} reached 100%{self.mark()}",
                   [f"{self.lib.fmt_int(chars)} of {self.lib.fmt_int(total)} 字 read.", "Mark it as finished?"],
                   [("Mark finished", yes, True), ("Not yet", None, False)], ms=30000, kind="finish")
        return grp

    # ------------------------------------------------------------------ windows
    def open_vn_detail(self, grp):
        return self._ui_call("ui_vndetail", "open_vn_detail", grp)
