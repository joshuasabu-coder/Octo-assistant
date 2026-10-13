"""
Octo - a personal, voice-only assistant that obeys only its owner's voice.

Run:
    python enroll.py     # once: teaches Octo your voice
    python main.py       # starts Octo
"""
import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import json
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from resemblyzer import VoiceEncoder, preprocess_wav

import config
import ui
from actions import ACTIONS, DESTRUCTIVE, confirm_text, describe
from brain import OLLAMA_MODEL, check_engine, think, warm_up
from hex_voice import HexVoice

# ---- Settings you may change ------------------------------------------------
SHOW_UI = True                  # open the live interface window
IDLE_FIRST_SECONDS = 45         # silence before Octo asks "are you there?"
IDLE_REPEAT_SECONDS = 120       # gap between further reminders (3 in total, then quiet)
UNAUTHORISED_COOLDOWN = 8       # don't repeat "unauthorised" more often than this
THINK_FEEDBACK_AFTER = 4        # say "One moment." if thinking takes longer than this
THREADS = 4                     # your real CPU cores
# -----------------------------------------------------------------------------

SAMPLE_RATE = 16000
STATE_FILE = Path(config.DATA_DIR) / "state.json"
VOICEPRINT = Path(config.DATA_DIR) / "owner_voiceprint.npy"

# Hints that make speech recognition spell your usual commands correctly.
STT_PROMPT = ("Octo. Open YouTube. Open Chrome. Open Spotify. Open WhatsApp. Open Notepad. "
              "Close Chrome. Search for. Play on YouTube. Volume up. Volume down. "
              "Take a screenshot. What time is it.")

IDLE_LINES = [
    "Master, are you there?",
    "I am still here, Master. Awaiting your command.",
    "Master, I will stand by. Call me when you need me.",
]


# ----------------------------------------------------------- speech in / ID
class Ears:
    def __init__(self):
        # Use the already-downloaded model without contacting the internet (faster start).
        try:
            self.stt = WhisperModel(config.WHISPER_MODEL, compute_type="int8",
                                    cpu_threads=THREADS, local_files_only=True)
        except Exception:
            self.stt = WhisperModel(config.WHISPER_MODEL, compute_type="int8",
                                    cpu_threads=THREADS)
        self.encoder = VoiceEncoder()
        if not VOICEPRINT.exists():
            sys.exit("No owner voiceprint found. Run:  python enroll.py")
        self.owner = np.load(VOICEPRINT)
        # One microphone stream kept open: no missed first syllable between sentences.
        self.block = int(SAMPLE_RATE * 0.1)
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                     dtype="float32", blocksize=self.block)
        self.stream.start()

    def _flush(self):
        try:
            n = self.stream.read_available
            if n:
                self.stream.read(n)
        except Exception:
            pass

    def record(self, max_seconds=12, silence_seconds=0.8, threshold=0.012):
        """Wait for speech, record it, stop when the speaker pauses."""
        self._flush()
        frames, preroll = [], deque(maxlen=3)
        quiet, started = 0.0, False
        t0 = time.time()
        while time.time() - t0 < max_seconds:
            if ui.typed_pending():                # something was typed: stop listening
                break
            data, _ = self.stream.read(self.block)
            level = float(np.abs(data).mean())
            ui.level(level)
            if level > threshold:
                if not started:
                    started = True
                    ui.state("listening")
                    frames.extend(preroll)        # keep the very start of the word
                quiet = 0.0
            elif started:
                quiet += 0.1
            if started:
                frames.append(data.copy())
                if quiet >= silence_seconds:
                    break
            else:
                preroll.append(data.copy())
        ui.level(0)
        return np.concatenate(frames).flatten() if frames else None

    def owner_score(self, audio):
        """How much this voice matches the owner (0..1), or None if it was just noise."""
        wav = preprocess_wav(audio, source_sr=SAMPLE_RATE)
        if len(wav) < SAMPLE_RATE * 0.5:
            return None
        emb = self.encoder.embed_utterance(wav)
        return float(np.dot(emb, self.owner) /
                     (np.linalg.norm(emb) * np.linalg.norm(self.owner)))

    def listen(self):
        """Returns (status, text). status is one of:
        'silence' (nothing heard), 'noise' (a sound, not speech),
        'unauthorised' (a voice that is not the owner), 'ok' (the owner spoke)."""
        ui.state("awaiting")
        typed = ui.pop_typed()                    # typed in the HUD bar (answered by voice only)
        if typed:
            print(f"[OCTO] typed: {typed}")
            return "ok", typed
        audio = self.record()
        typed = ui.pop_typed()
        if typed:
            print(f"[OCTO] typed: {typed}")
            return "ok", typed
        if audio is None:
            return "silence", None

        ui.state("verifying")
        t0 = time.time()
        score = self.owner_score(audio)
        if score is None:
            return "noise", None
        thr = config.VOICE_MATCH_THRESHOLD
        ui.update(voice_score=round(score, 2), threshold=thr)
        if score < thr:
            print(f"[OCTO] voice match {score:.2f} (needs {thr:.2f}) - not the owner")
            ui.update(owner_status="unauthorised")
            ui.alert("unauthorised", f"VOICE MATCH {score:.2f}  /  NEEDS {thr:.2f}", 6)
            return "unauthorised", None
        ui.update(owner_status="authorised")

        t1 = time.time()
        ui.state("transcribing")
        segs, _ = self.stt.transcribe(audio, language="en", vad_filter=True,
                                      beam_size=2, without_timestamps=True,
                                      initial_prompt=STT_PROMPT,
                                      condition_on_previous_text=False)
        text = " ".join(s.text for s in segs).strip()
        print(f"[OCTO] voice match {score:.2f} | voice check {t1 - t0:.1f} s | "
              f"speech-to-text {time.time() - t1:.1f} s")
        return ("ok", text) if text else ("noise", None)


