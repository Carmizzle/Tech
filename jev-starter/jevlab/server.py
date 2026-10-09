"""A tiny local web server for the dashboards. Serves this folder on 127.0.0.1 only."""

from __future__ import annotations

import os
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _Handler(SimpleHTTPRequestHandler):
    page = "loop.html"  # which dashboard "/" opens

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = f"/dashboard/{self.page}"
        elif self.path.startswith("/results/loop.json"):  # each port shows its own run
            self.path = self.path.replace("/results/loop.json", f"/results/loop_{self.port}.json", 1)
        return super().do_GET()

    def log_message(self, *args):  # keep the terminal clean
        pass


class _Server(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second dashboard share a busy port, so the browser can land
    # on an old one still running (e.g. the newsroom). Refuse instead, like Mac and Linux do.
    allow_reuse_address = os.name != "nt"


def serve(port: int = 8765, open_browser: bool = True, page: str = "loop.html") -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"page": page, "port": port})
    try:
        server = _Server(("127.0.0.1", port), partial(handler, directory=str(ROOT)))
    except OSError:
        raise SystemExit(f"  port {port} is busy. Stop the other dashboard (Ctrl+C) or add --port {port + 1}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"  dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    return server
