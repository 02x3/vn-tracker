"""Global hotkeys: a thread owns the RegisterHotKey registrations and a GetMessage loop.
Events go to a queue that the UI thread drains (App.poll), so no Tk call ever happens on this thread.

    mgr = HotkeyManager()
    mgr.configure({"pause": "ctrl+alt+p", ...})   # (re)registers; {} unregisters everything
    mgr.events.get_nowait() -> ("pause",)          # an action name when its combo is pressed
    mgr.failed -> {"pause": "already used by another program"}
"""
import ctypes
import ctypes.wintypes as wt
import queue
import sys
import threading

DEFAULTS = {
    "pause": "ctrl+alt+p",
    "undo": "ctrl+alt+z",
    "hide": "ctrl+alt+h",
    "region": "ctrl+alt+t",
    "library": "ctrl+alt+l",
}
LABELS = {
    "pause": "Pause / resume",
    "undo": "Undo last line",
    "hide": "Hide / show overlay",
    "region": "Select text box",
    "library": "Open Library",
}
ACTIONS = list(DEFAULTS)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
         "win": MOD_WIN, "windows": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN}

_NAMED = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "minus": 0xBD, "-": 0xBD, "equals": 0xBB, "=": 0xBB, "comma": 0xBC, ",": 0xBC,
    "period": 0xBE, ".": 0xBE, "slash": 0xBF, "/": 0xBF, "semicolon": 0xBA, ";": 0xBA,
    "backslash": 0xDC, "\\": 0xDC, "quote": 0xDE, "'": 0xDE, "bracketleft": 0xDB, "[": 0xDB,
    "bracketright": 0xDD, "]": 0xDD, "grave": 0xC0, "`": 0xC0,
}
_NAMES_BY_VK = {}
for _n, _v in _NAMED.items():
    if len(_n) > 1 and _n not in ("escape", "return"):
        _NAMES_BY_VK.setdefault(_v, _n)
_NAMES_BY_VK[0x1B] = "esc"
_NAMES_BY_VK[0x0D] = "enter"

# Tk <KeyPress> keysym -> our key name (only the ones that differ)
_TK_KEYSYMS = {"Return": "enter", "Escape": "esc", "BackSpace": "backspace", "Prior": "pageup",
               "Next": "pagedown", "Insert": "insert", "Delete": "delete", "Home": "home", "End": "end",
               "Left": "left", "Right": "right", "Up": "up", "Down": "down", "Tab": "tab", "space": "space",
               "minus": "minus", "equal": "equals", "comma": "comma", "period": "period", "slash": "slash",
               "semicolon": "semicolon", "backslash": "backslash", "apostrophe": "quote",
               "bracketleft": "bracketleft", "bracketright": "bracketright", "grave": "grave"}


def _key_to_vk(key):
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    if key in _NAMED:
        return _NAMED[key]
    if key[0] == "f" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x6F + int(key[1:])  # VK_F1 = 0x70
    raise ValueError(f"unknown key '{key}'")


def parse_hotkey(text):
    """'ctrl+alt+p' -> (modifiers, vk). Raises ValueError. A plain letter/digit needs at least one modifier."""
    parts = [p.strip().lower() for p in str(text or "").replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    key, mods = parts[-1], 0
    for p in parts[:-1]:
        if p not in _MODS:
            raise ValueError(f"unknown modifier '{p}'")
        mods |= _MODS[p]
    if key in _MODS:
        raise ValueError("a modifier alone is not a hotkey")
    vk = _key_to_vk(key)
    is_fkey = key[0] == "f" and key[1:].isdigit()
    if not mods and not is_fkey:
        raise ValueError("needs Ctrl, Alt, Shift or Win")
    return mods, vk


def format_hotkey(mods, vk):
    names = [n for m, n in ((MOD_CONTROL, "ctrl"), (MOD_ALT, "alt"), (MOD_SHIFT, "shift"), (MOD_WIN, "win")) if mods & m]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        key = chr(vk).lower()
    elif 0x70 <= vk <= 0x87:
        key = f"f{vk - 0x6F}"
    else:
        key = _NAMES_BY_VK.get(vk, f"vk{vk}")
    return "+".join(names + [key])


def normalize(text):
    """Canonical spelling of a hotkey string ('Alt+Ctrl+P' -> 'ctrl+alt+p'); raises ValueError."""
    return format_hotkey(*parse_hotkey(text))


def pretty(text):
    """'ctrl+alt+p' -> 'Ctrl+Alt+P' for display."""
    return "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in str(text).split("+"))


def from_tk_event(keysym, state):
    """Combo string for a Tk <KeyPress> (keysym, state), or None while only a modifier is held."""
    if keysym in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Super_L", "Super_R",
                  "Win_L", "Win_R", "Meta_L", "Meta_R", "Caps_Lock", "Num_Lock", "Scroll_Lock"):
        return None
    key = _TK_KEYSYMS.get(keysym) or keysym.lower()
    mods = 0
    if state & 0x4:
        mods |= MOD_CONTROL
    if state & 0x20000 or state & 0x8:  # Alt (Windows reports it as 0x20000)
        mods |= MOD_ALT
    if state & 0x1:
        mods |= MOD_SHIFT
    try:
        return format_hotkey(mods, _key_to_vk(key))
    except (ValueError, IndexError):
        return None