# --------------------------------------------------------------- state/resume
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"pending_task": None, "history": [], "last_seen": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_seen"] = datetime.now().isoformat(timespec="seconds")
    STATE_FILE.write_text(json.dumps(state, indent=2))


# -------------------------------------------------------------------- helpers
def normalize_yes_no(text):
    t = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if t.split()[:1] and t.split()[0] in ("yes", "yeah", "yep", "sure", "confirm", "proceed"):
        return "YES"
    if t.split()[:1] and t.split()[0] in ("no", "nope", "cancel", "stop", "negative"):
        return "NO"
    return None


def greeting():
    h = datetime.now().hour
    part = "morning" if h < 12 else "afternoon" if h < 18 else "evening"
    return f"Good {part}, {config.OWNER_TITLE}. Octo is online and listening only to you."


_last_unauth = 0.0


def warn_unauthorised(voice):
    """Tell a stranger (or a badly matched voice) that they are not allowed."""
    global _last_unauth
    if time.time() - _last_unauth < UNAUTHORISED_COOLDOWN:
        return
    ui.state("unauthorised")
    ui.log("Rejected a voice that is not the owner", "warn")
    voice.say("You are unauthorised.")
    _last_unauth = time.time()


class IdleWatch:
    """Asks 'Master, are you there?' when nothing has been heard for a while."""

    def __init__(self):
        self.touch()

    def touch(self):
        self.count = 0
        self.next_at = time.time() + IDLE_FIRST_SECONDS

    def line_if_due(self):
        if self.count < len(IDLE_LINES) and time.time() >= self.next_at:
            line = IDLE_LINES[self.count]
            self.count += 1
            self.next_at = time.time() + IDLE_REPEAT_SECONDS
            return line
        return None


def ask_yes_no(voice, ears, question):
    voice.say(question + " Yes or no?")
    tries = 0
    while tries < 3:
        status, heard = ears.listen()
        tries += 1
        if status == "unauthorised":
            warn_unauthorised(voice)
            continue
        if status == "ok":
            ans = normalize_yes_no(heard)
            if ans:
                ui.log(heard, "you")
                voice.say(ans)  # speaks exactly "YES" or "NO"
                return ans == "YES"
            voice.say("I did not catch that. Yes or no?")
        elif tries < 3:
            voice.say("Master, yes or no?")
    return False


_pool = ThreadPoolExecutor(max_workers=1)


def think_with_feedback(voice, heard, history):
    """Run the thinking in the background; say 'One moment.' if it takes a while."""
    ui.state("thinking")
    t0 = time.time()
    fut = _pool.submit(think, heard, history, "command")
    try:
        result = fut.result(timeout=THINK_FEEDBACK_AFTER)
    except FutureTimeout:
        voice.say("One moment.")
        ui.state("thinking")
        result = fut.result()          # the brain has its own hard time limit
    took = time.time() - t0
    route = result.get("route", "?")
    print(f"[OCTO] thinking took {took:.1f} s ({route})")
    ui.update(think_seconds=took, think_route=route)
    ui.log(f"Thought for {took:.1f}s via {route}")
    return result


