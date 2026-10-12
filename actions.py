"""Things HEX can actually do on the laptop. Add more here.

Every action returns a short sentence that HEX reads out. Actions that can lose
work (shut down, restart, sleep, run a command, delete, move) are listed in
DESTRUCTIVE: HEX asks for a second, spoken YES even after you approved the plan.
"""
import ctypes
import difflib
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import config

IS_WIN = sys.platform.startswith("win")
NO_WINDOW = 0x08000000 if IS_WIN else 0          # keeps black console boxes from flashing


def _need_windows():
    if not IS_WIN:
        raise OSError("That only works on a Windows laptop.")


def _safe(path):
    p = Path(os.path.expanduser(path)).resolve()
    if not any(str(p).startswith(str(Path(r).resolve())) for r in config.ALLOWED_ROOTS):
        raise PermissionError(f"{p} is outside the folders I am allowed to touch.")
    return p


def _powershell(script, timeout=20):
    _need_windows()
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "PowerShell failed").strip()[:200])
    return r.stdout.strip()


# =============================================================== opening apps
# Say the name you use in daily life. Anything not listed here is searched for in
# your Start menu, so "open spotify" or "open whatsapp" work if the app is installed.
APP_ALIASES = {
    "notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint",
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge",
    "microsoft edge": "msedge", "firefox": "firefox", "file explorer": "explorer",
    "explorer": "explorer", "command prompt": "cmd", "cmd": "cmd",
    "powershell": "powershell", "terminal": "wt", "task manager": "taskmgr",
    "control panel": "control", "settings": "ms-settings:", "word": "winword",
    "excel": "excel", "powerpoint": "powerpnt", "snipping tool": "snippingtool",
    "camera": "microsoft.windows.camera:", "clock": "ms-clock:", "store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:", "photos": "ms-photos:", "mail": "outlookmail:",
}

SETTINGS_PAGES = {
    "wifi": "ms-settings:network-wifi", "wi-fi": "ms-settings:network-wifi",
    "network": "ms-settings:network", "bluetooth": "ms-settings:bluetooth",
    "display": "ms-settings:display", "sound": "ms-settings:sound",
    "battery": "ms-settings:batterysaver", "update": "ms-settings:windowsupdate",
    "windows update": "ms-settings:windowsupdate", "apps": "ms-settings:appsfeatures",
    "privacy": "ms-settings:privacy", "storage": "ms-settings:storagesense",
    "personalization": "ms-settings:personalization", "accounts": "ms-settings:yourinfo",
    "time": "ms-settings:dateandtime", "power": "ms-settings:powersleep",
}

_APP_INDEX = None


def _build_app_index():
    """name -> ('file', path) or ('appid', id) for everything in the Start menu."""
    index = {}
    if not IS_WIN:
        return index
    for root in (os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
                 os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")):
        for folder, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith(".lnk"):
                    index.setdefault(f[:-4].lower(), ("file", os.path.join(folder, f)))
    try:                                        # also Store apps (WhatsApp, Spotify, Photos...)
        out = _powershell("Get-StartApps | ForEach-Object { $_.Name + '|||' + $_.AppID }", 25)
        for line in out.splitlines():
            if "|||" in line:
                name, appid = line.split("|||", 1)
                index.setdefault(name.strip().lower(), ("appid", appid.strip()))
    except Exception:
        pass
    return index


def _find_app(name):
    global _APP_INDEX
    if _APP_INDEX is None:
        _APP_INDEX = _build_app_index()
    if name in _APP_INDEX:
        return name, _APP_INDEX[name]
    hits = [k for k in _APP_INDEX if name in k]
    if hits:
        best = min(hits, key=len)
        return best, _APP_INDEX[best]
    close = difflib.get_close_matches(name, list(_APP_INDEX), n=1, cutoff=0.6)
    if close:
        return close[0], _APP_INDEX[close[0]]
    return None, None


def open_app(name):
    n = name.lower().strip()
    if os.path.exists(name) or re.match(r"^[a-z\-]+:", n) or n.endswith(".exe"):
        if IS_WIN:
            os.startfile(name)
            return f"Opened {name}."
    if n in SETTINGS_PAGES:
        os.startfile(SETTINGS_PAGES[n])
        return f"Opened {n} settings."
    if n in APP_ALIASES:
        target = APP_ALIASES[n]
        if IS_WIN:
            try:
                os.startfile(target)
                return f"Opened {name}."
            except OSError:
                pass                              # fall through to the Start menu search
    if IS_WIN:
        found, how = _find_app(n)
        if found:
            kind, ref = how
            if kind == "file":
                os.startfile(ref)
            else:
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{ref}"],
                                 creationflags=NO_WINDOW)
            return f"Opened {found.title()}."
        raise FileNotFoundError(f"I could not find an app called {name} on this laptop.")
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", name])
    else:
        subprocess.Popen([name])
    return f"Opened {name}."


