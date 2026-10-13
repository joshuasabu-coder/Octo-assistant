"""Octo's live interface.

Starts a tiny web server that only listens on THIS laptop (127.0.0.1) and shows
Octo's live status in a window. The page is read-only: it can display things,
but it cannot give Octo a command. The only way in besides your voice is the small
type bar, and that is protected by a secret token that only this page knows, so
other websites or programs cannot talk to Octo through it.
"""
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORTS = range(8765, 8776)
PAGE = Path(__file__).with_name("hex_ui.html")

LABELS = {
    "starting": "STARTING UP...",
    "awaiting": "AWAITING COMMAND...",
    "listening": "LISTENING...",
    "verifying": "VERIFYING VOICE...",
    "transcribing": "UNDERSTANDING...",
    "thinking": "THINKING...",
    "searching": "SEARCHING THE WEB...",
    "speaking": "SPEAKING...",
    "unauthorised": "UNAUTHORISED VOICE",
    "error": "ATTENTION NEEDED",
}

_lock = threading.Lock()
_state = {
    "mode": "starting", "label": LABELS["starting"], "level": 0.0,
    "voice_score": None, "threshold": None, "owner_status": "waiting",
    "think_seconds": None, "think_route": None, "model": "",
    "voice_engine": "", "engine": {"ok": None, "msg": "checking..."},
    "stats": {"cpu": 0, "mem_pct": 0, "mem_used_gb": 0, "mem_total_gb": 0, "disk_pct": 0},
    "alert": None, "popup": None,
    "log": [], "you": "", "hex": "", "owner_title": "MASTER", "started": time.time(),
}
_probe = None
_url = None
TOKEN = secrets.token_urlsafe(18)       # shown only to the page Octo itself serves
_typed = queue.Queue()                  # messages typed into the HUD's type bar


def alert(kind, text="", seconds=6):
    """Full-screen warning over the whole interface (e.g. an unauthorised voice)."""
    update(alert={"kind": kind, "text": text, "until": time.time() + seconds})


def popup(title, detail="", seconds=3.5):
    """A card that pops up over the sphere, e.g. 'OPENING / SETTINGS'."""
    update(popup={"title": str(title)[:40], "detail": str(detail)[:60], "id": int(time.time() * 1000),
                  "until": time.time() + seconds})


def pop_typed():
    try:
        return _typed.get_nowait()
    except queue.Empty:
        return None


def typed_pending():
    return not _typed.empty()


# ---------------------------------------------------------------- state API
def state(mode, label=None):
    with _lock:
        _state["mode"] = mode
        _state["label"] = label or LABELS.get(mode, mode.upper())


def update(**kw):
    with _lock:
        _state.update(kw)


def level(x):
    with _lock:
        _state["level"] = float(x)


def log(msg, kind="info"):
    with _lock:
        _state["log"].append({"t": datetime.now().strftime("%H:%M:%S"),
                              "kind": kind, "msg": str(msg)[:200]})
        del _state["log"][:-40]
        if kind == "you":
            _state["you"] = str(msg)[:200]
        elif kind == "hex":
            _state["hex"] = str(msg)[:300]


def set_engine_probe(fn):
    """fn() -> (ok: bool, message: str). Called every few seconds in the background."""
    global _probe
    _probe = fn


# ------------------------------------------------------------ background work
def _stats_loop():
    try:
        import psutil
    except Exception:
        psutil = None
    drive = os.path.abspath(os.sep)
    last_probe = 0
    while True:
        try:
            st = {}
            if psutil:
                vm = psutil.virtual_memory()
                st.update(cpu=round(psutil.cpu_percent(interval=None)),
                          mem_pct=round(vm.percent),
                          mem_used_gb=round((vm.total - vm.available) / 1e9, 1),
                          mem_total_gb=round(vm.total / 1e9, 1))
            du = shutil.disk_usage(drive)
            st["disk_pct"] = round(du.used / du.total * 100)
            with _lock:
                _state["stats"].update(st)
            if _probe and time.time() - last_probe > 8:
                last_probe = time.time()
                ok, msg = _probe()
                with _lock:
                    _state["engine"] = {"ok": bool(ok), "msg": msg}
        except Exception:
            pass
        time.sleep(1)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            try:
                page = PAGE.read_bytes().replace(b"__TOKEN__", TOKEN.encode())
                self._send(200, page, "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"hex_ui.html is missing", "text/plain")
        elif self.path.startswith("/api/state"):
            with _lock:
                snap = dict(_state)
                snap["log"] = list(_state["log"])
            snap["uptime"] = int(time.time() - snap.pop("started"))
            now = time.time()
            for key in ("alert", "popup"):                 # hide them once their time is up
                v = snap.get(key)
                snap[key] = None if (not v or v["until"] < now) else dict(v, ms_left=int((v["until"] - now) * 1000))
            self._send(200, json.dumps(snap).encode(), "application/json")
        elif self.path.startswith("/favicon"):
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, b"not found", "text/plain")


def _post_ok(self):
    """Only the Octo page itself, on this laptop, may post a message."""
    port = self.server.server_address[1]
    host_ok = self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")
    origin = self.headers.get("Origin")
    origin_ok = origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
    token_ok = secrets.compare_digest(self.headers.get("X-Octo-Token", ""), TOKEN)
    return host_ok and origin_ok and token_ok


def _do_post(self):
    if self.path != "/api/say" or not _post_ok(self):
        return self._send(403, b'{"ok":false}', "application/json")
    try:
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > 4000:
            raise ValueError
        text = str(json.loads(self.rfile.read(n)).get("text", "")).strip()[:300]
        if not text:
            raise ValueError
    except Exception:
        return self._send(400, b'{"ok":false}', "application/json")
    _typed.put(text)
    self._send(200, b'{"ok":true}', "application/json")


_Handler.do_POST = _do_post


def _open_window(url):
    """Open the interface in its own app-style window (Edge), else in the browser."""
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(f'start "" msedge --app={url} --window-size=1400,900',
                             shell=True)
            return
    except Exception:
        pass
    webbrowser.open(url)


def start(open_window=True, owner_title="MASTER", model=""):
    """Start the interface. Never raises: if it cannot start, Octo still works."""
    global _url
    update(owner_title=str(owner_title).upper(), model=model)
    for port in PORTS:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        except OSError:
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        threading.Thread(target=_stats_loop, daemon=True).start()
        _url = f"http://127.0.0.1:{port}"
        print(f"[OCTO] live interface: {_url}")
        if open_window:
            _open_window(_url)
        return _url
    print("[OCTO] could not start the live interface (all ports busy). Continuing without it.")
    return None
