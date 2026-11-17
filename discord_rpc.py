"""Discord Rich Presence over Discord's local IPC (named pipe \\\\.\\pipe\\discord-ipc-N). No third-party packages.

Frame: little-endian uint32 opcode, uint32 length, then a JSON payload.
Opcodes: 0 handshake, 1 frame, 2 close, 3 ping, 4 pong.

Everything runs on one background thread that reconnects quietly when Discord isn't running,
so the UI never blocks. The UI thread only calls `update()` / `configure()` / `status()`.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import struct
import sys
import threading
import time
import uuid

OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4
MIN_INTERVAL = 15.0    # seconds between presence updates (a game change or a clear goes out at once)
RETRY_SECONDS = 10.0   # how often to look for Discord again when it isn't running


def default_pipe_names():
    return [r"\\.\pipe\discord-ipc-%d" % i for i in range(10)]


def pack_frame(opcode, payload):
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return struct.pack("<II", opcode, len(data)) + data


def valid_client_id(text):
    t = str(text or "").strip()
    return t.isdigit() and 15 <= len(t) <= 22


# ----------------------------------------------------------------------------- activity (pure)

def _clip(s, n=128):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


def build_activity(cfg, name, vn, session_start, today_chars=0, today_seconds=0, fmt_int=None, fmt_speed=None):
    """Rich-presence activity dict for the VN being read."""
    fmt_int = fmt_int or (lambda n: f"{int(n):,}")
    fmt_speed = fmt_speed or (lambda c, s: f"{round(c / s * 3600):,}/h" if s and s >= 60 else "—")
    vn = vn or {}
    title, alt = vn.get("title"), vn.get("alttitle")
    japanese = cfg.get("discord_title_lang") == "japanese"
    details = (alt or title or name) if japanese else (title or name or alt)
    act = {"details": _clip(details or "Reading a visual novel")}
    if cfg.get("discord_show_chars", True):
        state = f"{fmt_int(today_chars)} 字 today"
        sp = fmt_speed(today_chars, today_seconds)
        if sp and sp != "—":
            state += f" · {sp}"
        act["state"] = _clip(state)
    else:
        act["state"] = "Reading"
    if session_start:
        act["timestamps"] = {"start": int(session_start)}
    url = vn.get("cover_url")
    hide = bool(cfg.get("blur_nsfw_covers")) and (vn.get("cover_sexual") or 0) >= float(cfg.get("nsfw_threshold", 1.5))
    if cfg.get("discord_show_cover", True) and url and str(url).startswith("https://") and not hide:
        assets = {"large_image": url}
        text = alt or title
        if text:
            assets["large_text"] = _clip(text)
        act["assets"] = assets
    return act


# ----------------------------------------------------------------------------- pipe client

if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.PeekNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                                   ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    _k32.PeekNamedPipe.restype = wt.BOOL


class _Pipe:
    """A connected named pipe with timed reads."""

    def __init__(self, path):
        self.f = open(path, "r+b", buffering=0)
        import msvcrt
        self.handle = msvcrt.get_osfhandle(self.f.fileno())

    def available(self):
        n = wt.DWORD(0)
        if not _k32.PeekNamedPipe(self.handle, None, 0, None, ctypes.byref(n), None):
            raise BrokenPipeError("pipe closed")
        return n.value

    def read_exact(self, size, timeout):
        end, buf = time.monotonic() + timeout, b""
        while len(buf) < size:
            avail = self.available()
            if avail:
                chunk = self.f.read(min(avail, size - len(buf)))
                if not chunk:
                    raise BrokenPipeError("pipe closed")
                buf += chunk
            elif time.monotonic() > end:
                raise TimeoutError("no data")
            else:
                time.sleep(0.02)
        return buf

    def read_frame(self, timeout=5.0):
        op, length = struct.unpack("<II", self.read_exact(8, timeout))
        data = self.read_exact(length, timeout) if length else b""
        try:
            return op, json.loads(data.decode("utf-8")) if data else {}
        except ValueError:
            return op, {}

    def write_frame(self, op, payload):
        self.f.write(pack_frame(op, payload))

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass


class DiscordRPC:
    def __init__(self, pipe_names=None, min_interval=MIN_INTERVAL, retry=RETRY_SECONDS):
        self.pipe_names = list(pipe_names) if pipe_names is not None else default_pipe_names()
        self.min_interval = min_interval
        self.retry = retry
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self._enabled = False
        self._client_id = ""
        self._want = None          # activity dict, or None to clear
        self._want_key = None      # game key the wanted activity belongs to
        self._force = False        # send the wanted state now, ignoring the interval
        self._sent = "unset"       # the activity last sent (None = cleared)
        self._sent_key = None
        self._sent_at = 0.0
        self._stop = False
        self._state = "disabled"   # connected | Discord not running | needs an Application ID | disabled
        self.frames_sent = 0

    # -- UI thread API
    def configure(self, enabled, client_id):
        with self._lock:
            changed = str(client_id or "").strip() != self._client_id  # a new Application ID needs a new connection
            self._enabled, self._client_id = bool(enabled), str(client_id or "").strip()
            if not self._enabled:
                self._state = "disabled"
            elif not valid_client_id(self._client_id):
                self._state = "needs an Application ID"
            elif self._state in ("disabled", "needs an Application ID"):
                self._state = "connecting…"
        if changed:
            self._reconnect = True
            self._sent, self._sent_key = "unset", None
        if self._enabled and self._thread is None and not self._stop:
            self._thread = threading.Thread(target=self._run, daemon=True, name="DiscordRPC")
            self._thread.start()
        self._wake.set()

    def update(self, activity, game_key=None):
        """The activity that should be showing (None = nothing). Sent at most every `min_interval` seconds,
        except when the game changes or the activity is cleared."""
        with self._lock:
            if activity == self._want and game_key == self._want_key and not self._force:
                return
            self._force = self._force or activity is None or game_key != self._want_key
            self._want, self._want_key = activity, game_key
        self._wake.set()

    def status(self):
        return self._state

    def shutdown(self, timeout=1.5):
        """Clears the presence and closes the connection (call on quit)."""
        with self._lock:
            self._want, self._want_key, self._force = None, None, True
            self._stop = True
        self._wake.set()
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -- thread
    _reconnect = False

    def _connect(self, client_id):
        for path in self.pipe_names:
            try:
                pipe = _Pipe(path)
            except OSError:
                continue
            try:
                pipe.write_frame(OP_HANDSHAKE, {"v": 1, "client_id": client_id})
                op, data = pipe.read_frame(5.0)
                if op == OP_FRAME and data.get("evt") != "ERROR":
                    return pipe
                pipe.close()
            except (OSError, TimeoutError):
                pipe.close()
        return None

    def _send_activity(self, pipe, activity):
        args = {"pid": os.getpid()}
        if activity is not None:
            args["activity"] = activity
        pipe.write_frame(OP_FRAME, {"cmd": "SET_ACTIVITY", "args": args, "nonce": str(uuid.uuid4())})
        self.frames_sent += 1
        # Discord answers every command; read it so errors/close surface and the pipe doesn't fill up
        try:
            op, data = pipe.read_frame(3.0)
        except TimeoutError:
            return
        if op == OP_CLOSE:
            raise BrokenPipeError("closed by Discord")
        if op == OP_PING:
            pipe.write_frame(OP_PONG, data)

    def _service(self, pipe):
        """Answers pings and notices the pipe closing while idle."""
        while pipe.available() >= 8:
            op, data = pipe.read_frame(2.0)
            if op == OP_PING:
                pipe.write_frame(OP_PONG, data)
            elif op == OP_CLOSE:
                raise BrokenPipeError("closed by Discord")
        pipe.available()  # raises when the pipe is gone

    def _run(self):
        pipe = None
        next_try = 0.0
        while True:
            self._wake.wait(1.0)
            self._wake.clear()
            with self._lock:
                enabled, cid, stop = self._enabled, self._client_id, self._stop
                want, key, force = self._want, self._want_key, self._force
            if getattr(self, "_reconnect", False):
                self._reconnect = False
                if pipe:
                    pipe.close()
                    pipe = None
                next_try = 0.0
            try:
                if stop:
                    if pipe is not None and isinstance(self._sent, dict):
                        self._send_activity(pipe, None)
                    break
                if not enabled or not valid_client_id(cid):
                    if pipe and isinstance(self._sent, dict):
                        self._send_activity(pipe, None)  # switched off: take the presence down
                        self._sent = None
                    if pipe:
                        pipe.close()
                        pipe = None
                    continue
                if pipe is None:
                    if time.monotonic() < next_try:
                        continue
                    pipe = self._connect(cid)
                    if pipe is None:
                        self._state = "Discord not running"
                        next_try = time.monotonic() + self.retry
                        continue
                    self._state = "connected"
                    self._sent, self._sent_key = "unset", None
                self._service(pipe)
                now = time.monotonic()
                if want != self._sent or key != self._sent_key:
                    # a clear when something is shown, or a new game, goes out at once
                    due = force or self._sent == "unset" and want is None or now - self._sent_at >= self.min_interval
                    if self._sent == "unset" and want is None:
                        self._sent, self._sent_key = None, key  # nothing shown and nothing wanted
                        continue
                    if due:
                        self._send_activity(pipe, want)
                        self._sent, self._sent_key, self._sent_at = want, key, now
                        with self._lock:
                            if self._want is want:
                                self._force = False
            except (OSError, TimeoutError, ValueError):
                if pipe:
                    pipe.close()
                pipe = None
                self._state = "Discord not running"
                self._sent, self._sent_key = "unset", None
                next_try = time.monotonic() + self.retry
        if pipe:
            pipe.close()
        self._state = "disabled"
