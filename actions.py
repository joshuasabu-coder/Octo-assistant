"""Things HEX can actually do on the laptop. Add more here."""
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

import config


def _safe(path):
    p = Path(os.path.expanduser(path)).resolve()
    if not any(str(p).startswith(str(Path(r).resolve())) for r in config.ALLOWED_ROOTS):
        raise PermissionError(f"{p} is outside the folders I am allowed to touch.")
    return p


def open_app(name):
    if sys.platform.startswith("win"):
        os.startfile(name)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", name])
    else:
        subprocess.Popen([name])
    return f"Opened {name}."


def open_website(url):
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."


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


def lock_screen():
    if sys.platform.startswith("win"):
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif sys.platform == "darwin":
        subprocess.run(["pmset", "displaysleepnow"])
    return "Screen locked."


ACTIONS = {f.__name__: f for f in [open_app, open_website, list_folder, create_folder,
                                   write_note, move_file, delete_file, lock_screen]}

# HEX double-checks these even after you approved the plan.
DESTRUCTIVE = {"delete_file", "move_file"}
