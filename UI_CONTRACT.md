# UI contract (shared by tracker.py, ui_stats.py, ui_settings.py, ui_dialogs.py)

The UI is being rebuilt as a "cute and minimalistic" pass with themes. Non-UI logic in tracker.py
(counting, OCR watcher, VNDB, Store, Tracker, SessionLog) already works. **Don't change it**
beyond what's listed here.

## Files and owners
| file | owner | what |
|---|---|---|
| `tracker.py` → `run_gui()` and the `App` object | core agent | overlay, wiring, OCR/clipboard polling, sessions, menu, theme switching, region select |
| `ui_theme.py` | core agent, append-only | palettes + widgets (already written: read it first) |
| `ui_stats.py` | stats agent | `open_stats(app, geometry=None, state=None)` |
| `ui_settings.py` | settings agent | `open_settings(app, geometry=None, state=None)` |
| `ui_dialogs.py` | settings agent | `fix_match_dialog(app, grp, current_name, parent)`, `choose_game_dialog(app, parent)` |

The ui_* modules must **not** `import tracker`; the app may run as `__main__`, which would load it twice.
Use `app.lib` instead, which is the tracker module object.

## The `app` object (built in run_gui; a plain class with these attributes)

| name | what |
|---|---|
| `app.root` | `tk.Tk` (the overlay window; parent for Toplevels) |
| `app.cfg` | config dict; call `app.save_config()` after changing it |
| `app.lib` | the tracker module: `fmt_int, fmt_dur, fmt_speed, vndb_search, download_cover, clean_title, count_chars, STATUSES, virtual_screen` ... |
| `app.store` | `Store`: `library(), totals(), daily(n=None), recent_lines(limit), sessions(limit), streak(), sum_since(ts), day_start_epoch(), today_str(), set_status(grp, s), rename_group(grp, name), group_keys(grp), delete_lines(ids), all_lines(), set_match(keys, vn, matched, cover_path), set_no_match(keys), set_cover_path(vid, path), ensure_game(key, name, hint=''), game_name(key), vn(vid)` |
| `app.tracker` | `Tracker`: `.locked_game`, `.last_game`, `.paused`, `.session_ids` (list of line ids this run) |
| `app.worker` | `.submit(fn, callback)`: runs `fn()` off the UI thread, then `callback(result, error)` on the UI thread |
| `app.P` | current palette dict (keys: `bg card card2 line fg dim accent accent_fg good warn bad`). It's the same dict object for the app's lifetime, updated in place on theme change. Read colors when building widgets. |
| `app.F` | `ui_theme.Fonts`: named fonts `xs sm md mdb lg xl h1`; `.available()` lists installed font choices |
| `app.style` | the `ttk.Style` (already styled by `ui_theme.style_ttk`) |
| `app.cute()` | bool: cute extras on (kaomoji, ✿, ♡). Keep cute text optional and short. |
| `app.status_color(status)` | color for "Reading" / "Finished" / "On hold" / "Dropped" |
| `app.cover_photo(vn, w, h, radius=0)` | cached `PhotoImage` of a VN's cover (dict from `store.vn()` / library item `["vn"]`), rounded corners if radius > 0, blurred if NSFW, placeholder if none |
| `app.status(msg, ms=2500)` | small message on the overlay |
| `app.refresh()` | redraw overlay numbers |
| `app.data_changed()` | data changed: refresh the overlay and call every callable in `app.listeners` |
| `app.listeners` | list; a window appends its refresh fn; it's removed automatically when it raises `tk.TclError` |
| `app.windows` | dict `"stats"` / `"settings"` → Toplevel; set it when you open your window |
| `app.apply_theme()` | re-read theme/font from cfg, restyle ttk, rebuild the overlay, and **destroy + reopen** open stats/settings windows via `open_stats(app, geometry, state)` / `open_settings(app, geometry, state)`. Before destroying, it passes `win.ui_state` (any dict your window keeps up to date, e.g. current tab or scroll position) back as `state`. Call it with `app.root.after_idle(app.apply_theme)` from inside event handlers. |
| `app.open_stats(page=None)`, `app.open_settings()` | open (or raise) those windows |
| `app.fix_match_dialog(grp, name, parent)`, `app.choose_game_dialog(parent)` | the dialogs |
| `app.select_region()`, `app.flash_region()` | pick / show the OCR text box |
| `app.lock_game(key)`, `app.unlock_game()`, `app.add_vndb_game(vn) -> key` | manual game choice |
| `app.delete_group(grp, ignore_program=False)` | delete a library entry (games, lines, sessions); optionally ignore its program from now on |
| `app.sync_vndb(callback=None)` | pull the linked VNDB user's list (`cfg["vndb_user"]`) into the Library: fetch on the worker, import on the UI thread (`store.import_vndb_list`), covers downloaded in the background, then `data_changed()` and `status("VNDB: added N, updated M")`. `callback((added, updated), error)` when done. Library items from VNDB carry `source == "vndb"` (show "from your VNDB list" when `chars == 0`). Runs ~5s after launch if linked and `vndb_sync_on_start`. |
| `app.set_text_source(src)` | `"ocr" | "clipboard" | "both"`; saves and starts OCR if needed |

