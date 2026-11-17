"""Start with Windows: a shortcut "VN Tracker.lnk" in the user's Startup folder (shell:startup).

Same target as the Desktop shortcut: the Python that runs the tracker (pythonw.exe next to sys.executable,
meikipop's venv), argument tracker.py, working folder = this folder, icon = icon.ico.
No registry Run key is used. No GUI, no `import tracker`.

Safety for tests: the Startup folder can be overridden with the env var VN_TRACKER_STARTUP_DIR or the
`folder=` argument. If VN_TRACKER_DATA is set (a scratch data dir) and neither override is given, a
"startup" subfolder of that data dir is used, so a test can never touch the real Startup folder.
"""
import base64
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LNK_NAME = "VN Tracker.lnk"
KNOWN_PYTHONW = os.path.join(os.path.expanduser("~"), r"meikipop\meikipop\.venv\Scripts\pythonw.exe")


def startup_dir(folder=None):
    if folder:
        return folder
    env = os.environ.get("VN_TRACKER_STARTUP_DIR")
    if env:
        return env
    data = os.environ.get("VN_TRACKER_DATA")
    if data:
        return os.path.join(data, "startup")
    appdata = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    return os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")


def shortcut_path(folder=None):
    return os.path.join(startup_dir(folder), LNK_NAME)


def target_python():
    """pythonw.exe of the interpreter running the tracker (falls back to meikipop's venv, then python itself)."""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return KNOWN_PYTHONW if os.path.exists(KNOWN_PYTHONW) else sys.executable


def is_enabled(folder=None):
    return os.path.exists(shortcut_path(folder))


def _ps(script):
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True, timeout=30, creationflags=flags)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout or "powershell failed").strip()[:300])


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


def enable(folder=None):
    """Creates the shortcut (folder is created if missing). Returns its path. Raises OSError on failure."""
    d = startup_dir(folder)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, LNK_NAME)
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + _q(path) + ");"
        "$s.TargetPath=" + _q(target_python()) + ";"
        "$s.Arguments=" + _q('"' + os.path.join(APP_DIR, "tracker.py") + '"') + ";"
        "$s.WorkingDirectory=" + _q(APP_DIR) + ";"
        "$s.IconLocation=" + _q(os.path.join(APP_DIR, "icon.ico") + ",0") + ";"
        "$s.Description='Tracks Japanese characters read in visual novels';"
        "$s.WindowStyle=1;$s.Save()"
    )
    _ps(script)
    if not os.path.exists(path):
        raise OSError("shortcut was not created")
    return path


def disable(folder=None):
    """Removes our shortcut (only that one file). Returns True if something was removed."""
    path = shortcut_path(folder)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def set_enabled(on, folder=None):
    return enable(folder) if on else disable(folder)


def read_shortcut(folder=None):
    """{target, args, workdir, icon} of the shortcut, or None (used by tests)."""
    path = shortcut_path(folder)
    if not os.path.exists(path):
        return None
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + _q(path) + ");"
              "[Console]::Out.Write($s.TargetPath+'|'+$s.Arguments+'|'+$s.WorkingDirectory+'|'+$s.IconLocation)")
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    parts = r.stdout.split("|")
    return dict(zip(("target", "args", "workdir", "icon"), parts)) if len(parts) == 4 else None
