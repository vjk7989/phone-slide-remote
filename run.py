"""Start the laptop helper and display the phone's private links."""

from __future__ import annotations

import base64
import html
import io
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))

import qrcode
from qrcode.image.svg import SvgPathImage

import remote


TUNNEL = ROOT / "tools" / "cloudflared.exe"
PAGES_URL = "https://vjk7989.github.io/phone-slide-remote/"
SETUP_PORT = 8766
PAIR_PATH = "/pair/" + secrets.token_urlsafe(32)
SETUP_URL = f"http://127.0.0.1:{SETUP_PORT}{PAIR_PATH}"
_public_url = ""
_tunnel_message = "Starting tunnel…"
_setup_public_url = ""
_state_lock = threading.Lock()
_stop = threading.Event()
_tunnel_processes: dict[str, subprocess.Popen[str]] = {}


def qr_data(url: str) -> str:
    image = qrcode.make(url, image_factory=SvgPathImage, box_size=6, border=3)
    data = io.BytesIO()
    image.save(data)
    return "data:image/svg+xml;base64," + base64.b64encode(data.getvalue()).decode("ascii")


def link_card(title: str, url: str) -> str:
    safe_url = html.escape(url, quote=True)
    return (
        f"<section><h2>{html.escape(title)}</h2>"
        f'<img src="{qr_data(url)}" alt="QR code for {html.escape(title, quote=True)}">'
        f'<p><a href="{safe_url}">{safe_url}</a></p></section>'
    )


def setup_page() -> bytes:
    with _state_lock:
        public_url = _public_url
        message = _tunnel_message
        hosted_setup_url = _setup_public_url + PAIR_PATH if _setup_public_url else ""
    cards = []
    if public_url:
        pair = urlencode({"endpoint": public_url, "token": remote.TOKEN})
        cards.append(link_card("Hosted phone page", PAGES_URL + "#" + pair))
    else:
        cards.append(f"<section><h2>Internet link</h2><p>{html.escape(message)}</p></section>")
    if hosted_setup_url:
        cards.append(f'<section><h2>Hosted QR page</h2><p><a href="{html.escape(hosted_setup_url, quote=True)}">Open the hosted QR page</a></p></section>')
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta http-equiv="refresh" content="8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slide remote setup</title><style>
body{font:18px system-ui,sans-serif;max-width:950px;margin:2rem auto;padding:0 1rem;background:#f8fafc;color:#111827}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:1rem}
section{background:white;padding:1.2rem;border-radius:1rem;box-shadow:0 1px 8px #d7dce3}
img{display:block;width:min(100%,320px);height:auto;margin:auto}a{overflow-wrap:anywhere}
small{color:#4b5563}</style><h1>Slide remote</h1>
<p>Scan the Hosted phone page QR code on your Android phone. Keep this page open on the laptop.</p><main>"""
    page += "".join(cards)
    page += "</main><p><small>Keep this private link to yourself. It expires when you stop the launcher. Tap Start on the phone page to connect. If the tunnel restarts, scan its new QR code.</small></p></html>"
    return page.encode("utf-8")


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path != PAIR_PATH:
            self.send_error(404)
            return
        body = setup_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def tunnel_worker(port: int, kind: str) -> None:
    global _public_url, _tunnel_message, _setup_public_url
    if not TUNNEL.is_file():
        with _state_lock:
            _tunnel_message = f"Missing {TUNNEL}. Run setup.ps1 first."
        return
    while not _stop.is_set():
        with _state_lock:
            if kind == "remote":
                _public_url = ""
                _tunnel_message = "Connecting to Cloudflare…"
            else:
                _setup_public_url = ""
        process = None
        try:
            process = subprocess.Popen(
                [str(TUNNEL), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            _tunnel_processes[kind] = process
            assert process.stdout is not None
            for line in process.stdout:
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match:
                    with _state_lock:
                        if kind == "remote":
                            _public_url = match.group(0)
                            _tunnel_message = "Connected"
                        else:
                            _setup_public_url = match.group(0)
                    if kind == "remote":
                        print("Internet QR is ready in the setup page.", flush=True)
                    else:
                        print(f"Hosted QR page: {match.group(0)}{PAIR_PATH}", flush=True)
                elif "ERR" in line or "error" in line.lower():
                    print(f"{kind} tunnel:", line.strip(), flush=True)
                if _stop.is_set():
                    break
            process.wait(timeout=3)
        except Exception as exc:
            print(f"{kind} tunnel failed:", exc, flush=True)
        finally:
            if process and process.poll() is None:
                process.terminate()
            _tunnel_processes.pop(kind, None)
            with _state_lock:
                if kind == "remote":
                    _public_url = ""
                    _tunnel_message = "Tunnel reconnecting…"
                else:
                    _setup_public_url = ""
        _stop.wait(4)


def main() -> None:
    try:
        setup_server = ThreadingHTTPServer(("127.0.0.1", SETUP_PORT), SetupHandler)
    except OSError as exc:
        raise SystemExit(f"Cannot start setup server: {exc}")
    ready = threading.Event()
    errors: list[Exception] = []
    ws_thread = threading.Thread(target=remote.run_server, args=(_stop, ready, errors), daemon=True)
    ws_thread.start()
    if not ready.wait(5) or errors:
        _stop.set()
        setup_server.server_close()
        raise SystemExit(f"Cannot start WebSocket server: {errors[0] if errors else 'timed out'}")
    threading.Thread(target=setup_server.serve_forever, daemon=True).start()
    threading.Thread(target=tunnel_worker, args=(remote.PORT, "remote"), daemon=True).start()
    threading.Thread(target=tunnel_worker, args=(SETUP_PORT, "setup"), daemon=True).start()
    print(f"Setup page: {SETUP_URL}", flush=True)
    print("Keep this window open while presenting. Press Ctrl+C here to stop.", flush=True)
    if os.environ.get("SLIDE_REMOTE_NO_BROWSER") != "1":
        webbrowser.open(SETUP_URL)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _stop.set()
        for process in list(_tunnel_processes.values()):
            if process.poll() is None:
                process.terminate()
        setup_server.shutdown()
        setup_server.server_close()
        ws_thread.join(timeout=5)


if __name__ == "__main__":
    main()