## Look
- `ui_theme.py` has: `PRESETS` (Sakura default, Matcha, Latte, Sky, Lavender, Midnight, Mono), `CUSTOMIZABLE`,
  `palette(cfg)`, `mix(a, b, t)`, `Card` (rounded surface, children go in `.body`), `Pill` (rounded button;
  kinds accent/soft/ghost/chip), `Switch`, `ScrollFrame`, `rounded_rect`, `rounded_image`, `style_ttk`.
- Style: soft, airy, rounded, minimal. Generous padding, no hard borders, secondary info in `dim`,
  one accent. Use Cards for grouping and Pills for buttons; no default grey ttk buttons.
  Must look right in light themes (Sakura) **and** dark ones (Midnight).
- Text sizes: `F["h1"]` window titles, `F["lg"]`/`F["xl"]` numbers, `F["md"]` body, `F["sm"]`/`F["xs"]` secondary.
- Cute extras only when `app.cute()`: e.g. "reading log ✿" title, "(・ω・)" in empty states.
  **Only BMP characters**: Tk 8.6 can't render emoji above U+FFFF and may crash on them.

## Customization options (config keys, all applied live through `app.apply_theme()` / `app.refresh()`)
- `ui_scale` (0.9 / 1.0 / 1.15 / 1.3) scales every named font in `Fonts`. `Fonts.update_from(cfg)` re-reads
  `font`, `number_font`, `ui_scale`, `overlay_size`. Big numbers use `F["xl_num"]` / `F["lg_num"]` (overlay count: `F["ov_num"]`).
- `corner_style` `round|soft|sharp` is a radius multiplier (`ui_theme.rad(r)`, min 3px). Card, Pill, Switch and
  `app.cover_photo(radius=...)` apply it themselves: always pass the "round" radius.
- `number_format` `comma|dot|space|man`: `tracker.fmt_int` / `fmt_speed` read a module-level setting
  (`tracker.set_number_format`, called on load and in `apply_theme`). Always format numbers with `app.lib.fmt_int`.
- `cute_symbol` (✿ ❀ ✦ ★ ♡ ♪): use `app.sym()` (symbol or "" when cute is off) / `app.mark()` (" ✿" or "") instead of a hardcoded ✿.
- `theme_custom` can now also hold `good`, `warn`, `bad`.
- Overlay: `overlay_main` today|session|total, `overlay_unit` 字|chars|none (none = just "today"/"this session"/"total"),
  `overlay_size` small|normal|large, `overlay_show_title|sub|session|goal`. Compact mode wins over the toggles.
- Stats: `stats_default_page` (used when `open_stats()` has no explicit page), `library_card_size` small|medium|large,
  `chart_days` 14|30|60|90, `library_sort` (written by the Library sort menu).
- Settings has "Reset look to defaults" (`ui_settings.LOOK_KEYS`) and "Reset all settings" (everything in
  `DEFAULT_CONFIG` except `ui_settings.KEEP_ON_RESET_ALL`); both confirm, save and call `apply_theme`.
- New options that change how things are drawn must work through the in-place rebuild (`rebuild_stats`,
  `open_settings(into=win)`): never close and reopen the windows.

