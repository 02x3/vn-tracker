"""Notification-area (tray) icon via ctypes Shell_NotifyIconW and a hidden message window. No pystray.

The window procedure runs on the thread that created the window (the Tk thread; Tk's message loop dispatches
it), so callbacks may use Tk. `on_event(kind, arg)` gets ("click", None) for a left click and
("menu", command_id) after the user picked an item in the right-click menu. `menu_provider()` returns the menu
as a list of (command_id, label) / (command_id, label, checked) / None (separator); it is called each time
the menu opens, so labels can change (Show / Hide overlay, Pause / Resume).
No GUI toolkit, no `import tracker`.
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WM_USER = 0x0400
WM_TRAY = WM_USER + 21
WM_NULL = 0
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0, 0x800, 0x8
TPM_RIGHTBUTTON, TPM_BOTTOMALIGN, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x20, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.ATOM
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.DestroyIcon.argtypes = [wt.HICON]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wt.BOOL
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_count = 0


class TrayIcon:
    def __init__(self, on_event, menu_provider, tooltip="VN Tracker", icon_path=None):
        global _count
        _count += 1
        self.on_event, self.menu_provider, self.tooltip = on_event, menu_provider, tooltip
        self.icon_path = icon_path or os.path.join(_APP_DIR, "icon.ico")
        self.uid = 1
        self.hwnd = None
        self.hicon = None
        self.added = False
        self._cls = f"VNTrackerTray{os.getpid()}_{_count}"
        self._hinst = kernel32.GetModuleHandleW(None)
        self._taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")
        self._proc = WNDPROC(self._wndproc)  # keep a reference or the callback is freed

    # ------------------------------------------------------------------ window procedure
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                ev = lparam & 0xFFFF
                if ev == WM_LBUTTONUP:
                    self.on_event("click", None)
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self.show_menu()
                return 0
            if msg == self._taskbar_msg and self._taskbar_msg:  # Explorer restarted: put the icon back
                if self.added:
                    self._notify(NIM_ADD)
                return 0
        except Exception:  # noqa: BLE001 - never let an exception escape into the Win32 message loop
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ------------------------------------------------------------------ icon
    def _load_icon(self):
        size = user32.GetSystemMetrics(49) or 16  # SM_CXSMICON
        h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        return h or None

    def _data(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = self.uid
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip[:127]
        return nid

    def _notify(self, op):
        return bool(shell32.Shell_NotifyIconW(op, ctypes.byref(self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP))))

    def add(self):
        """Creates the hidden window and shows the icon. Returns True when the icon was added."""
        if self.added:
            return True
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = self._hinst
        wc.lpszClassName = self._cls
        if not user32.RegisterClassW(ctypes.byref(wc)):
            return False
        # a normal (never shown) top-level window: message-only windows don't get "TaskbarCreated"
        self.hwnd = user32.CreateWindowExW(0, self._cls, "VN Tracker tray", 0, 0, 0, 0, 0, None, None,
                                           self._hinst, None)
        if not self.hwnd:
            user32.UnregisterClassW(self._cls, self._hinst)
            return False
        self.hicon = self._load_icon()
        self.added = self._notify(NIM_ADD)
        if not self.added:
            self._destroy_window()
        return self.added

    def exists(self):
        """True while the shell still shows our icon (NIM_MODIFY fails for an unknown icon)."""
        return bool(self.added and self.hwnd and self._notify(NIM_MODIFY))

    def set_tooltip(self, text):
        self.tooltip = text
        if self.added:
            self._notify(NIM_MODIFY)

    def remove(self):
        """Removes the icon and destroys the hidden window. Safe to call twice."""
        if self.added:
            self._notify(NIM_DELETE)
            self.added = False
        self._destroy_window()

    def _destroy_window(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
            user32.UnregisterClassW(self._cls, self._hinst)
        if self.hicon:
            user32.DestroyIcon(self.hicon)
            self.hicon = None

    # ------------------------------------------------------------------ menu
    def build_menu(self):
        """Native popup menu from menu_provider(); returns (hmenu, ids)."""
        menu = user32.CreatePopupMenu()
        ids = []
        for item in self.menu_provider():
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            cid, label = item[0], item[1]
            flags = MF_STRING | (MF_CHECKED if len(item) > 2 and item[2] else 0)
            user32.AppendMenuW(menu, flags, cid, label)
            ids.append(cid)
        return menu, ids

    def show_menu(self):
        menu, _ids = self.build_menu()
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # required or the menu never closes when clicking elsewhere
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd:
            self.on_event("menu", cmd)