# ----------------------------------------------------------------------------- the thread

WM_HOTKEY, WM_APP, WM_QUIT = 0x0312, 0x8000, 0x0012

if sys.platform == "win32":
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    _u32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    _u32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    _u32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
    _u32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    _k32.GetCurrentThreadId.restype = wt.DWORD


class HotkeyManager:
    def __init__(self):
        self.events: queue.Queue = queue.Queue()
        self.failed: dict = {}       # action -> reason, for combos that couldn't be registered
        self.registered: dict = {}   # action -> combo string, currently active
        self.version = 0             # bumps after every (re)configure, so the UI can notice
        self._cmds: queue.Queue = queue.Queue()
        self._thread = None
        self._tid = None
        self._ready = threading.Event()
        self._done = threading.Event()

    # -- public (any thread)
    def configure(self, bindings, wait=False):
        """Registers exactly `bindings` ({action: 'ctrl+alt+p'}); everything else is unregistered."""
        if self._thread is None:
            if not bindings:
                return
            self._thread = threading.Thread(target=self._run, daemon=True, name="Hotkeys")
            self._thread.start()
            self._ready.wait(2)
        self._done.clear()
        self._cmds.put(dict(bindings))
        self._wake()
        if wait:
            self._done.wait(2)

    def stop(self):
        if self._thread is not None and self._tid:
            self._cmds.put(None)
            self._wake()
            self._thread.join(1.5)
        self._thread = None

    def inject(self, action):
        """Test helper: act as if the hotkey was pressed (goes through the same message loop)."""
        ids = getattr(self, "_ids", {})
        for hid, act in ids.items():
            if act == action:
                _u32.PostThreadMessageW(self._tid, WM_HOTKEY, hid, 0)
                return True
        return False

    # -- thread
    def _wake(self):
        if self._tid:
            _u32.PostThreadMessageW(self._tid, WM_APP, 0, 0)

    def _apply(self, bindings):
        for hid in list(getattr(self, "_ids", {})):
            _u32.UnregisterHotKey(None, hid)
        self._ids, registered, failed = {}, {}, {}
        seen = {}
        for n, (action, text) in enumerate(bindings.items(), start=1):
            try:
                mods, vk = parse_hotkey(text)
            except ValueError as e:
                failed[action] = str(e)
                continue
            if (mods, vk) in seen:
                failed[action] = f"same as {LABELS.get(seen[(mods, vk)], seen[(mods, vk)]).lower()}"
                continue
            seen[(mods, vk)] = action
            if _u32.RegisterHotKey(None, n, mods | MOD_NOREPEAT, vk):
                self._ids[n] = action
                registered[action] = text
            else:
                err = ctypes.get_last_error()
                failed[action] = "already used by another program" if err == 1409 else f"couldn't register (error {err})"
        self.registered, self.failed = registered, failed
        self.version += 1
        self._done.set()

    def _run(self):
        self._tid = _k32.GetCurrentThreadId()
        msg = wt.MSG()
        _u32.PeekMessageW(ctypes.byref(msg), None, WM_APP, WM_APP, 0)  # makes the thread's message queue exist
        self._ready.set()
        try:
            while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    action = getattr(self, "_ids", {}).get(int(msg.wParam))
                    if action:
                        self.events.put((action,))
                elif msg.message == WM_APP:
                    stop = False
                    while True:
                        try:
                            cmd = self._cmds.get_nowait()
                        except queue.Empty:
                            break
                        if cmd is None:
                            stop = True
                            break
                        self._apply(cmd)
                    if stop:
                        break
        finally:
            for hid in list(getattr(self, "_ids", {})):
                _u32.UnregisterHotKey(None, hid)
            self._ids = {}
            self.registered = {}
