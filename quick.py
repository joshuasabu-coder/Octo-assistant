"""Instant commands and answers.

Common requests are understood here, in a fraction of a second, without asking
the slow AI model. Anything not matched here goes to the AI model.
Add your own patterns inside match() or answer().
"""
import os
import re
from datetime import datetime
from urllib.parse import quote_plus

from actions import SETTINGS_PAGES

SITES = {
    "youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com",
    "github": "github.com", "wikipedia": "wikipedia.org", "maps": "maps.google.com",
    "google maps": "maps.google.com", "whatsapp web": "web.whatsapp.com",
    "chatgpt": "chatgpt.com", "chat gpt": "chatgpt.com", "claude": "claude.ai",
}
APPS = {
    "notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint",
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge",
    "microsoft edge": "msedge", "file explorer": "explorer", "explorer": "explorer",
    "command prompt": "cmd", "cmd": "cmd", "task manager": "taskmgr",
    "settings": "ms-settings:", "word": "winword", "excel": "excel",
    "powerpoint": "powerpnt",
}
FOLDERS = {"desktop": "~/Desktop", "documents": "~/Documents", "downloads": "~/Downloads"}

_FILLER = re.compile(
    r"\b(please|kindly|can you|could you|would you|will you|i want you to|i need you to|"
    r"i would like you to|for me|hex)\b[,]?", re.I)


def _normalize(text):
    t = text.strip()
    t = re.sub(r"^(hey|hi|ok|okay)?\s*(hex|hecks|hacks)[,.\s]+", "", t, flags=re.I)
    t = _FILLER.sub(" ", t)
    t = re.sub(r"[,!?]+", " ", t)
    t = re.sub(r"\.+(?=\s|$)", " ", t)      # drop sentence dots but keep example.com
    return re.sub(r"\s+", " ", t).strip()


def _plan(goal, action, args, explain):
    return {"goal": goal,
            "steps": [{"action": action, "args": args, "explain": explain}]}


def answer(text):
    """Return a short spoken answer for simple questions, or None."""
    t = _normalize(text).lower()
    now = datetime.now()
    if re.fullmatch(r"(?:what(?:'s| is) the time|what time is it|tell me the time|"
                    r"the time|time)(?: now| right now)?", t):
        return f"It is {now.strftime('%I:%M %p').lstrip('0')}."
    if re.fullmatch(r"(?:what(?:'s| is) (?:the )?(?:date|day)(?: today)?|what day is it|"
                    r"today's date|the date)(?: today)?", t):
        return f"Today is {now:%A}, {now:%B} {now.day}."
    if re.fullmatch(r"(?:what(?:'s| is) your name|who are you)", t):
        return "I am HEX, your personal assistant. I only obey your voice."
    if re.fullmatch(r"how are you(?: doing| today)?", t):
        return "All systems are running well. How can I help?"
    if re.fullmatch(r"(?:hello|hi|hey)(?: there)?|good (?:morning|afternoon|evening)", t):
        return "Hello. I am listening."
    if re.fullmatch(r"(?:thanks|thank you)(?: so much| very much)?", t):
        return "You are welcome."
    return None