# Never closed by voice: Windows itself, and HEX / his brain.
PROTECTED = {"explorer", "svchost", "winlogon", "csrss", "lsass", "system", "dwm", "services",
             "python", "pythonw", "ollama", "ollama app", "msedgewebview2", "powershell"}


def close_app(name):
    """Politely ask an app to close (it can still ask you to save)."""
    import psutil
    want = re.sub(r"[^a-z0-9]", "", APP_ALIASES.get(name.lower().strip(), name).lower())
    want = want.replace("msedge", "edge")
    if len(want) < 3:
        raise ValueError("Tell me the full name of the app to close.")
    names = set()
    for p in psutil.process_iter(["name"]):
        stem = re.sub(r"[^a-z0-9]", "", (p.info["name"] or "").lower().rsplit(".", 1)[0])
        if stem and stem not in PROTECTED and len(stem) >= 3 and (want in stem or stem in want):
            names.add(p.info["name"])
    if not names:
        return f"{name} does not seem to be running."
    for exe in names:
        if IS_WIN:
            subprocess.run(["taskkill", "/IM", exe], capture_output=True, creationflags=NO_WINDOW)
    return f"Asked {name} to close."


def running_apps():
    out = _powershell("Get-Process | Where-Object {$_.MainWindowTitle} | "
                      "Select-Object -ExpandProperty ProcessName -Unique")
    apps = sorted({a.strip() for a in out.splitlines() if a.strip()})
    return ("You have " + str(len(apps)) + " apps open: " + ", ".join(apps[:12])) if apps else \
           "I do not see any open app windows."


# ================================================================ sound & media
_VK = {"mute": 0xAD, "down": 0xAE, "up": 0xAF, "next": 0xB0, "prev": 0xB1, "play": 0xB3}


def _key(name, times=1):
    _need_windows()
    for _ in range(times):
        ctypes.windll.user32.keybd_event(_VK[name], 0, 0, 0)
        ctypes.windll.user32.keybd_event(_VK[name], 0, 2, 0)
        time.sleep(0.01)


def volume_change(direction, steps=5):
    """Each step is about 2 percent."""
    steps = max(1, min(50, int(steps)))
    _key("up" if direction == "up" else "down", steps)
    return f"Volume {'raised' if direction == 'up' else 'lowered'}."


def set_volume(level):
    level = max(0, min(100, int(level)))
    _key("down", 50)
    _key("up", round(level / 2))
    return f"Volume set to about {level} percent."


def mute_toggle():
    _key("mute")
    return "Toggled mute."


def media_key(action):
    if action not in ("play", "next", "prev"):
        raise ValueError("Unknown media action.")
    _key(action)
    return {"play": "Toggled play and pause.", "next": "Next track.", "prev": "Previous track."}[action]


# ===================================================================== screen
def set_brightness(level):
    level = max(0, min(100, int(level)))
    _powershell("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1,{level})")
    return f"Brightness set to {level} percent."


def change_brightness(delta):
    cur = int(_powershell("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness)"
                          ".CurrentBrightness"))
    return set_brightness(cur + int(delta))


