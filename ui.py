"""HEX's live interface.

Starts a tiny web server that only listens on THIS laptop (127.0.0.1) and shows
HEX's live status in a window. The page is read-only: it can display things,
but it can never give HEX a command. Only your voice can do that.
"""
import json
import os
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
    "log": [], "you": "", "hex": "", "owner_title": "MASTER", "started": time.time(),
}
_probe = None
_url = None


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
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"hex_ui.html is missing", "text/plain")
        elif self.path.startswith("/api/state"):
            with _lock:
                snap = dict(_state)
                snap["log"] = list(_state["log"])
            snap["uptime"] = int(time.time() - snap.pop("started"))
            self._send(200, json.dumps(snap).encode(), "application/json")
        elif self.path.startswith("/favicon"):
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, b"not found", "text/plain")


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
    """Start the interface. Never raises: if it cannot start, HEX still works."""
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
        print(f"[HEX] live interface: {_url}")
        if open_window:
            _open_window(_url)
        return _url
    print("[HEX] could not start the live interface (all ports busy). Continuing without it.")
    return None
