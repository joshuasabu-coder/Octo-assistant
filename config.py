import os

OWNER_TITLE = "sir"            # how HEX addresses you; change to your name
DATA_DIR = os.path.join(os.path.expanduser("~"), ".hex")
WHISPER_MODEL = "base.en"      # "small.en" is more accurate, slower
SPEECH_RATE = 175
VOICE_MATCH_THRESHOLD = 0.75   # raise (0.80+) = stricter, lower = more forgiving

# Brain: set the environment variable ANTHROPIC_API_KEY before running.
CLAUDE_MODEL = "claude-sonnet-5-5"

# Folders HEX is allowed to touch. Anything outside is refused.
ALLOWED_ROOTS = [os.path.expanduser("~/Documents"),
                 os.path.expanduser("~/Desktop"),
                 os.path.expanduser("~/Downloads")]
