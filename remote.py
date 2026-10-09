"""Authenticated WebSocket slide remote for a Windows laptop."""

from __future__ import annotations

import asyncio
import ctypes
import hmac
import json
import os
import secrets
import threading
import time
from ctypes import wintypes

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed


PORT = 8765
PAGES_ORIGIN = "https://vjk7989.github.io"
TOKEN = secrets.token_urlsafe(24)
ACTION_KEYS = {
    "next": (0x22,),                         # Page Down
    "previous": (0x21,),                     # Page Up
    "window": (0x12, 0x09),                  # Alt+Tab
    "tab": (0x11, 0x09),                     # Ctrl+Tab
    "previous_tab": (0x11, 0x10, 0x09),      # Ctrl+Shift+Tab
    "literal_chord": (0x12, 0x11, 0x10, 0x09),  # Alt+Ctrl+Shift+Tab
    "select": (0x0D,),                       # Enter
}


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
    """Inject a key or chord into the foreground Windows app."""
    if os.name != "nt":
        raise RuntimeError("Windows is required")
    codes = [(key, 0) for key in keys]
    codes += [(key, 0x0002) for key in reversed(keys)]
    events = (INPUT * len(codes))()
    for event, (key, flags) in zip(events, codes):
        event.type = 1
        event.ki = KEYBDINPUT(key, 0, flags, 0, 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


class RemoteSession:
    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.active: ServerConnection | None = None
        self.active_lock = asyncio.Lock()
        self.command_lock = asyncio.Lock()
        self.recent_ids: dict[str, float] = {}
        self.last_action_at = 0.0

    async def handle(self, ws: ServerConnection) -> None:
        if not ws.request or ws.request.path != "/ws":
            await ws.close(code=1008, reason="Wrong path")
            return
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=5)
            hello = json.loads(first)
            if not isinstance(hello, dict) or hello.get("type") != "start" or not isinstance(hello.get("token"), str):
                raise ValueError("Invalid start message")
            if not hmac.compare_digest(hello["token"], self.token):
                raise ValueError("Invalid pairing")
        except (asyncio.TimeoutError, ValueError, TypeError, json.JSONDecodeError, ConnectionClosed):
            await ws.close(code=4003, reason="Invalid pairing")
            return

        async with self.active_lock:
            previous = self.active
            self.active = ws
        if previous is not None and previous is not ws:
            await previous.close(code=4001, reason="Another phone took control")
        await ws.send(json.dumps({"type": "ready"}))
        try:
            async for message in ws:
                if self.active is not ws:
                    await ws.close(code=4001, reason="Another phone took control")
                    return
                await self.handle_command(ws, message)
        except ConnectionClosed:
            pass
        finally:
            async with self.active_lock:
                if self.active is ws:
                    self.active = None

    async def handle_command(self, ws: ServerConnection, raw: str | bytes) -> None:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("type") != "command":
                raise ValueError
            request_id = payload.get("id")
            action = payload.get("action")
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80 or not isinstance(action, str):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError):
            await ws.close(code=1008, reason="Invalid command")
            return
        if action not in ACTION_KEYS:
            await ws.send(json.dumps({"type": "ack", "id": request_id, "ok": False, "error": "Unknown command"}))
            return
        async with self.command_lock:
            now = time.monotonic()
            for old_id, when in list(self.recent_ids.items()):
                if now - when > 60:
                    del self.recent_ids[old_id]
            if request_id in self.recent_ids:
                result = {"type": "ack", "id": request_id, "ok": True, "duplicate": True}
            elif now - self.last_action_at < 0.15:
                result = {"type": "ack", "id": request_id, "ok": False, "error": "Wait a moment"}
            else:
                try:
                    send_keys(ACTION_KEYS[action])
                except Exception as exc:
                    print("Keyboard input failed:", exc, flush=True)
                    result = {"type": "ack", "id": request_id, "ok": False, "error": "Laptop rejected the keypress"}
                else:
                    self.last_action_at = now
                    self.recent_ids[request_id] = now
                    result = {"type": "ack", "id": request_id, "ok": True}
        await ws.send(json.dumps(result))


SESSION = RemoteSession()


async def _serve(stop: threading.Event, ready: threading.Event) -> None:
    async with serve(
        SESSION.handle,
        "127.0.0.1",
        PORT,
        origins=[PAGES_ORIGIN],
        ping_interval=20,
        ping_timeout=20,
        max_size=512,
        compression=None,
    ):
        ready.set()
        await asyncio.to_thread(stop.wait)


def run_server(stop: threading.Event, ready: threading.Event, errors: list[Exception]) -> None:
    try:
        asyncio.run(_serve(stop, ready))
    except Exception as exc:
        errors.append(exc)
        ready.set()