## Config keys involved
`theme`, `theme_custom` (dict of CUSTOMIZABLE key → "#rrggbb"), `font`, `cute`, `overlay_compact`, `overlay_cover`,
`overlay_alpha`, `blur_nsfw_covers`, `vndb_auto_match`, `afk_seconds`, `day_start_hour`, `daily_goal`,
`text_source`, `session_gap_minutes`, `vndb_user` (id like u12345), `vndb_username`, `vndb_last_sync` (ts),
`vndb_sync_on_start`.

## Extras: window-following text box, backups, hotkeys, Discord
`App` also inherits `app_extras.ExtrasMixin` (logic lives there, not in tracker.py). New `app` methods:
| name | what |
|---|---|
| `app.hide_overlay()`, `app.show_overlay()`, `app.toggle_overlay()`, `app.overlay_hidden()` | hide/show the overlay (`root.withdraw()`); hiding is refused unless the "hide" hotkey is registered. Not persisted across restarts. |
| `app.apply_hotkeys()` | re-register `cfg["hotkeys"]` (action → "ctrl+alt+p"; actions `pause undo hide region library`) if `cfg["hotkeys_enabled"]`. Call after changing either key. Taken combos land in `app.hotkeys.failed` ({action: reason}) and the status line. |
| `app.hotkey_text(action)` | display string like "Ctrl+Alt+P" |
| `app.backup_now(manual=True, callback=None)` | background `data/backups/reading-YYYY-MM-DD.db` copy; `callback(path, err)` on the UI thread. `app.last_backup_info()` -> `(path, mtime)` or None, `app.backup_dir()` |
| `app.apply_discord()` | push `discord_enabled` / `discord_client_id` to `app.discord` (`discord_rpc.DiscordRPC`); `app.discord.status()` -> "connected" / "Discord not running" / "needs an Application ID" / "disabled" |
| `app.show_library()` | open and raise the Library |
| `app.follow_region()` | per-tick: recompute the text box from the game's window (called by `follow_game_region`) |
| `app.current_region_spec(exe)`, `app.region_spec_for_selection(region)` | build a stored region spec |

