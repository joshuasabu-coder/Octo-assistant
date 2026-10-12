# HEX — your personal voice assistant

## Setup (about 10 minutes)
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. Get an API key from console.anthropic.com and set it:
   - Windows: `setx ANTHROPIC_API_KEY "your-key"` (then reopen the terminal)
   - Mac/Linux: `export ANTHROPIC_API_KEY="your-key"`
4. `python enroll.py` — read 5 sentences so HEX learns your voice.
5. `python main.py` — HEX greets you and starts listening.

## Start automatically when you log in
- Windows: press Win+R, type `shell:startup`, put a shortcut to `python C:\path\to\hex\main.py` there.
- Mac: System Settings > General > Login Items > add a script that runs main.py.

## How it behaves
- Only your voice is processed. Other voices are ignored silently.
- HEX proposes a plan, you say "yes" (he answers "YES") or "no" ("NO").
- He narrates every step while doing it.
- Say "I didn't understand" and he re-explains simply, then asks if you got it.
- If interrupted, he resumes unfinished work next time you start him.
- Say "goodbye HEX" to stop him.

## Tuning
- `config.py`: VOICE_MATCH_THRESHOLD (stricter/looser), OWNER_TITLE, allowed folders.
- Male voice: HEX picks a male system voice if one is installed. On Windows, add
  one in Settings > Time & Language > Speech > Add voices.

## Honest limits
- Voice recognition is convenience, not strong security: a recording of your voice
  could fool it. Keep your normal laptop password/lock too.
- HEX can only do what is in `actions.py`. Add functions there to teach him more.
- Deletions go to a recovery folder (`~/.hex/trash`), not permanent erase.
