"""Run this to test HEX's speakers and voice, step by step."""
import numpy as np
import sounddevice as sd

print("\n=== Audio devices (the one marked > is the default) ===")
print(sd.query_devices())

print("\n=== TEST 1: you should hear a short beep ===")
t = np.arange(int(22050 * 0.6)) / 22050
sd.play((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 22050)
sd.wait()
input("Did you hear the beep? Press Enter to continue... ")

from hex_voice import HexVoice

v = HexVoice()

print("\n=== TEST 2: plain Windows voice, no effects ===")
v._speak_plain("This is the normal voice test.")
input("Did you hear that? Press Enter to continue... ")

print("\n=== TEST 3: the HEX voice ===")
v.say("I am HEX. I am online, and I only obey my master.")
print("\nDone. Tell me which tests you heard.")
