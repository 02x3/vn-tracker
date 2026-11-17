"""App mixin: text box that follows the game window, backups, global hotkeys, Discord status.
Kept out of tracker.py so that file only needs small hook calls. Must not `import tracker`: use `self.lib`."""
import datetime as dt
import os
import queue
import threading
import time
import tkinter as tk

import backup
import discord_rpc
import hotkeys
import winregion


class ExtrasMixin:
    # ------------------------------------------------------------------ setup / teardown
    def init_extras(self):
        cfg = self.cfg
        self._overlay_hidden = False
        self._cur_spec = None
        self._upgrade_done: set = set()
        self._hk_failed_shown = None
        self._bk_queue: queue.Queue = queue.Queue()
        self._bk_running = False
        self._bk_day = None
        self._bk_error = None
        self._bk_next_check = 0.0
        # text box spec: prefer the relative one saved with the absolute rect it was made from
        spec = winregion.parse_spec(cfg.get("ocr_region_spec"))
        if spec and cfg.get("ocr_region") and spec.get("abs") != list(cfg["ocr_region"]):
            spec["abs"] = list(cfg["ocr_region"])
        self._cur_spec = spec or winregion.parse_spec(cfg.get("ocr_region"))
        if self._cur_spec and self.ocr.get("watcher"):
            self._set_region_quiet(winregion.resolve_spec(self._cur_spec, self._find_client))
        # hotkeys
        user = cfg.get("hotkeys") if isinstance(cfg.get("hotkeys"), dict) else {}
        cfg["hotkeys"] = {a: str(user.get(a) or hotkeys.DEFAULTS[a]) for a in hotkeys.ACTIONS}
        self.hotkeys = hotkeys.HotkeyManager()
        self.apply_hotkeys()
        # discord (no thread is started unless it's enabled)
        self.discord = discord_rpc.DiscordRPC()
        self.apply_discord()
        # backups: one now (a moment after the window is up), then once a day
        self.root.after(4000, lambda: self.backup_now(manual=False))

    def shutdown_extras(self):
        for fn in (lambda: self.hotkeys.stop(), lambda: self.discord.shutdown()):
            try:
                fn()
            except Exception:  # noqa: BLE001 - never block quitting
                pass

    # ------------------------------------------------------------------ text box follows the game window
    def _find_client(self, exe):
        return winregion.find_game_client(exe, os.getpid())

    def make_region_spec(self, region, exe):
        """Spec for a screen rectangle selected over the window of `exe` (relative when that window is found
        and the box lies inside it, otherwise just the absolute rectangle)."""
        region = [int(v) for v in region]
        rect = None
        if exe and not self.lib.is_non_game(exe, self.cfg):
            rect = self._find_client(exe.lower())
            if rect:
                cx, cy = (region[0] + region[2]) // 2, (region[1] + region[3]) // 2
                if not (rect[0] <= cx < rect[2] and rect[1] <= cy < rect[3]):
                    rect = None
        return winregion.make_spec(region, exe, rect)

    def region_spec_for_selection(self, region):
        """Called by apply_region: finds the game window under the new box and returns its spec."""
        try:
            scene = self.lib.scan_windows(region, os.getpid(), self.cfg.get("ocr_block_processes") or [])
            exe = scene["game"][0] if scene.get("game") else None
        except Exception:  # noqa: BLE001
            exe = None
        return self.make_region_spec(region, exe)

    def current_region_spec(self, exe=None):
        """Spec of the box being watched now (abs = what the watcher uses), tied to `exe` when possible."""
        region = self.watcher_region()
        if not region:
            return None
        spec = self._cur_spec
        if spec and spec.get("rel") and (not exe or spec.get("exe") == os.path.normcase(exe)):
            return dict(spec, abs=list(region))
        return self.make_region_spec(region, exe)

    @staticmethod
    def _spec_ident(spec):
        if spec.get("rel"):
            return ("rel", spec.get("exe"), tuple(spec["rel"]))
        return ("abs", tuple(spec.get("abs") or ()))

    def _set_region_quiet(self, region):
        w = self.ocr["watcher"]
        if w and region and w.region != region:
            w.region = list(region)  # no dedupe reset: same text, the window just moved or resized

    def _upgrade_spec(self, key, spec):
        """An old plain region becomes a relative one the first time its game's window is found under it."""
        if spec.get("rel") or not key or key in self._upgrade_done or not key.endswith(".exe") or not os.path.isabs(key):
            return spec
        rect = self._find_client(key)
        if not rect:
            return spec
        self._upgrade_done.add(key)
        new = self.make_region_spec(spec["abs"], key)
        if new.get("rel"):
            self.store.set_region(key, new)
            return new
        return spec

    def follow_region(self):
        """Every tick: recompute the absolute text box from the game's current window position."""
        key = self.tracker.locked_game
        if not key:
            exe, _ = self.lib.foreground_window()
            key = exe.lower() if exe else None
        spec = self.store.get_region_spec(key)
        if spec:
            spec = self._upgrade_spec(key, spec)
        else:
            spec = self._cur_spec
        if not spec:
            return
        region = winregion.resolve_spec(spec, self._find_client)
        if not region:
            return
        cur = self._cur_spec
        if cur is None or self._spec_ident(spec) != self._spec_ident(cur):
            self._cur_spec = spec
            self.set_watch_region(region, announce=True)
        else:
            self._cur_spec = spec
            self._set_region_quiet(region)

    # ------------------------------------------------------------------ overlay hide / show
    def overlay_hidden(self):
        return self._overlay_hidden

    def hide_available(self):
        return bool(self.cfg.get("hotkeys_enabled", True)) and "hide" in self.hotkeys.registered

    def hide_overlay(self):
        if not self.hide_available():
            self.status("turn on hotkeys (Settings) to hide the overlay", 4000)
            return
        self._overlay_hidden = True
        self.root.withdraw()

    def show_overlay(self):
        self._overlay_hidden = False
        try:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass

    def toggle_overlay(self):
        if self._overlay_hidden:
            self.show_overlay()
        else:
            self.hide_overlay()

    # ------------------------------------------------------------------ hotkeys
    def hotkey_text(self, action):
        user = self.cfg.get("hotkeys") if isinstance(self.cfg.get("hotkeys"), dict) else {}
        return hotkeys.pretty(user.get(action) or hotkeys.DEFAULTS[action])

    def apply_hotkeys(self):
        """(Re)registers the configured combos. Combos that are taken are shown in settings and the status."""
        cfg = self.cfg
        bindings = dict(cfg["hotkeys"]) if cfg.get("hotkeys_enabled", True) else {}
        try:
            self.hotkeys.configure(bindings, wait=True)
        except Exception as e:  # noqa: BLE001
            self.status(f"hotkeys unavailable: {e}", 5000)
            return
        if not bindings and self._overlay_hidden:
            self.show_overlay()  # nothing could bring it back otherwise
        self._report_hotkey_failures()

    def _report_hotkey_failures(self):
        failed = dict(self.hotkeys.failed)
        if failed != self._hk_failed_shown:
            self._hk_failed_shown = failed
            if failed:
                names = ", ".join(f"{self.hotkey_text(a)} ({why})" for a, why in failed.items())
                self.status("hotkey not available: " + names, 7000)

    def run_hotkey(self, action):
        if action == "pause":
            self.toggle_pause()
        elif action == "undo":
            self.undo()
        elif action == "hide":
            self.toggle_overlay()
        elif action == "region":
            self.select_region()
        elif action == "library":
            self.show_library()

    def show_library(self):
        self.open_stats("library")
        win = self.windows.get("stats")
        if win is not None and self._alive(win):
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
            win.after(200, lambda: self._alive(win) and win.attributes("-topmost", False))

    # ------------------------------------------------------------------ backups
    def backup_dir(self):
        return backup.backups_dir(self.lib.DATA_DIR)

    def backup_now(self, manual=True, callback=None):
        """Backs up reading.db on a background thread (sqlite backup API, safe while open)."""
        if self._bk_running:
            return
        self._bk_running = True
        keep, folder, db_path = int(self.cfg.get("backup_keep", 7) or 7), self.backup_dir(), self.lib.DB_PATH

        def job():
            try:
                self._bk_queue.put((manual, callback, backup.backup_now(db_path, folder, keep), None))
            except Exception as e:  # noqa: BLE001
                self._bk_queue.put((manual, callback, None, e))

        threading.Thread(target=job, daemon=True, name="Backup").start()

    def _pump_backups(self):
        while True:
            try:
                manual, callback, path, err = self._bk_queue.get_nowait()
            except queue.Empty:
                return
            self._bk_running = False
            self._bk_error = err
            if path:
                self._bk_day = dt.date.today().isoformat()
            if manual:
                self.status("backup done" if path else f"backup failed: {err}", 3500)
            if callback:
                try:
                    callback(path, err)
                except tk.TclError:
                    pass

    def last_backup_info(self):
        return backup.last_backup(self.backup_dir())

    def _maybe_daily_backup(self, now):
        if now < self._bk_next_check:
            return
        self._bk_next_check = now + 60
        if self._bk_day and self._bk_day != dt.date.today().isoformat() and not self._bk_error:
            self.backup_now(manual=False)

    # ------------------------------------------------------------------ discord
    def apply_discord(self):
        cfg = self.cfg
        self.discord.configure(cfg.get("discord_enabled", False), cfg.get("discord_client_id", ""))
        if not cfg.get("discord_enabled", False):
            self.discord.update(None)

    def discord_activity(self):
        cur = self.sessions.current
        if not cur or self.tracker.paused:
            return None, None
        store, lib = self.store, self.lib
        key = cur["game"]
        chars, secs = store.sum_since(store.day_start_epoch())
        return discord_rpc.build_activity(self.cfg, store.game_name(key), store.game_vn(key), cur.get("start"),
                                          chars, secs, lib.fmt_int, lib.fmt_speed), key

    def _discord_tick(self):
        if not self.cfg.get("discord_enabled", False):
            return
        act, key = self.discord_activity()
        self.discord.update(act, key)

    # ------------------------------------------------------------------ hooks called from poll / tick
    def pump_extras(self):
        try:
            while True:
                try:
                    (action,) = self.hotkeys.events.get_nowait()
                except queue.Empty:
                    break
                self.run_hotkey(action)
            self._pump_backups()
        except Exception as e:  # noqa: BLE001
            self.status(f"error: {e}", 5000)

    def tick_extras(self):
        try:
            now = time.time()
            self._maybe_daily_backup(now)
            self._discord_tick()
        except Exception as e:  # noqa: BLE001
            self.status(f"error: {e}", 5000)