New config keys: `ocr_region_spec`, `backup_keep` (7), `hotkeys_enabled` (True), `hotkeys` (dict), `discord_enabled` (False),
`discord_client_id`, `discord_title_lang` (english|japanese), `discord_show_cover`, `discord_show_chars`.
`games.region` is now JSON `{"rel": [fractions of the window client rect], "exe": ..., "abs": [l,t,r,b]}`; the old plain
`[l,t,r,b]` list is still read (and upgraded to relative the first time the game's window is found).
`store.get_region(key)` still returns the absolute list; `store.get_region_spec(key)` returns the dict.
`scan_windows()` also returns `"hwnd"` of the game window. New files: `winregion.py`, `backup.py`, `hotkeys.py`,
`discord_rpc.py`, `app_extras.py`, `ui_settings_extra.py` (settings sections: hotkeys, backups, discord).

## Goals, heatmap, manual entries, progress
Logic modules (no GUI, no `import tracker`; call them from ui_* with a plain `import`): `goals.py`, `manual.py`, `progress.py`.
UI: `ui_heatmap.Heatmap(parent, app, weeks=26, on_click=fn(day_iso))` (a Canvas; `.set_data(store.daily() rows)`).

New config keys (all in `DEFAULT_CONFIG`): `weekly_goal` (chars, 0 = off), `week_starts` (`monday|sunday`),
`overlay_goal_mode` (`daily|weekly|both`: "both" draws a second thin bar), `chars_per_minute` (450; estimate factor),
`goal_toast_day` / `goal_toast_week` (internal: last day / week a "goal reached" toast was shown).

| name | what |
|---|---|
| `app.manual_entry_dialog(parent=None, grp=None)` | "Add reading" dialog (`ui_dialogs.manual_entry_dialog`); `grp` pre-selects a Library entry. Calls `app.data_changed()` after saving. In the overlay menu, the Stats header and the Library card menu. |
| `goals.week_summary(store)` | `{chars, seconds, goal, start, frac}` for this week (weeks follow `day_start_hour`); `goals.weekly_goal(cfg)`, `goals.daily_goal(cfg)`, `goals.logical_today(cfg)`, `goals.week_start_day(cfg, day)` |
| `goals.overlay_bars(cfg, store, today_chars)` | fractions of the overlay goal bar(s); `goals.check_milestones(app, today_chars)` shows the "goal reached" toasts |
| `manual.add_entry(store, grp, name, chars, minutes, day, note="")` | `grp` = a library group (vndb id or `name:<title>`) or None for a new title called `name`. Returns `(game_key, line_id)` |
| `manual.is_manual(text)`, `manual.display_text(text)`, `manual.lines_for_day(store, "YYYY-MM-DD")`, `manual.cleanup(store)` | helpers; call `cleanup` after deleting lines |
| `progress.all_totals(store)`, `progress.set_user_total(store, vid, n)`, `progress.start_fetch(app)`, `progress.card_progress(item, totals, overall_chars, overall_seconds, cpm=None)`, `progress.card_texts(prog, fmt_int)` | per-VN total characters and percent read |

Manual entries are normal `lines` rows (text `"[manual] note"`) under the game key `manual:log:<group>` plus a
`sessions` row with reason `manual`, so they count in totals, days, weeks, library and the heatmap. The key
prefix `manual:` already means "added by hand" elsewhere (never auto-matched, never a program name).
Progress: table `vn_totals(vid, total_chars, source, fetched_at)` (`user` wins over `jiten`; `none` = jiten
doesn't know it, re-checked after 14 days). The jiten.moe lookups run on `app.worker` in small sequential batches
(`app.lib._http`). With no stored total the card shows an estimate (VNDB `length_minutes` x `chars_per_minute`,
drawn paler and marked "≈"). Heatmap click opens the Lines page filtered to that reading day
(`ui_state["line_day"]`).

## Testing without touching the user's data
- Run Python as meikipop's venv Python (e.g. `%USERPROFILE%\meikipop\meikipop\.venv\Scripts\python.exe`) (it has Pillow, mss, meikiocr).
- Set env `VN_TRACKER_DATA` to a scratch folder so the real `data/` folder is never touched.
- The user's real tracker may be running. **Never kill it.** Test instances use a separate data dir.
  The core agent makes the single-instance lock depend on `VN_TRACKER_DATA`.
- Write files with the file tools, not bash heredocs (heredocs mangle backslashes and Japanese here).
  Run commands with PowerShell.
- Screenshots: PowerShell + System.Drawing `CopyFromScreen`, then view the PNG.


## Lookups, VNDB status push, Read next
Logic modules (no GUI, no `import tracker`): `lookups.py`, `vndb_push.py`, `readnext.py`. App glue: `app_more.MoreMixin`
(App's bases: `ExtrasMixin, MoreMixin`; `app.init_more()` runs after `init_extras()`). UI: `ui_more.py`
(`fill_tile`, `attach`, `LookupTrend`, `ReadNextPage`, `build_settings`), hooked from `ui_stats` / `ui_settings`.

New config keys (all in `DEFAULT_CONFIG`): `vndb_token` (""; kept by "Reset all settings"), `vndb_push_enabled` (True),
`lookups_enabled` (True), `read_next_sort` ("Easiest first" | "Shortest first" | "Best rated").

| name | what |
|---|---|
| `tracker._http(url, body=None, timeout=15, method=None, headers=None)` | now takes an HTTP `method` ("PATCH") and extra `headers` (also in the curl fallback) |
| `store.on_status` | optional hook `fn(grp, status)` called by `Store.set_status` when a group's status really changed. `vndb_push.install(app)` sets it, so menu changes, auto-finish and "Start reading" all push to VNDB. `import_vndb_list` writes SQL directly, so the "only import new VNs" sync never pushes |
| `app.more_listeners` | list of no-arg callables, run by `app.notify_more()` after every counted lookup (TclError removes them) |
| `app.on_popup()` | OCR watcher signal (`("popup", exe)` on the OCR queue, one per popup appearance, debounced 1 s in `lookups.PopupEdge`); counts a lookup via `lookups.count_popup` |
| `app.vndb_test_token(callback)` | GET /authinfo on the worker; `callback(text, ok)` |
| `app.refresh_read_next(force=False, callback=None)`, `app.start_reading(row)` | Read next refresh (worker batches) / start reading a row |
| `lookups.ensure/add/by_group/total/overall/weekly/per_1k/card_text/count_popup/game_active/delete_games` | table `lookups(id, ts, game)`; `by_group(store)` -> `{library group: count}`; `weekly(store, grp=None, weeks=12, week_starts)` -> `[(week_start, lookups, chars, per_1k)]`; per-1k needs >= 300 chars (`MIN_CHARS`) |
| `vndb_push.build_body(status, started, finished)`, `request_for(store, grp, status)`, `patch_ulist`, `authinfo`, `push_status(app, grp, status)`, `test_token(app, cb)`, `mask_token` | PATCH `https://api.vndb.org/kana/ulist/<vid>` with `Authorization: Token <t>` |
| `readnext.rows(app)`, `sort_rows(rows, mode)`, `refresh(app)`, `pending(app)`, `state(app)`, `start_reading(app, row)` | row = `{vid, title, alttitle, vn, chars, chars_est, diff, rating, length_minutes, in_library, status, source}` |

Lookups: a popup is counted only while the tracker is not paused, `lookups_enabled`, and a real game is being read
(`tracker.locked_game or last_game`, last line at most 30 min old). One row per appearance (`ts`, game key). Library
cards show "N lookups · X / 1k 字" (card menu: "Lookups: ... trend..." opens Days with that VN picked); the Stats
tile "Lookups" is overall lookups per 1,000 characters; Days has a weekly trend card (all VNs or one).
Deleting a library entry deletes its lookups.

VNDB push: labels via `labels_set` [new status label] and `labels_unset` [other status labels 1-5, wishlist too];
custom labels and Voted are untouched. Ids: Reading 1 (Playing), Finished 2, On hold 3 (Stalled), Dropped 4, Wishlist 5.
`started` = day of the first tracked line (Reading / Finished only, when known); `finished` = today (Finished only).
Only groups whose key is a VNDB id (`v123`) are sent. Result goes to `app.status(...)`. Settings has the masked token
field, "Test token" and "Get a token" (vndb.org/u/tokens needs "list write").

Read next (Stats page "next"): candidates = wishlist (POST `/ulist`, `user` = `cfg["vndb_user"]`, filter
`["label","=",5]`, sent with the token when set) + Library VNs with 0 characters and status Reading / On hold.
jiten.moe `/api/media-deck/<deck>/detail` gives `mainDeck.characterCount` and `difficultyRaw` (0-5; shown "x.x / 5").
No jiten data: length = VNDB `length_minutes` x `chars_per_minute` (shown with "≈"), difficulty "?" (sorted last).
Cache: table `read_next(vid, data JSON, fetched_at)` (row `_wishlist` = ids); jiten answers refresh after 30 days;
a found character count is also saved to `vn_totals` (Library progress). The first visit fetches once; Refresh
re-reads the wishlist and only fetches missing / stale VNs. Progress is pushed through `readnext.state(app)["listeners"]`.

## QoL pack: kanji, tray, startup, toasts, milestones, break reminder, speed chart
`App` also inherits `app_qol.QolMixin` (logic there; tracker.py only has hook calls: `init_qol`, `qol_line`,
`qol_session_ended`, `tick_qol`, `qol_close_to_tray`, `shutdown_qol`, `rebuild_qol`). No GUI module imports `tracker`.

New modules: `kanji.py` (unique kanji), `vnstats.py` (speed series), `qol_state.py` (persistent "already shown" flags),
`autostart.py` (Startup shortcut), `tray.py` (ctypes tray icon), `ui_toast.py`, `ui_kanji.py` (Stats page + tile + card menu
entries), `ui_vndetail.py` (VN detail window), `ui_settings_qol.py` (Settings section "windows & notifications").

New config keys (all in `DEFAULT_CONFIG`): `autostart` (False), `tray_enabled` (False), `tray_close_to_tray` (False),
`toast_session` (True), `toast_milestones` (True), `auto_finish_prompt` (True), `break_reminder` (False),
`break_reminder_minutes` (60), `kanji_sort` (`first|oldest|freq|rare`). Milestones / "finish asked" flags are NOT in config:
they live in the DB table `qol_state(k, v)` so "Reset all settings" never makes them repeat.

| name | what |
|---|---|
| `kanji.sync(store)` | incremental update of table `kanji_seen(game, ch, first_ts, count)` from `lines` (first call = backfill; a rebuild runs when lines were deleted). Manual entries are skipped. BMP kanji only. Called after every counted line. |
| `kanji.unique_count(store, grp=None)`, `kanji.per_vn_counts(store)` | unique kanji overall / for one Library group / `{grp: n}` |
| `kanji.kanji_list(store, grp=None, sort)` | `[(ch, first_ts, count, first_game_name)]`, sort `first|oldest|freq|rare` |
| `kanji.new_between(store, since, until=None)`, `kanji.new_per_day(store, days)`, `kanji.new_per_vn_day(store, grp, days)`, `kanji.new_today(store)` | first-seen kanji: `[(first_ts, ch)]`, `[(day, n)]` |
| `vnstats.speed_by_session(store, grp)`, `vnstats.speed_by_day(store, grp)`, `vnstats.summary(store, grp)` | chars/hour series for the detail chart (points under 2 min of reading are dropped) |
| `qol_state.get/put/seen/mark(store, key)` | tiny persistent flags; `mark` returns True the first time |
| `autostart.enable/disable/is_enabled/set_enabled(on, folder=None)`, `autostart.startup_dir(folder=None)` | `VN Tracker.lnk` in the Startup folder, same target as the Desktop shortcut (pythonw.exe next to `sys.executable`, arg `tracker.py`, icon `icon.ico`). **Tests:** `folder=` or env `VN_TRACKER_STARTUP_DIR`; if `VN_TRACKER_DATA` is set the folder defaults to `<data>/startup`, never the real one. Needs PowerShell (COM `WScript.Shell`). No registry Run key. |
| `tray.TrayIcon(on_event, menu_provider, tooltip)` | `.add()`, `.remove()`, `.exists()`, `.set_tooltip()`; `on_event("click" or "menu", id)`. Always `remove()` it (the app does in `shutdown_qol`). |
| `app.apply_qol()` | makes the tray icon and the Startup shortcut match `tray_enabled` / `autostart`; also runs from `apply_theme`. `app.set_autostart(on, callback=None)` does the shortcut on the worker. `app.tray` is the icon or None. |
| `app.tray_action(kind, arg)`, `app.tray_toggle_overlay()` | tray menu ids: 1 show/hide overlay, 2 open Library, 3 pause/resume, 4 quit. Hiding from the tray works without the hide hotkey. With `tray_close_to_tray` the overlay x / window close hides instead of quitting (tray Quit really quits). |
| `app.toast(title, lines, buttons=(), ms, kind)` | `ui_toast.show_toast`: one themed toast at a time near the overlay (queue), `buttons=[(label, callback, primary)]`; every toast is appended to `app.toast_log` |
| `app.session_toast_data(s)` | `(title, lines)` of the end-of-session toast: VN, chars, time, speed, new kanji (kanji first seen during the session) |
| `app.milestone_scan(key=None, seed=False)` | marks and returns newly reached milestones `[{id, title, lines}]`: total chars (100k, 250k, 500k, 1M, 2M, 5M, 10M, 20M, 50M), per VN (100k, 250k, 500k, 1M), VNs finished (1, 5, 10, 25, 50, 100). Marked even when popups are off. First run seeds everything already reached silently. |
| `app.finish_candidate(key)`, `app.check_auto_finish(key)` | VN at >= 100% of a known (user / jiten, not estimate) total, not Finished / Dropped, not asked before: toast "Mark finished" / "Not yet". Yes = `store.set_status(grp, "Finished")` + `app.data_changed()`. Asked once per VN (`qol_state` `fin_asked:<grp>`). |
| break reminder | `tick_qol`: after `break_reminder_minutes` of continuous reading (a gap over 5 min or a session end restarts the timer) one toast, then again each further interval |
| `app.open_vn_detail(grp)` | `ui_vndetail.open_vn_detail`: cover, totals, unique kanji, newest kanji, speed chart per session / per day. `app.windows["vn_detail"]`, rebuilt in place by `apply_theme` / `data_changed`. |
| `ui_kanji.fill_tile(sw)`, `build_page(sw, f)`, `fill_page(sw)`, `card_menu_items(sw, menu, item)`, `set_filter(sw, grp)` | Stats hooks (page `"kanji"`, tile `"kanji"`); the VN filter is kept in `app._kj_grp`, the sort in `cfg["kanji_sort"]` so theme rebuilds keep them |