# ----------------------------------------------------------------------- loop
def run_plan(voice, ears, state, plan):
    """Execute steps one by one, narrating each, saving progress for resume."""
    state["pending_task"] = plan
    save_state(state)
    steps = plan["steps"]
    while plan["done"] < len(steps):
        step = steps[plan["done"]]
        prefix = f"Step {plan['done'] + 1} of {len(steps)}. " if len(steps) > 1 else ""
        voice.say(prefix + step["explain"])
        name = step["action"]
        if name in DESTRUCTIVE and not step.get("confirmed"):
            if not ask_yes_no(voice, ears, confirm_text(name, step.get("args", {}))):
                voice.say("Understood. I will not do that step.")
                plan["done"] += 1
                save_state(state)
                continue
        url = str(step.get("args", {}).get("url", ""))
        searching = name == "open_website" and any(k in url for k in ("/search", "results?"))
        try:
            ui.log(f"Running {name}")
            ui.popup(*describe(name, step.get("args", {})))
            if searching:                        # the HUD shows the 3D web network
                qs = parse_qs(urlparse(url).query)
                query = (qs.get("q") or qs.get("search_query") or [""])[0]
                ui.update(searching=True, search_query=query)
            result = ACTIONS[name](**step.get("args", {}))
            if searching:
                time.sleep(3)                    # let the search animation play
                ui.update(searching=False, search_query="")
            voice.say(f"Done. {result}" if result else "Done.")
        except Exception as e:  # report honestly, never hide failures
            ui.update(searching=False, search_query="")
            ui.log(f"{name} failed: {e}", "warn")
            voice.say(f"That step failed. The error was: {e}. "
                      "Would you like me to try another way?")
        plan["done"] += 1
        save_state(state)
    voice.say("Task complete.")
    state["pending_task"] = None
    save_state(state)


def main():
    ui.start(open_window=SHOW_UI, owner_title="Master", model=OLLAMA_MODEL)
    ui.set_engine_probe(check_engine)
    ui.log("Loading speech models...")
    # Load the thinking model in the background while the rest of Octo starts up.
    threading.Thread(target=warm_up, daemon=True).start()

    voice, ears, state = HexVoice(), Ears(), load_state()
    ui.log("Octo is online")
    voice.say(greeting())

    ok, msg = check_engine()
    ui.update(engine={"ok": ok, "msg": msg})
    if not ok:
        ui.log(msg, "warn")
        voice.say(msg)

    if state.get("pending_task"):
        t = state["pending_task"]
        voice.say(f"Last time I was working on: {t['goal']}. "
                  f"I finished {t['done']} of {len(t['steps'])} steps.")
        if ask_yes_no(voice, ears, "Shall I continue from where I stopped?"):
            run_plan(voice, ears, state, t)
        else:
            state["pending_task"] = None
            save_state(state)

    idle = IdleWatch()
    last_explanation = ""
    while True:
        try:
            status, heard = ears.listen()

            if status == "unauthorised":
                warn_unauthorised(voice)
                continue
            if status != "ok":                      # silence or noise
                line = idle.line_if_due()
                if line:
                    ui.log(line, "hex")
                    voice.say(line)
                continue

            idle.touch()
            print(f"YOU: {heard}")
            ui.log(heard, "you")
            low = heard.lower()

            if re.search(r"\b(goodbye|bye|shut down|sleep)\s+(octo|otto|octa|okto)\b", low):
                voice.say(f"Goodbye, {config.OWNER_TITLE}. I will remember where we are.")
                save_state(state)
                break

            # "I didn't understand" -> re-explain simply and check
            if any(p in low for p in ("didn't get", "did not get", "don't understand",
                                      "didn't understand", "explain again", "say that again")):
                simple = think(
                    f"Explain this again in very simple words, short sentences: {last_explanation}",
                    state["history"], mode="explain")
                voice.say(simple)
                ask_yes_no(voice, ears, "Did you get the idea?")
                idle.touch()
                continue

            result = think_with_feedback(voice, heard, state["history"])
            state["history"] += [{"role": "user", "content": heard},
                                 {"role": "assistant", "content": json.dumps(result)}]
            state["history"] = state["history"][-20:]

            # Octo may correct a mistake or advise - but the order still stands.
            if result.get("advice"):
                voice.say(result["advice"])
                last_explanation = result["advice"]

            plan = result.get("plan")
            if not plan or not plan.get("steps"):
                if result.get("say"):
                    voice.say(result["say"])
                    last_explanation = result["say"]
                save_state(state)
                idle.touch()
                continue

            last_explanation = plan["goal"]
            if ask_yes_no(voice, ears, f"Plan: {plan['goal']}. Shall I go ahead?"):
                plan["done"] = 0
                run_plan(voice, ears, state, plan)
            else:
                voice.say("Understood. Standing by.")
            save_state(state)
            idle.touch()

        except Exception as e:             # one bad moment must never freeze Octo
            traceback.print_exc()
            ui.state("error")
            ui.log(f"Error: {e}", "warn")
            try:
                voice.say("Something went wrong inside me, Master. I am carrying on.")
            except Exception:
                pass
            time.sleep(1)


if __name__ == "__main__":
    main()
