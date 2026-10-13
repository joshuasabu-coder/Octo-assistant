"""Octo's voice: a natural, calm male voice.

Preferred engine: Piper, a neural voice that runs on your laptop (no internet).
It sounds like a real person, not a robot. It needs a one-time voice download
(see the setup steps). If it is not set up, Octo falls back to Windows' built-in
voice so he is never silent.

Octo starts speaking after the FIRST sentence is ready while the rest is still
being prepared, so long answers begin sooner.
"""
import io
import re
import os
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import butter, sosfilt

import ui

try:
    import win32com.client
except Exception:                      # not on Windows / not installed
    win32com = None

# ---- Dials you can change ---------------------------------------------------
VOICE_DIR = Path(__file__).with_name("voices")
PIPER_VOICE = "en_GB-alan-medium"   # calm British man.  Others: en_US-ryan-medium,
                                    # en_GB-northern_english_male-medium, en_US-joe-medium
WARMTH = 0.0         # chest/body boost. 0 = none. Raise (0.1) for a deeper, fuller voice
BASS_CUT_HZ = 160    # removes low rumble so the voice is lighter. Raise to 200 for even less bass
                     # (set to None to leave the voice exactly as Piper makes it)
LOWPASS_HZ = None    # e.g. 9000 removes harsh hiss. None = leave it natural
SAPI_RATE = 0        # Windows fallback voice speed, -10..+10
# -----------------------------------------------------------------------------

# Windows fallback voices are tried in this order.
PREFERRED_SAPI = ("george", "ryan", "david", "mark", "james", "daniel", "alex", "fred")


def _finish(audio, sr, warmth=WARMTH, lowpass=LOWPASS_HZ):
    """Light polish only: no pitch tricks, no distortion, so it stays human."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size < 200:
        raise ValueError("the speech audio was empty")
    out = audio
    if BASS_CUT_HZ:
        out = sosfilt(butter(2, BASS_CUT_HZ, btype="high", fs=sr, output="sos"), out)
    if warmth:
        low = sosfilt(butter(2, 250, btype="low", fs=sr, output="sos"), out)
        out = out + warmth * low.astype(np.float32)
    if lowpass:
        out = sosfilt(butter(4, lowpass, btype="low", fs=sr, output="sos"), out)
    peak = float(np.max(np.abs(out)))
    if not np.isfinite(peak) or peak < 1e-4:
        raise ValueError("the processed audio was silent")
    return (0.9 * out / peak).astype(np.float32)


def _sentences(text):
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    merged = []
    for p in parts:                       # glue very short bits onto the next sentence
        if merged and len(merged[-1]) < 14:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged or [text]


class HexVoice:
    def __init__(self):
        self.piper = None
        self.sapi_file = None
        self.sapi_plain = None
        self._load_piper()
        self._load_sapi()
        if not self.piper and not self.sapi_plain:
            raise RuntimeError("No voice engine is available (Piper and Windows speech both failed).")
        if self.piper:
            ui.update(voice_engine=f"NEURAL {PIPER_VOICE.split('-')[1].upper()}")
        else:
            ui.update(voice_engine="WINDOWS SAPI")
            msg = ("Natural voice not set up yet, using the Windows voice. "
                   "See the setup steps to install the Piper voice.")
            print("[OCTO]", msg)
            ui.log(msg, "warn")
        try:
            print("[OCTO] audio output device:", sd.query_devices(kind="output")["name"])
        except Exception:
            pass

    # ------------------------------------------------------------ engines
    def _load_piper(self):
        model = VOICE_DIR / f"{PIPER_VOICE}.onnx"
        if not model.exists() or not Path(str(model) + ".json").exists():
            return
        try:
            from piper import PiperVoice
            self.piper = PiperVoice.load(str(model))
            print(f"[OCTO] natural voice loaded: {PIPER_VOICE}")
        except Exception as e:
            print(f"[OCTO] could not load the natural voice ({e}); using the Windows voice.")
            self.piper = None

    def _load_sapi(self):
        if win32com is None:
            return
        try:
            self.sapi_file = win32com.client.Dispatch("SAPI.SpVoice")   # writes to a file
            self.sapi_plain = win32com.client.Dispatch("SAPI.SpVoice")  # speaks directly
            voices = self.sapi_file.GetVoices()
            found = [(voices.Item(i).GetDescription(), voices.Item(i))
                     for i in range(voices.Count)]
            for hint in PREFERRED_SAPI:
                hit = next(((d, v) for d, v in found if hint in d.lower()), None)
                if hit:
                    self.sapi_file.Voice = hit[1]
                    self.sapi_plain.Voice = hit[1]
                    if not self.piper:
                        print("[OCTO] Windows voice:", hit[0])
                    break
            self.sapi_file.Rate = SAPI_RATE
            self.sapi_plain.Rate = 0
        except Exception as e:
            print(f"[OCTO] Windows speech engine problem: {e}")
            self.sapi_file = self.sapi_plain = None

    # ------------------------------------------------------------ speaking
    def _synth_piper(self, text):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            if hasattr(self.piper, "synthesize_wav"):
                self.piper.synthesize_wav(text, wf)       # current Piper
            else:
                self.piper.synthesize(text, wf)           # older Piper
        buf.seek(0)
        audio, sr = sf.read(buf, dtype="float32")
        return _finish(audio, sr), sr

    def _say_piper(self, text):
        with ThreadPoolExecutor(max_workers=1) as pool:
            futures = [pool.submit(self._synth_piper, s) for s in _sentences(text)]
            for fut in futures:                 # play each sentence as soon as it is ready
                audio, sr = fut.result()
                sd.play(audio, sr)
                sd.wait()

    def _say_sapi(self, text):
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(path, 3)                 # 3 = create file for writing
            self.sapi_file.AudioOutputStream = stream
            self.sapi_file.Speak(text)
            stream.Close()
            audio, sr = sf.read(path, dtype="float32")
            sd.play(_finish(audio, sr, warmth=0.0, lowpass=9000), sr)
            sd.wait()
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _speak_plain(self, text):
        try:
            if self.sapi_plain:
                self.sapi_plain.Speak(text)
        except Exception as e:
            print(f"[OCTO] even the plain voice failed: {e}")

    def say(self, text):
        print(f"Octo: {text}")
        ui.log(text, "hex")
        ui.state("speaking")
        try:
            try:
                if self.piper:
                    self._say_piper(text)
                elif self.sapi_file:
                    self._say_sapi(text)
                else:
                    raise RuntimeError("no engine")
            except Exception as e:               # never go silent
                print(f"[OCTO] voice problem ({e}); using the plain Windows voice.")
                ui.log(f"voice problem: {e}", "warn")
                self._speak_plain(text)
        finally:
            ui.state("awaiting")
