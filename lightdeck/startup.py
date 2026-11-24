"""Start LightDeck when Windows starts (per user, no admin needed).

Uses the same place most apps use: the registry key
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run, value "LightDeck".
The installer writes the same value, so the app and the installer always agree.
Task Manager's Startup tab can also switch it off; that is stored under StartupApproved,
which we respect when reading and clear when the user turns it back on here.
"""
import sys
from pathlib import Path

try:
    import winreg
except ImportError:          # not Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
NAME = "LightDeck"
FLAG = "--startup"            # tells the app it was started by Windows (opens minimized)


def command():
    """The command Windows runs at sign-in."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {FLAG}'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    app = Path(__file__).resolve().parent / "app.py"
    return f'"{pyw if pyw.exists() else exe}" "{app}" {FLAG}'


def _disabled_in_task_manager():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
            data, _ = winreg.QueryValueEx(k, NAME)
        return bool(data) and data[0] % 2 == 1     # 02 = on, 03 = switched off in Task Manager
    except OSError:
        return False


def is_enabled():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, NAME)
    except OSError:
        return False
    return not _disabled_in_task_manager()


def set_enabled(on):
    """Turn starting with Windows on or off. Returns the new state."""
    if winreg is None:
        return False
    if on:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command())
        try:   # undo a "Disabled" set in Task Manager, otherwise Windows would still skip it
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, NAME)
        except OSError:
            pass
    else:
        for key in (RUN_KEY, APPROVED_KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, NAME)
            except OSError:
                pass
    return is_enabled()


def refresh():
    """If startup is on, make sure it points at this copy of LightDeck (e.g. after a move or update).
    Only the installed .exe does this, so running from source never steals the user's startup entry."""
    if winreg is None or not getattr(sys, "frozen", False) or not is_enabled():
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            current, _ = winreg.QueryValueEx(k, NAME)
        if current != command():
            set_enabled(True)
    except OSError:
        pass


def started_by_windows():
    return FLAG in sys.argv[1:]
