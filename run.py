"""Start the laptop helper and display the phone's private links."""

from __future__ import annotations

import base64
import html
import io
import os
import re
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
SETUP_URL = f"http://127.0.0.1:{SETUP_PORT}/"
_public_url = ""
_tunnel_message = "Starting tunnel…"
_state_lock = threading.Lock()
_stop = threading.Event()
_tunnel_process: subprocess.Popen[str] | None = None


def bluetooth_ip() -> str | None:
    command = (
        "Get-NetIPAddress -InterfaceAlias 'Bluetooth Network Connection' "
        "-AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        "Where-Object { $_.IPAddress -notlike '169.254.*' } | "
        "Select-Object -First 1 -ExpandProperty IPAddress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


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
    bt_ip = bluetooth_ip()
    cards = []
    if public_url:
        pair = urlencode({"endpoint": public_url, "token": remote.TOKEN})
        cards.append(link_card("Hosted phone page", PAGES_URL + "#" + pair))
        cards.append("<details><summary>Direct tunnel backup</summary>" + link_card("Direct tunnel backup", public_url + "/#" + remote.TOKEN) + "</details>")
    else:
        cards.append(f"<section><h2>Internet link</h2><p>{html.escape(message)}</p></section>")
    if bt_ip:
        cards.append(link_card("Bluetooth backup", f"http://{bt_ip}:{remote.PORT}/#" + remote.TOKEN))
    else:
        cards.append("<section><h2>Bluetooth backup</h2><p>Pair the phone, enable Android Bluetooth tethering, then connect the laptop to its Bluetooth PAN. This card will appear when Windows receives an address.</p></section>")
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
    page += "</main><p><small>Keep this private link to yourself. It expires when you stop the launcher. If the tunnel restarts, scan its new QR code.</small></p></html>"
    return page.encode("utf-8")


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path != "/":
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


def tunnel_worker() -> None:
    global _public_url, _tunnel_message, _tunnel_process
    if not TUNNEL.is_file():
        with _state_lock:
            _tunnel_message = f"Missing {TUNNEL}. Run setup.ps1 first."
        return
    while not _stop.is_set():
        with _state_lock:
            _public_url = ""
            _tunnel_message = "Connecting to Cloudflare…"
        process = None
        try:
            process = subprocess.Popen(
                [str(TUNNEL), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{remote.PORT}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            _tunnel_process = process
            assert process.stdout is not None
            for line in process.stdout:
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match:
                    with _state_lock:
                        _public_url = match.group(0)
                        _tunnel_message = "Connected"
                    print("Internet QR is ready in the setup page.", flush=True)
                elif "ERR" in line or "error" in line.lower():
                    print("Tunnel:", line.strip(), flush=True)
                if _stop.is_set():
                    break
            process.wait(timeout=3)
        except Exception as exc:
            print("Tunnel failed:", exc, flush=True)
        finally:
            if process and process.poll() is None:
                process.terminate()
            _tunnel_process = None
            with _state_lock:
                _public_url = ""
                _tunnel_message = "Tunnel reconnecting…"
        _stop.wait(4)


def main() -> None:
    try:
        server = remote.make_server()
        setup_server = ThreadingHTTPServer(("127.0.0.1", SETUP_PORT), SetupHandler)
    except OSError as exc:
        raise SystemExit(f"Cannot start remote or setup server: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    threading.Thread(target=setup_server.serve_forever, daemon=True).start()
    threading.Thread(target=tunnel_worker, daemon=True).start()
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
        if _tunnel_process and _tunnel_process.poll() is None:
            _tunnel_process.terminate()
        server.shutdown()
        server.server_close()
        setup_server.shutdown()
        setup_server.server_close()


if __name__ == "__main__":
    main()
