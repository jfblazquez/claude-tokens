import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fixtures import build_projects

from ctokens.pricing import load_prices
from ctokens.web.server import CSP, STATIC_FILES, Config, Handler, Server

DEFAULT_HOST = object()


def start_server(config, static_dir=None):
    server = Server(config, 0, **({"static_dir": static_dir} if static_dir else {}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(10)


def write_static(root):
    """Placeholder files for the fixed static map plus files that must never be served."""
    for name in STATIC_FILES.values():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"/* {name} */", encoding="utf-8")
    (Path(root) / "secret.txt").write_text("secret", encoding="utf-8")
    (Path(root) / "vendor" / "VERSIONS.txt").write_text("versions", encoding="utf-8")
    return Path(root)


class ServerTestCase(unittest.TestCase):
    """Real server on a free port in a thread, fixtures in a temporary projects folder."""

    @classmethod
    def setUpClass(cls):
        cls.quiet = mock.patch.object(Handler, "log_message", lambda *args: None)
        cls.quiet.start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projects = build_projects(cls.tmp.name)
        cls.static = write_static(Path(cls.tmp.name) / "static")
        cls.server, cls.thread = start_server(Config(cls.projects, load_prices(None)), cls.static)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.server, cls.thread)
        cls.tmp.cleanup()
        cls.quiet.stop()

    def request(self, path, method="GET", host=DEFAULT_HOST, body=None, port=None):
        connection = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=30)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if host is DEFAULT_HOST:
                host = f"127.0.0.1:{port or self.port}"
            if host is not None:
                connection.putheader("Host", host)
            if body is not None:
                connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def get_json(self, path, port=None):
        status, headers, body = self.request(path, port=port)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        return status, json.loads(body.decode("utf-8"))


class SecurityGateTest(ServerTestCase):
    def test_bad_host(self):
        for host in ("evil.example", "evil.example:8765", "127.0.0.2", "localhost.evil.example", "[::1]:8765",
                     "localhost:abc", "localhost:", ""):
            with self.subTest(host=host):
                status, headers, body = self.request("/", host=host)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body), {"error": "host not allowed"})
                self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_no_host(self):
        status, _, body = self.request("/api/conversations", host=None)
        self.assertEqual((status, json.loads(body)), (403, {"error": "host not allowed"}))

    def test_bad_host_reads_no_conversation(self):
        with mock.patch("ctokens.catalog.lines", side_effect=AssertionError("read a log")) as lines:
            status, _, _ = self.request("/api/conversations", host="evil.example")
        self.assertEqual(status, 403)
        lines.assert_not_called()

    def test_allowed_hosts_any_port(self):
        for host in ("localhost:9000", "localhost", "127.0.0.1", "LOCALHOST:1", f"127.0.0.1:{self.port}"):
            with self.subTest(host=host):
                self.assertEqual(self.request("/", host=host)[0], 200)

    def test_other_methods(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "FOO", "do_GET"):
            with self.subTest(method=method):
                status, headers, body = self.request("/api/conversations", method=method, body=b"x=1")
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "GET, HEAD")
                self.assertEqual(json.loads(body), {"error": "method not allowed"})

    def test_bad_host_wins_over_method(self):
        self.assertEqual(self.request("/", method="POST", host="evil.example", body=b"")[0], 403)

    def test_unknown_paths(self):
        for path in ("/nope", "/index.html", "/static/", "/static/secret.txt", "/static/vendor/VERSIONS.txt",
                     "/static/../secret.txt", "/static/%2e%2e/secret.txt", "/static/vendor/../app.js",
                     "/static/app.js/", "/api", "/api/", "/api/totals/", "/api/conversations/",
                     "http://127.0.0.1/static/app.js", "*"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": "not found"})

    def test_common_headers(self):
        for path, method in (("/", "GET"), ("/static/app.js", "GET"), ("/nope", "GET"), ("/", "POST"),
                             ("/", "HEAD")):
            with self.subTest(path=path, method=method):
                _, headers, _ = self.request(path, method=method)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        _, headers, _ = self.request("/", host="evil.example")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_csp_on_html_only(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "object-src 'none'",
                          "base-uri 'none'", "frame-ancestors 'none'"):
            self.assertIn(directive, headers["Content-Security-Policy"])
        self.assertNotIn("http", CSP)
        self.assertIsNone(self.request("/static/app.js")[1]["Content-Security-Policy"])

    def test_head_has_no_body(self):
        status, headers, body = self.request("/", method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(headers["Content-Length"], str(len((self.static / "index.html").read_bytes())))

    def test_malformed_request_is_json(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=30) as raw:
            raw.sendall(b"GET / extra HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while chunk := raw.recv(65536):
                data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.0 400 "), head)
        self.assertIn(b"Content-Type: application/json; charset=utf-8", head)
        self.assertIn("error", json.loads(body))


class StaticFilesTest(ServerTestCase):
    def test_fixed_map(self):
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
        self.assertEqual(sorted(STATIC_FILES), sorted([
            "/", "/static/app.js", "/static/app.css", "/static/vendor/chart.umd.min.js",
            "/static/vendor/marked.min.js", "/static/vendor/purify.min.js", "/static/vendor/highlight.min.js",
            "/static/vendor/hljs-light.css", "/static/vendor/hljs-dark.css"]))
        for route, name in STATIC_FILES.items():
            with self.subTest(route=route):
                status, headers, body = self.request(route)
                self.assertEqual(status, 200)
                self.assertEqual(body, (self.static / name).read_bytes())
                self.assertEqual(headers["Content-Type"], types[Path(name).suffix])

    def test_missing_file_is_404(self):
        missing = Path(self.tmp.name) / "missing-static"
        missing.mkdir()
        server, thread = start_server(Config(self.projects, load_prices(None)), missing)
        try:
            status, _, body = self.request("/static/app.js", port=server.server_address[1])
        finally:
            stop_server(server, thread)
        self.assertEqual((status, json.loads(body)), (404, {"error": "not found"}))


if __name__ == "__main__":
    unittest.main()
