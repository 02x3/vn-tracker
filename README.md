# VN Character Tracker

Counts the Japanese characters you read in visual novels, per day and per VN, and
builds a library with VNDB covers.

It reads the game's text box with OCR: the same local meikiocr model meikipop uses,
private and offline. No text hooker is needed. Hookers that copy lines to the clipboard
(Textractor, LunaHook...) work too.

## Install

Windows only. Needs Python 3.11+ with [meikiocr](https://github.com/rtr46/meikiocr), `onnxruntime`, `numpy`,
`Pillow`, `mss` and `certifi`.

- **If you use [meikipop](https://github.com/rtr46/meikipop):** its venv already has all of these.
  `VN Tracker.bat` looks for it in `%USERPROFILE%\meikipop\meikipop\.venv` and `%USERPROFILE%\meikipop\.venv`.
- **Otherwise:** `pip install meikiocr onnxruntime numpy pillow mss certifi`, and the launcher uses `pythonw` from PATH.
- **Another Python:** set the `VN_TRACKER_PYTHON` environment variable to its `pythonw.exe`.

Clipboard mode (for text hookers) works without the OCR packages.

## First run

1. Double-click `VN Tracker.bat`. It starts with meikipop's Python, which has meikiocr.
   A small overlay appears (top right; drag it anywhere). "OCR ready" shows after a few seconds.
2. Start your VN, right-click the overlay, choose **Select text box (OCR)…**, and drag a box
   around the dialogue box. Box only the text area, not the name plate or the whole window.
3. Read. Each new line is counted as soon as it finishes appearing.

Each game remembers its own text box, so you only select it once per game.
**Show text box** flashes the current box. The box is saved relative to the game's window, so it follows when you move or resize the game
(it falls back to the last screen position if the window can't be found).

## Which game is it?

- **Automatic**: the game is the window under the text box. On the first line from a new game
  it's looked up on VNDB (window title, then install folder, then exe name) and gets its title
  and cover. If the match is wrong, double-click the game name on the overlay.
- **By hand**: right-click → **Choose / add game…** (also in Stats → *Add / choose game…*):
  - pick one of your games,
  - search VNDB and add a new one, or
  - **Add without VNDB…** for anything that isn't on VNDB.

  The game you pick stays locked (shown as ⚑ on the overlay) until you choose
  **Auto-detect game**. While locked, only text from the program that first filled the
  text box counts.

## Overlay

- Hover over it for the buttons: `❚❚` pause / resume · `↶` undo last line · `≡` stats · `⚙` settings · `✕` quit
- Right-click: text box, choose game, fix VNDB match, rename, settings
- Compact mode (Settings) shows just the count and the goal bar.

## Themes

Settings → **look**:
- 7 presets: Sakura, Matcha, Latte, Sky, Lavender, Midnight, Mono.
- Your own colors (accent, background, surface, text, soft text, plus the finished / on hold / dropped colors).
- A choice of fonts, a separate font for big numbers, and text size (Small to Extra large).
- Corner style (Round / Soft / Sharp).
- Number format: `12,345`, `12.345`, `12 345` or `1.2万`.
- Cute extras (kaomoji and a symbol of your choice: ✿ ❀ ✦ ★ ♡ ♪) on or off.

Settings → **overlay**: which number is big (today / session / total), its label (字 / chars / none), size, and
toggles for the cover, game title, time · speed line, session figure, goal bar, compact mode, plus opacity.

Settings → **stats**: the page the log opens on, library card size (Small / Medium / Large) and how many days the
Days chart shows (14 / 30 / 60 / 90). The library sort is remembered.

**Reset look to defaults** (bottom of the look section) and **Reset all settings** (small button at the very
bottom) both ask first and keep your reading data, library, sessions, VNDB link, text boxes and ignored programs.

Changes apply live, with no restart.

## Sessions

Each sitting is logged as a session. It ends when:
- the VN closes,
- you click ✕,
- you switch to another game, or
- you've been idle for 30 minutes (adjustable in Settings).

Stats → **Sessions** lists them by day with time span, characters, reading time, speed, and how each one ended.
Sessions are saved as you read, so a crash still keeps them; those show as "tracker stopped".

## Stats & Library

- **Library**: one card per VN with cover, characters, time and speed. Click a card to set its
  status (Reading / Finished / On hold / Dropped), fix the match, or open it on VNDB.
  Manually added games and auto-detected exes of the same VN merge into one card.
- **Days**: calendar heatmap of the last 26 weeks, the day chart and a per-day table (see below).
- **Sessions**: your reading sessions (see above).
- **Recent lines**: everything counted. Select lines and delete them if something wrong got in.
- **Export CSV** for spreadsheets.

## Weekly goal
Settings → reading: **Weekly goal** (characters, 0 = off) and which day the week starts on. Stats shows a
**This week** tile with a progress bar, and **Overlay goal bar** can show the daily bar, the weekly bar or both
(two thin bars). Weeks follow the "new day starts at" hour. You get a short message when you reach a goal.

## Calendar heatmap
Stats → Days: one square per day for the last 26 weeks, darker = more characters (scaled to your daily goal, or to
your best days if there is none). A green outline means the daily goal was met. Hover for the numbers, click a day to
see its lines on the Lines page.

## Add reading by hand
For reading done elsewhere (phone, manga, a VN the OCR can't read): right-click the overlay → **Add reading…**,
the **Add reading** button in Stats, or a Library card's menu. Pick the VN (or a new title), characters, optional
minutes, date and note. It counts in totals, days, weeks, the heatmap and the Library, and is marked **manual**
(blue in the Lines page, "added by hand" in Sessions). Delete it from the Lines page like any other line.

## Progress per VN
Library cards show a slim bar with % read. The total length comes from jiten.moe (looked up in the background and
cached in the database). If jiten doesn't have the VN, a paler bar and "≈" show an estimate from VNDB's play time
(`chars_per_minute` in `data/config.json`, 450 by default). Card menu → **Set total characters…** lets you type
your own number, which always wins. Finished VNs show 100%.

## What counts

Kana, kanji, 々/〆/〇, ー, full-width letters/digits, half-width katakana.
Punctuation, spaces and ASCII don't count.

With OCR, the tracker counts only what's new:

| What happens on screen | Counted |
|---|---|
| New line | the whole line |
| Typewriter text read mid-way, NVL page gains a line | only the added part |
| Same line read again (OCR noise, hidden/reshown box, backlog) | nothing |
| meikipop's popup covering the box | nothing; it waits for the popup to close |
| Game closed or alt-tabbed and a browser, chat app or desktop shows behind the box | nothing |

Reading time is the gap between lines, capped at the AFK timeout (60 s by default).
The day rolls over at 04:00.

## Settings

Right-click → **Settings…**: AFK timeout, day start, daily goal, opacity, VNDB auto-match,
cover blurring, and the text source (**OCR**, **Clipboard** or **Both**; use Both only if
nothing double-counts). More options live in `data/config.json`:

- `ocr_settle` / `ocr_max_wait`: how long text must stay still before it's read
- `ocr_block_processes`: programs whose windows pause OCR when they cover the box (default `meikipop`)
- `ignored_processes` / `passthrough_processes`: programs that are never treated as the game

## Notes

- Light on resources. In a test with a new line every ~3 s it used about 9% of one CPU core,
  1.4% on a still screen, and almost nothing with no game open. The OCR model takes
  roughly 300 MB of RAM.
- The overlay stays on top of windowed and borderless games, not exclusive fullscreen.
  The overlay is blacked out of the capture, but keep it off the text box so it doesn't hide text.
- Explicit covers are blurred by default.

## Global hotkeys

Work even while a game has focus. Defaults (change them in Settings → hotkeys: click a box and press the keys;
a combo another program already uses is flagged there and in the overlay status):

| Keys | Action |
|---|---|
| Ctrl+Alt+P | pause / resume |
| Ctrl+Alt+Z | undo last line |
| Ctrl+Alt+H | hide / show the overlay (also in the right-click menu; hotkeys keep working while it's hidden) |
| Ctrl+Alt+T | select the text box |
| Ctrl+Alt+L | open the Library |

Starting the tracker again also brings a hidden overlay back.

## Backups

`reading.db` is copied to `data/backups/reading-YYYY-MM-DD.db` at startup and once a day, using SQLite's
backup API (safe while the tracker is running). The last 7 are kept (`backup_keep` in `data/config.json`).
Settings → backups has **Back up now** and **Open backups folder**. To restore, close the tracker and copy a
backup over `data/reading.db` (delete `reading.db-wal` / `reading.db-shm` next to it).

## Discord status

Shows the VN you're reading, today's characters and your speed on your Discord profile. It talks to the
Discord desktop app on your PC (no extra packages) and is off by default.

1. Create an application named "VN Tracker" at https://discord.com/developers/applications.
2. Copy its **Application ID**.
3. Paste it in Settings → Discord and switch it on.

The status clears when you pause, the session ends, the game closes, or you quit. The cover comes from VNDB
(explicit covers are never sent while cover blurring is on). Settings lets you pick the English or Japanese
title and hide the cover or the character count. If Discord isn't running it just waits and connects later.

## Lookups (difficulty)
Each time meikipop's popup opens over the text box counts as one dictionary lookup for the VN you are reading
(not while paused). Library cards show "N lookups · X / 1k 字"; Stats has an overall **Lookups** tile and, on the Days
page, lookups per 1,000 characters by week (all VNs, or pick one; also from a card's menu). Switch it off in
Settings → lookups (`lookups_enabled`).

## Send status to VNDB
Settings → VNDB status sync: paste an API token from https://vndb.org/u/tokens (with the "list write" permission),
press **Test token**. After that, changing a Library VN's status (Reading / Finished / On hold / Dropped) also sets
the label on your VNDB list (Playing / Finished / Stalled / Dropped), with the start date (first tracked line) and,
for Finished, today's date. Other labels (wishlist excepted), votes and notes are left alone. Only VNs with a VNDB id
are sent; the token is stored in `data/config.json` and shown masked. Turn it off with the switch
(`vndb_push_enabled`). Pulling your list from VNDB still only imports new VNs.

## Read next
Stats → **Read next**: your VNDB wishlist (needs the linked account) plus Library VNs you haven't started, with cover,
length in characters and difficulty from jiten.moe (shown "≈" when estimated from VNDB's play time; "?" if jiten has
no difficulty). Sort by easiest, shortest or best rated. **Start reading** adds a wishlist VN to the Library as Reading
(and sets it to Playing on VNDB if the token is set); **Open on VNDB** opens its page. Results are cached; **Refresh**
re-reads the wishlist and fills in what is missing.

## Unique kanji
Every counted line is scanned for kanji. Stats shows an **Unique kanji** tile (and how many are new today) and a
**Kanji** page: a grid of every kanji you met, sortable (newest, oldest, most seen, rarest), filterable per VN, with
kanji first seen in the last 7 days highlighted. Hover one for its count, first date and first VN. A Library card's menu
shows that VN's unique kanji count, **Details & speed chart...** and **Show its kanji**. Existing lines are counted
once on first start; deleting lines recounts. Manually added entries are not scanned.

## Speed over time
**Details & speed chart...** (Library card menu) opens a window with the VN's totals, its newest kanji and a chart of
your reading speed (characters / hour) per session or per day, with the average as a dashed line.

## Windows & notifications
Settings -> **windows & notifications**:
- **Start with Windows** puts a "VN Tracker" shortcut in your Startup folder (same program as the Desktop shortcut) and removes it when switched off.
- **Tray icon** with a menu: show / hide overlay, open Library, pause / resume, quit (left click shows / hides the
  overlay). **Close to tray** makes the overlay's x hide it there instead of quitting.
- **Session summary**: a small toast near the overlay when a session ends (VN, characters, time, speed, new kanji).
- **Milestone popups** for 100k, 250k, 500k, 1M, 2M, 5M, 10M... characters in total, 100k / 250k / 500k / 1M in one VN,
  and your first / 5th / 10th... finished VN. Each shows once; what you already reached when you update is not announced.
- **Ask to mark a VN finished at 100%** once a VN reaches its known total length (jiten.moe or your own number, never
  the estimate). It only asks; **Mark finished** changes the status.
- **Break reminder** (off by default): a gentle toast after N minutes of continuous reading (default 60). A 5 minute
  pause or the end of the session restarts the timer.

## Data

`data/reading.db` (SQLite), `data/covers/`, `data/config.json`, next to `tracker.py`.
