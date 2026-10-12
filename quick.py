"""Instant commands and answers.

Common requests are understood here, in a fraction of a second, without asking
the slow AI model. Anything not matched here goes to the AI model.
Add your own patterns inside match() or answer().
"""
import os
import re
from datetime import datetime
from urllib.parse import quote_plus

SITES = {
    "youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com",
    "github": "github.com", "wikipedia": "wikipedia.org", "maps": "maps.google.com",
    "google maps": "maps.google.com", "whatsapp": "web.whatsapp.com",
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

    # open a website or an app
    m = re.fullmatch(r"(?:open|launch|start|go to)(?: the)? (.+)", t, re.I)
    if m:
        target = re.sub(r"\s+(website|site|app|application|page)$", "",
                        m.group(1).strip().lower())
        if target in SITES:
            return _plan(f"open {target}", "open_website", {"url": SITES[target]},
                         f"I will open {target} in your web browser.")
        if re.fullmatch(r"[\w\-]+(\.[\w\-]+)+", target):
            return _plan(f"open {target}", "open_website", {"url": target},
                         f"I will open {target} in your web browser.")
        if target in APPS:
            return _plan(f"open {target}", "open_app", {"name": APPS[target]},
                         f"I will open {target} on your laptop.")

    return None   # not a known command: let the AI model handle it
