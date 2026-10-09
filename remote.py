"""Small, single-purpose slide remote server for Windows."""

from __future__ import annotations

import ctypes
import hmac
import json
import os
import secrets
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PORT = 8765
PAGE = (Path(__file__).parent / "docs" / "index.html").read_bytes()
TOKEN = secrets.token_urlsafe(24)
PAGES_ORIGIN = "https://vjk7989.github.io"
ACTION_KEYS = {
    "next": (0x22,),       # Page Down
    "previous": (0x21,),   # Page Up
    "window": (0x12, 0x09),  # Alt+Tab
    "tab": (0x11, 0x09),     # Ctrl+Tab
}
_key_lock = threading.Lock()
_last_action_at = 0.0
_recent_ids: dict[str, float] = {}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


def send_keys(keys: tuple[int, ...]) -> None:
    """Inject one key or one modifier chord into the foreground window."""
    if os.name != "nt":
        raise RuntimeError("Windows is required")
    codes = [(key, 0) for key in keys]
    codes += [(key, 0x0002) for key in reversed(keys)]  # KEYEVENTF_KEYUP
    events = (INPUT * len(codes))()
    for event, (key, flags) in zip(events, codes):
        event.type = 1  # INPUT_KEYBOARD
        event.ki = KEYBDINPUT(key, 0, flags, 0, 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


class RemoteHandler(BaseHTTPRequestHandler):
    server_version = "SlideRemote/1.0"

    def log_message(self, format: str, *args: object) -> None:
        # Never log the private link or token.
        print("Request from", self.client_address[0], format % args, flush=True)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        if self.headers.get("Origin") == PAGES_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", PAGES_ORIGIN)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if self.path not in ("/health", "/command") or self.headers.get("Origin") != PAGES_ORIGIN:
            self._send(403, b"", "text/plain")
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", PAGES_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Remote-Token")
        self.send_header("Access-Control-Max-Age", "300")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, status: int, value: dict[str, object]) -> None:
        self._send(status, json.dumps(value).encode(), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        return hmac.compare_digest(self.headers.get("X-Remote-Token", ""), TOKEN)

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/health":
            if not self._authorized():
                self._json(403, {"error": "invalid remote link"})
                return
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        global _last_action_at
        if self.path != "/command":
            self._json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._json(403, {"error": "invalid remote link"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(415, {"error": "JSON required"})
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
            if not 1 <= size <= 256:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            action = payload["action"]
            request_id = payload["id"]
            if action not in ACTION_KEYS or not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid command"})
            return
        with _key_lock:
            now = time.monotonic()
            for old_id, when in list(_recent_ids.items()):
                if now - when > 30:
                    del _recent_ids[old_id]
            if request_id in _recent_ids:
                self._json(200, {"ok": True, "duplicate": True})
                return
            if now - _last_action_at < 0.15:
                self._json(429, {"error": "wait a moment"})
                return
            try:
                send_keys(ACTION_KEYS[action])
            except Exception as exc:
                print("Keyboard input failed:", exc, flush=True)
                self._json(503, {"error": "laptop rejected the keypress"})
                return
            _last_action_at = now
            _recent_ids[request_id] = now
        self._json(200, {"ok": True})


def make_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RemoteHandler)
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    print(f"Serving remote on port {PORT}", flush=True)
    with make_server() as server:
        server.serve_forever()
