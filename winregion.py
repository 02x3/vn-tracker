"""Text box that follows the game window.

A region is saved relative to the game window's client area (fractions 0..1), together with the game's exe,
so moving or resizing the window keeps the OCR box on the text. The absolute rectangle is kept as a fallback.

Stored form (games.region / cfg["ocr_region_spec"]):
    {"rel": [l, t, r, b] (fractions of the client rect), "exe": "c:\\...\\game.exe", "abs": [l, t, r, b]}
The old format, a plain [l, t, r, b] list of screen pixels, is still read (see `parse_spec`).
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

MIN_W, MIN_H = 30, 15  # a text box smaller than this (in pixels) is treated as nonsense

if sys.platform == "win32":
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    _u32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]
    _u32.IsWindowVisible.argtypes = [wt.HWND]
    _u32.IsIconic.argtypes = [wt.HWND]
    _u32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    _u32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    _u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _u32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    _k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    try:
        _dwm = ctypes.WinDLL("dwmapi")
        _dwm.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    except OSError:
        _dwm = None


# ----------------------------------------------------------------------------- pure math (unit-tested)

def abs_to_rel(region, rect):
    """Screen rectangle -> fractions of `rect` (the window's client rect, also in screen pixels)."""
    cl, ct, cr, cb = rect
    w, h = max(1, cr - cl), max(1, cb - ct)
    l, t, r, b = region
    return [round((l - cl) / w, 6), round((t - ct) / h, 6), round((r - cl) / w, 6), round((b - ct) / h, 6)]


def rel_to_abs(rel, rect):
    """Fractions of `rect` -> screen rectangle (ints)."""
    cl, ct, cr, cb = rect
    w, h = cr - cl, cb - ct
    return [int(round(cl + rel[0] * w)), int(round(ct + rel[1] * h)),
            int(round(cl + rel[2] * w)), int(round(ct + rel[3] * h))]


def valid_region(r) -> bool:
    try:
        return len(r) == 4 and r[2] - r[0] >= MIN_W and r[3] - r[1] >= MIN_H
    except TypeError:
        return False


def make_spec(region, exe, rect):
    """Spec for `region` (screen pixels) over a window with client rect `rect` (None = no window known)."""
    region = [int(v) for v in region]
    if exe and rect and rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
        return {"rel": abs_to_rel(region, rect), "exe": exe.lower(), "abs": region}
    return {"abs": region}


def parse_spec(value):
    """Stored JSON value (new dict or old plain list) -> spec dict, or None."""
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return {"abs": [int(v) for v in value]}
    if isinstance(value, dict):
        spec = {}
        if isinstance(value.get("abs"), (list, tuple)) and len(value["abs"]) == 4:
            spec["abs"] = [int(v) for v in value["abs"]]
        if isinstance(value.get("rel"), (list, tuple)) and len(value["rel"]) == 4 and value.get("exe"):
            spec["rel"] = [float(v) for v in value["rel"]]
            spec["exe"] = str(value["exe"])
        return spec if spec.get("abs") or spec.get("rel") else None
    return None


def resolve_spec(spec, find=None):
    """Absolute screen region for a spec. `find(exe)` returns the game's client rect or None.
    Falls back to the stored absolute rectangle when the window can't be found."""
    if not spec:
        return None
    if spec.get("rel") and spec.get("exe"):
        rect = (find or find_game_client)(spec["exe"])
        if rect:
            r = rel_to_abs(spec["rel"], rect)
            if valid_region(r):
                return r
    return list(spec["abs"]) if spec.get("abs") else None


# ----------------------------------------------------------------------------- windows

_exe_cache: dict = {}


def _pid_exe(pid):
    hit = _exe_cache.get(pid)
    if hit and time.monotonic() - hit[0] < 30:
        return hit[1]
    h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    exe = ""
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wt.DWORD(1024)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe = os.path.normcase(buf.value)
        finally:
            _k32.CloseHandle(h)
    if len(_exe_cache) > 400:
        _exe_cache.clear()
    _exe_cache[pid] = (time.monotonic(), exe)
    return exe


def _cloaked(hwnd) -> bool:
    if not _dwm:
        return False
    val = ctypes.c_int(0)
    _dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(val), ctypes.sizeof(val))
    return bool(val.value)


def client_rect(hwnd):
    """(l, t, r, b) of the window's client area in screen pixels, or None."""
    rc = wt.RECT()
    if not _u32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wt.POINT(0, 0)
    if not _u32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return (pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom)


def find_game_window(exe, ignore_pid=None):
    """(hwnd, client rect) of the largest visible, non-minimized window of `exe`, or None."""
    if not exe or sys.platform != "win32":
        return None
    want = os.path.normcase(exe)
    best = []

    def visit(hwnd, _):
        if not _u32.IsWindowVisible(hwnd) or _u32.IsIconic(hwnd) or _cloaked(hwnd):
            return True
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == ignore_pid or _pid_exe(pid.value) != want:
            return True
        if _u32.GetWindowLongW(hwnd, -20) & 0x80:  # tool window
            return True
        rect = client_rect(hwnd)
        if rect and rect[2] - rect[0] > 1 and rect[3] - rect[1] > 1:
            best.append(((rect[2] - rect[0]) * (rect[3] - rect[1]), hwnd, rect))
        return True

    _u32.EnumWindows(_WNDENUMPROC(visit), 0)
    if not best:
        return None
    _, hwnd, rect = max(best, key=lambda b: b[0])
    return hwnd, rect


def find_game_client(exe, ignore_pid=None):
    hit = find_game_window(exe, ignore_pid)
    return hit[1] if hit else None