def match(text):
    """Return a ready-made plan for a known command, or None."""
    t = _normalize(text)
    if not t:
        return None

    # lock the screen
    if re.fullmatch(r"lock (the |my )?(screen|laptop|computer|pc)", t, re.I):
        return _plan("lock the screen", "lock_screen", {},
                     "I will lock your screen now.")

    # list what is inside a folder
    m = re.fullmatch(r"(?:list|what is in|what's in|whats in) (?:the |my )?"
                     r"(desktop|documents|downloads)(?: folder)?", t, re.I)
    if m:
        key = m.group(1).lower()
        return _plan(f"list your {key} folder", "list_folder",
                     {"path": FOLDERS[key]},
                     f"I will look inside your {key} folder and read out what is there.")

    # open a standard folder in File Explorer
    m = re.fullmatch(r"(?:open|show) (?:the |my )?(desktop|documents|downloads)"
                     r"(?: folder)?", t, re.I)
    if m:
        key = m.group(1).lower()
        return _plan(f"open your {key} folder", "open_app",
                     {"name": os.path.expanduser(FOLDERS[key])},
                     f"I will open your {key} folder in File Explorer.")

    # create a folder
    m = re.fullmatch(r"(?:create|make|add) (?:a |an |new )*folder(?: (?:called|named))? "
                     r"(.+?)(?: (?:on|in|inside|under)(?: the| my)? "
                     r"(desktop|documents|downloads)(?: folder)?)?", t, re.I)
    if m:
        name = re.sub(r'[<>:"/\\|?*]', "", m.group(1)).strip()
        where = (m.group(2) or "desktop").lower()
        if name:
            return _plan(f"create a folder called {name} in your {where}", "create_folder",
                         {"path": f"{FOLDERS[where]}/{name}"},
                         f"I will create a new folder called {name} in your {where}.")

    # play something on YouTube
    m = re.fullmatch(r"play (.+?) on youtube", t, re.I)
    if m:
        q = m.group(1).strip()
        return _plan(f"search YouTube for {q}", "open_website",
                     {"url": "https://www.youtube.com/results?search_query=" + quote_plus(q)},
                     f"I will search YouTube for {q}.")

    # search the web
    m = re.fullmatch(r"(?:search|google|look up)(?: for| up)? (.+)", t, re.I)
    if m:
        q = m.group(1).strip()
        return _plan(f"search the web for {q}", "open_website",
                     {"url": "https://www.google.com/search?q=" + quote_plus(q)},
                     f"I will search the web for {q}.")

    # ---------------------------------------------------------- system control
    low = t.lower()
    one = lambda goal, action, args, say: _plan(goal, action, args, say)

    # volume
    m = re.fullmatch(r"(?:set |change |put )?(?:the )?volume (?:to |at )?(\d{1,3})(?: percent| %)?", low)
    if m:
        return one(f"set the volume to {m.group(1)} percent", "set_volume",
                   {"level": int(m.group(1))}, f"I will set the volume to {m.group(1)} percent.")
    m = re.fullmatch(r"(?:turn |make |put )?(?:the )?(?:volume |sound )?(up|down)(?: the volume| the sound)?|"
                     r"(?:turn |make )?(?:the )?(?:volume|sound) (up|down)|"
                     r"(increase|raise|lower|decrease|reduce) (?:the )?volume", low)
    if m:
        word = next(g for g in m.groups() if g)
        up = word in ("up", "increase", "raise")
        if "volume" in low or "sound" in low:
            return one("raise the volume" if up else "lower the volume", "volume_change",
                       {"direction": "up" if up else "down", "steps": 8},
                       "I will raise the volume." if up else "I will lower the volume.")
    if re.fullmatch(r"(?:mute|unmute)(?: the)?(?: sound| volume| laptop| audio)?|(?:turn|switch) (?:the )?sound off", low):
        return one("toggle mute", "mute_toggle", {}, "I will toggle the sound mute.")

    # brightness
    m = re.fullmatch(r"(?:set |change |put )?(?:the )?(?:screen )?brightness (?:to |at )?(\d{1,3})(?: percent| %)?", low)
    if m:
        return one(f"set brightness to {m.group(1)} percent", "set_brightness",
                   {"level": int(m.group(1))}, f"I will set the screen brightness to {m.group(1)} percent.")
    m = re.fullmatch(r"(?:turn |make )?(?:the )?(?:screen )?brightness (up|down)|"
                     r"(increase|raise|lower|decrease|reduce) (?:the )?(?:screen )?brightness", low)
    if m:
        word = next(g for g in m.groups() if g)
        up = word in ("up", "increase", "raise")
        return one("raise the brightness" if up else "lower the brightness", "change_brightness",
                   {"delta": 20 if up else -20},
                   "I will brighten the screen." if up else "I will dim the screen.")

    # media
    if re.fullmatch(r"(?:play|pause|resume|stop)(?: the)?(?: music| media| video| song| playback)?|play pause", low):
        return one("play or pause the media", "media_key", {"action": "play"},
                   "I will play or pause the media.")
    if re.fullmatch(r"(?:next|skip)(?: the)?(?: song| track)?|play (?:the )?next (?:song|track)", low):
        return one("go to the next track", "media_key", {"action": "next"}, "I will skip to the next track.")
    if re.fullmatch(r"(?:previous|go back)(?: the)?(?: song| track)?|play (?:the )?previous (?:song|track)", low):
        return one("go to the previous track", "media_key", {"action": "prev"}, "I will go back one track.")

    # screenshot and information
    if re.fullmatch(r"(?:take |capture )(?:a )?(?:screenshot|screen shot|picture of (?:the|my) screen)", low):
        return one("take a screenshot", "screenshot", {}, "I will take a screenshot of your screen.")
    if re.fullmatch(r"(?:system (?:status|info|information)|(?:what is|what's|how is|how's) "
                    r"(?:the )?(?:my )?(?:battery|cpu|memory|ram|system)(?: level| usage| status)?|"
                    r"(?:battery|cpu|memory|ram)(?: level| usage| status)?|how much battery(?: do i have| is left)?)", low):
        return one("check the system status", "system_info", {}, "I will check your laptop's status.")
    if re.fullmatch(r"(?:what apps are (?:open|running)|which apps are (?:open|running)|"
                    r"(?:show|list) (?:the |my )?(?:open|running) apps)", low):
        return one("list the open apps", "running_apps", {}, "I will look at which apps are open.")

    # power
    if re.fullmatch(r"(?:shut ?down|turn off|power off)(?: the| my)?(?: laptop| computer| pc| system)?", low):
        return one("shut down the laptop", "shutdown_pc", {}, "I will shut down your laptop.")
    if re.fullmatch(r"(?:restart|reboot)(?: the| my)?(?: laptop| computer| pc| system)?", low):
        return one("restart the laptop", "restart_pc", {}, "I will restart your laptop.")
    if re.fullmatch(r"(?:put (?:the |my )?(?:laptop|computer|pc) to sleep|go to sleep|sleep(?: mode)?|"
                    r"sleep (?:the )?(?:laptop|computer|pc))", low):
        return one("put the laptop to sleep", "sleep_pc", {}, "I will put your laptop to sleep.")
    if re.fullmatch(r"cancel (?:the )?(?:shut ?down|restart)|abort (?:the )?shut ?down", low):
        return one("cancel the shutdown", "cancel_shutdown", {}, "I will cancel the shutdown.")

    # terminal command: only runs when you say "run command ..." and confirm twice
    m = re.fullmatch(r"(?:run|execute)(?: the)? (?:command|terminal command|powershell command) (.+)", t, re.I)
    if m:
        cmd = m.group(1).strip()
        return one(f"run the command {cmd}", "run_command", {"command": cmd},
                   f"I will run this command: {cmd}.")

    # settings pages: "open wifi settings"
    m = re.fullmatch(r"(?:open|show|go to)(?: the)? (.+?) settings", low)
    if m and m.group(1) in SETTINGS_PAGES:
        return one(f"open {m.group(1)} settings", "open_app", {"name": m.group(1)},
                   f"I will open the {m.group(1)} settings.")

    # close an app
    m = re.fullmatch(r"(?:close|quit|exit|kill|shut)(?: down)?(?: the)? (.+?)(?: app| application| window)?", low)
    if m and m.group(1) not in ("laptop", "computer", "pc", "system", "screen", "door"):
        name = m.group(1).strip()
        return one(f"close {name}", "close_app", {"name": name}, f"I will close {name}.")

    # ----------------------------------------------------- open a website or an app
    m = re.fullmatch(r"(?:open|launch|start|run|go to)(?: the)? (.+)", t, re.I)
    if m:
        target = re.sub(r"\s+(website|site|app|application|page)$", "",
                        m.group(1).strip().lower())
        if target in SITES:
            return _plan(f"open {target}", "open_website", {"url": SITES[target]},
                         f"I will open {target} in your web browser.")
        if re.fullmatch(r"[\w\-]+(\.[\w\-]+)+", target):
            return _plan(f"open {target}", "open_website", {"url": target},
                         f"I will open {target} in your web browser.")
        # any other name: HEX looks for it in the Start menu (Spotify, WhatsApp, VS Code...)
        if target and not re.search(r"\b(folder|file|document|note|command)\b", target) \
                and len(target.split()) <= 4:
            return _plan(f"open {target}", "open_app", {"name": target},
                         f"I will open {target} on your laptop.")

    return None   # not a known command: let the AI model handle it
