"""HTTP server: security gate, routes and JSON responses."""
from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple, Optional

HOST = "127.0.0.1"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
STATIC_DIR = Path(__file__).resolve().parent / "static"
VENDOR_FILES = ("chart.umd.min.js", "marked.min.js", "purify.min.js", "highlight.min.js",
                "hljs-light.css", "hljs-dark.css")
STATIC_FILES = {"/": "index.html", "/static/app.js": "app.js", "/static/app.css": "app.css",
                **{f"/static/vendor/{name}": f"vendor/{name}" for name in VENDOR_FILES}}
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
JSON_TYPE = "application/json; charset=utf-8"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
COMMON_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
MAX_DISCARDED_BODY = 1 << 20


class Config(NamedTuple):
    projects_dir: Path
    prices: dict
    cold_summary_output: int = 2000
    context_window: Optional[int] = None


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str = JSON_TYPE
    headers: tuple = ()


def json_response(status, data, headers=()):
    return Response(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), JSON_TYPE, headers)


NOT_FOUND = json_response(404, {"error": "not found"})


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-tokens"
    sys_version = ""

    def __getattr__(self, name):
        # BaseHTTPRequestHandler answers 501 when do_<METHOD> is missing; every method but GET/HEAD gets 405.
        if name.startswith("do_"):
            return self.method_not_allowed
        raise AttributeError(name)

    def do_GET(self):
        if not self.host_allowed():
            return
        path, _, query = self.path.partition("?")
        try:
            response = self.route(path, query)
        except Exception:
            traceback.print_exc()
            response = json_response(500, {"error": "internal error"})
        self.respond(response)

    do_HEAD = do_GET

    def method_not_allowed(self):
        self.discard_body()
        if self.host_allowed():
            self.respond(json_response(405, {"error": "method not allowed"}, (("Allow", "GET, HEAD"),)))

    def host_allowed(self):
        hosts = self.headers.get_all("Host") or []
        host = hosts[0].strip().lower() if len(hosts) == 1 else ""
        if ":" in host:
            host, _, port = host.rpartition(":")
            if not port.isdigit():
                host = ""
        if host in ALLOWED_HOSTS:
            return True
        self.respond(json_response(403, {"error": "host not allowed"}))
        return False

    def discard_body(self):
        # Closing a socket with unread request data can reset the connection before the client reads the answer.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= MAX_DISCARDED_BODY:
            self.rfile.read(length)

    def route(self, path, query):
        if path in STATIC_FILES:
            return self.static(STATIC_FILES[path])
        return NOT_FOUND

    def static(self, name):
        try:
            body = (self.server.static_dir / name).read_bytes()
        except OSError:
            return NOT_FOUND
        content_type = CONTENT_TYPES[Path(name).suffix]
        headers = (("Content-Security-Policy", CSP),) if content_type.startswith("text/html") else ()
        return Response(200, body, content_type, headers)

    def respond(self, response):
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in (*COMMON_HEADERS.items(), *response.headers):
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        self.respond(json_response(code, {"error": message or self.responses.get(code, ("error",))[0].lower()}))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEPORT would let two servers share the port instead of failing (R1.5).
    allow_reuse_port = False

    def __init__(self, config, port, static_dir=STATIC_DIR):
        self.config = config
        self.static_dir = Path(static_dir)
        super().__init__((HOST, port), Handler)