def screenshot():
    folder = Path.home() / "Pictures" / "HEX Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
    _powershell("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
                "$g=[System.Drawing.Graphics]::FromImage($bmp); "
                "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
                f"$bmp.Save('{path}')")
    return f"Screenshot saved in Pictures, HEX Screenshots, as {path.name}."


def lock_screen():
    if IS_WIN:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif sys.platform == "darwin":
        subprocess.run(["pmset", "displaysleepnow"])
    return "Screen locked."


# ============================================================ system & power
def system_info():
    import psutil
    parts = [f"CPU is at {psutil.cpu_percent(interval=0.5):.0f} percent",
             f"memory is {psutil.virtual_memory().percent:.0f} percent used"]
    b = psutil.sensors_battery()
    if b:
        parts.append(f"battery is at {b.percent:.0f} percent, "
                     + ("charging" if b.power_plugged else "on battery"))
    root = os.path.abspath(os.sep)
    parts.append(f"disk is {psutil.disk_usage(root).percent:.0f} percent full")
    return ", ".join(parts) + "."


def shutdown_pc():
    _need_windows()
    subprocess.run(["shutdown", "/s", "/t", "30"], creationflags=NO_WINDOW)
    return "Shutting down in 30 seconds. Say cancel shutdown to stop me."


def restart_pc():
    _need_windows()
    subprocess.run(["shutdown", "/r", "/t", "30"], creationflags=NO_WINDOW)
    return "Restarting in 30 seconds. Say cancel shutdown to stop me."


def cancel_shutdown():
    _need_windows()
    subprocess.run(["shutdown", "/a"], creationflags=NO_WINDOW)
    return "Cancelled. Your laptop will stay on."


def sleep_pc():
    _need_windows()
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Going to sleep."


def run_command(command):
    """Run one command in the terminal and read back the start of its output."""
    _need_windows()
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    out = (r.stdout or r.stderr or "").strip()
    out = re.sub(r"\s+", " ", out)[:300]
    return f"The command finished. {out}" if out else "The command finished with no output."


# ================================================================== files
def list_folder(path):
    p = _safe(path)
    items = sorted(os.listdir(p))[:15]
    return f"{p.name} contains {len(os.listdir(p))} items. First ones: " + ", ".join(items)


def create_folder(path):
    p = _safe(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Created folder {p.name}."


def write_note(path, text):
    p = _safe(path)
    p.write_text(text)
    return f"Saved note to {p.name}."


def move_file(src, dst):
    shutil.move(str(_safe(src)), str(_safe(dst)))
    return "Moved."


def delete_file(path):
    p = _safe(path)
    # Sent to a recovery folder instead of permanent erase.
    trash = Path(config.DATA_DIR) / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(trash / p.name))
    return f"Moved {p.name} to HEX's recovery folder. Nothing was permanently erased."


def open_website(url):
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."


ACTIONS = {f.__name__: f for f in [
    open_app, close_app, running_apps, open_website, list_folder, create_folder, write_note,
    move_file, delete_file, lock_screen, volume_change, set_volume, mute_toggle, media_key,
    set_brightness, change_brightness, screenshot, system_info, shutdown_pc, restart_pc,
    cancel_shutdown, sleep_pc, run_command]}

# HEX double-checks these even after you approved the plan.
DESTRUCTIVE = {"delete_file", "move_file", "shutdown_pc", "restart_pc", "sleep_pc", "run_command"}

# The AI model may never plan these by itself: only a command you say clearly runs them.
LLM_BLOCKED = {"run_command", "shutdown_pc", "restart_pc", "sleep_pc"}


def confirm_text(name, args):
    """What HEX says before a risky step."""
    return {
        "shutdown_pc": "I am about to shut down your laptop. Unsaved work may be lost.",
        "restart_pc": "I am about to restart your laptop. Unsaved work may be lost.",
        "sleep_pc": "I am about to put your laptop to sleep.",
        "run_command": f"I am about to run this command in the terminal: {args.get('command', '')}.",
        "delete_file": "This will move a file to my recovery folder.",
        "move_file": "This will move a file.",
    }.get(name, "This step changes your laptop.") + " Shall I proceed?"
