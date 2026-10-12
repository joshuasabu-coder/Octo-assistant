"""HEX's reasoning, powered by Ollama (a free AI model running on this laptop).

Three speeds:
  1. Known commands and simple questions (quick.py)  -> instant, no AI model
  2. Chat and questions                              -> short plain-text answer
  3. Other tasks                                     -> the model writes a plan (slowest)

Every AI call has a hard time limit, so HEX can never sit silent for minutes.
"""
import json
import re

import requests

import quick
from actions import ACTIONS

# ---- Settings you may change ------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS = "http://localhost:11434/api/tags"
OLLAMA_MODEL = "llama3.2:1b"   # tuned for a 4-core Ryzen 5 7520U laptop (no usable GPU)
CPU_THREADS = 4                # = your real CPU cores. More threads makes it SLOWER
CONTEXT_TOKENS = 2048          # smaller memory window = faster and lighter on RAM
TIMEOUT_SECONDS = 35           # HEX gives up and says so after this long
KEEP_LOADED = "30m"            # keep the model in memory so replies start fast
PLAN_TOKENS = 250              # cap for task plans
CHAT_TOKENS = 60               # cap for chat answers (about two short sentences)
HISTORY_MESSAGES = 4
# -----------------------------------------------------------------------------

# Words that suggest the owner wants HEX to DO something on the laptop.
TASK_WORDS = re.compile(
    r"\b(open|launch|start|create|make|add|delete|remove|move|rename|copy|save|write|"
    r"note|lock|list|show|run|folder|file|website|app|search|play|close|download)\b", re.I)

PLAN_SYSTEM = """You are HEX, a voice assistant on the owner's laptop. Be brief. No markdown.
Reply ONLY with JSON: {"say": "", "advice": "", "plan": null}
- Tasks: plan = {"goal": "...", "steps": [{"action": "...", "args": {}, "explain": "one short sentence"}]}
- Allowed actions: open_app(name), open_website(url), list_folder(path), create_folder(path),
  write_note(path, text), move_file(src, dst), delete_file(path), lock_screen().
  Paths look like ~/Desktop/Test or ~/Documents/notes.txt.
- If it is only chat or a question, put a short answer in "say" and keep plan null.
- If the owner is mistaken, add a short correction in "advice" but still plan the task.
- If you cannot do it, say so in "say". Never claim success you did not achieve."""

CHAT_SYSTEM = ("You are HEX, a calm, confident voice assistant. Answer in at most two short "
               "sentences. No markdown, no lists. If asked to do something on the laptop that "
               "you cannot do, say so briefly.")

OFFLINE_MESSAGE = ("My thinking engine, Ollama, is not running. "
                   "Please open the Ollama app, then say that again.")
SLOW_MESSAGE = ("I am thinking too slowly on that one. Try a simpler command, like open an "
                "app, a website, or a folder.")
MISSING_MESSAGE = (f"My thinking model is not installed. Please run ollama pull "
                   f"{OLLAMA_MODEL} in the terminal. Basic commands still work.")


def check_engine():
    """Is Ollama running and is the model installed? Returns (ok, message)."""
    try:
        r = requests.get(OLLAMA_TAGS, timeout=2)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return False, OFFLINE_MESSAGE
    want = OLLAMA_MODEL if ":" in OLLAMA_MODEL else OLLAMA_MODEL + ":latest"
    if want in names:
        return True, f"{OLLAMA_MODEL} is installed and ready."
    return False, MISSING_MESSAGE


def _chat(messages, want_json, max_tokens):
    body = {"model": OLLAMA_MODEL, "messages": messages, "stream": False,
            "keep_alive": KEEP_LOADED,
            "options": {"temperature": 0.2, "num_predict": max_tokens,
                        "num_thread": CPU_THREADS, "num_ctx": CONTEXT_TOKENS}}
    if want_json:
        body["format"] = "json"
    r = requests.post(OLLAMA_URL, json=body, timeout=(3.05, TIMEOUT_SECONDS))
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def warm_up():
    """Load the model into memory in the background while HEX starts up."""
    try:
        _chat([{"role": "user", "content": "hi"}], want_json=False, max_tokens=1)
    except Exception:
        pass


def _clean_plan(plan):
    """Drop any step the model invented that HEX cannot actually do."""
    if not isinstance(plan, dict):
        return None
    steps = []
    for s in plan.get("steps") or []:
        if isinstance(s, dict) and s.get("action") in ACTIONS:
            s.setdefault("args", {})
            s.setdefault("explain", f"I will run {s['action']}.")
            steps.append(s)
    if not steps:
        return None
    return {"goal": plan.get("goal") or "your request", "steps": steps}


def _fail(mode, msg):
    return msg if mode == "explain" else {"say": msg, "advice": "", "plan": None, "route": "failed"}


def think(text, history, mode="command"):
    try:
        if mode == "explain":
            return _chat([
                {"role": "system", "content":
                 "You are HEX. Explain in very simple words. Short sentences. No markdown."},
                {"role": "user", "content": text}], want_json=False, max_tokens=150)

        # 1. instant: known commands and simple questions
        plan = quick.match(text)
        if plan:
            return {"say": "", "advice": "", "plan": plan, "route": "instant"}
        spoken = quick.answer(text)
        if spoken:
            return {"say": spoken, "advice": "", "plan": None, "route": "instant"}

        # 2. fast: plain chat or a question
        if not TASK_WORDS.search(text):
            reply = _chat([{"role": "system", "content": CHAT_SYSTEM},
                           {"role": "user", "content": text}],
                          want_json=False, max_tokens=CHAT_TOKENS)
            return {"say": reply, "advice": "", "plan": None, "route": "chat"}

        # 3. slower: the model writes a plan
        raw = _chat([{"role": "system", "content": PLAN_SYSTEM}] +
                    history[-HISTORY_MESSAGES:] + [{"role": "user", "content": text}],
                    want_json=True, max_tokens=PLAN_TOKENS)
    except requests.exceptions.ReadTimeout:
        return _fail(mode, SLOW_MESSAGE)
    except requests.exceptions.ConnectionError:
        return _fail(mode, OFFLINE_MESSAGE)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return _fail(mode, MISSING_MESSAGE)
        return _fail(mode, f"Something went wrong with my thinking engine. {e}")
    except Exception as e:
        return _fail(mode, f"Something went wrong with my thinking engine. {e}")

    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except json.JSONDecodeError:
        return {"say": "Sorry, I could not work that out. Please say it again.",
                "advice": "", "plan": None, "route": "plan"}
    return {"say": data.get("say") or "",
            "advice": data.get("advice") or "",
            "plan": _clean_plan(data.get("plan")),
            "route": "plan"}
