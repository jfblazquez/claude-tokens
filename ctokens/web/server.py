"""HTTP server: security gate, routes and JSON responses."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple, Optional

HOST = "127.0.0.1"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class Config(NamedTuple):
    projects_dir: Path
    prices: dict
    cold_summary_output: int = 2000
    context_window: Optional[int] = None


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-tokens"
    sys_version = ""

    def do_GET(self):
        self.send_json(404, {"error": "not found"})

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEPORT would let two servers share the port instead of failing (R1.5).
    allow_reuse_port = False

    def __init__(self, config, port, static_dir=STATIC_DIR):
        self.config = config
        self.static_dir = Path(static_dir)
        super().__init__((HOST, port), Handler)
