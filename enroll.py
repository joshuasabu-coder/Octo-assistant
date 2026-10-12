"""Teach HEX your voice. Run once, in a quiet room."""
import os
import numpy as np
import sounddevice as sd
from resemblyzer import VoiceEncoder, preprocess_wav

import config

SR = 16000
PROMPTS = [
    "HEX, this is my voice and I am your master.",
    "Good morning HEX, please open my documents folder.",
    "The quick brown fox jumps over the lazy dog.",
    "HEX, listen only to me and obey my commands.",
    "Today is a great day to build something amazing.",
]

def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    enc = VoiceEncoder()
    embeds = []
    for i, line in enumerate(PROMPTS, 1):
        input(f"\n[{i}/{len(PROMPTS)}] Press Enter, then read aloud:\n   \"{line}\"\n")
        audio = sd.rec(int(6 * SR), samplerate=SR, channels=1, dtype="float32")
        sd.wait()
        wav = preprocess_wav(audio.flatten(), source_sr=SR)
        embeds.append(enc.embed_utterance(wav))
    voiceprint = np.mean(embeds, axis=0)
    voiceprint /= np.linalg.norm(voiceprint)
    np.save(os.path.join(config.DATA_DIR, "owner_voiceprint.npy"), voiceprint)
    print("\nVoiceprint saved. HEX now knows his master.")

if __name__ == "__main__":
    main()
