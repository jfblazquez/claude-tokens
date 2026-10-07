import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from characterization import DATA, ENV, SCRIPT
from fixtures import CONV_A, ROOT, build_projects


def environment():
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env.update(ENV)
    return env


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def restore_sigint():
    # A parent shell may ignore SIGINT; Python only turns it into KeyboardInterrupt when it isn't ignored.
    signal.signal(signal.SIGINT, signal.SIG_DFL)


class ServeOptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projects = build_projects(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--projects-dir", str(self.projects)],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, env=environment(),
                              cwd=str(ROOT), timeout=60)

    def test_port_without_serve(self):
        done = self.cli("--port", "9000")
        self.assertEqual(done.returncode, 2)
        self.assertIn("error: --port requires --serve", done.stderr)

    def test_forbidden_options(self):
        cases = {"a conversation": [CONV_A], "--totals": ["--totals"], "--json": ["--json"],
                 "--last-response": ["--last-response"], "--bash": ["--bash"], "--files": ["--files"],
                 "--project": ["--project", "api"]}
        for label, extra in cases.items():
            with self.subTest(option=label):
                done = self.cli("--serve", *extra)
                self.assertEqual(done.returncode, 2)
                self.assertIn(f"error: --serve cannot be combined with {label}", done.stderr)
                self.assertNotIn("Serving on", done.stdout)

    def test_invalid_values(self):
        cases = {"--port must be between 1 and 65535": ["--port", "0"],
                 "--context-window must be positive": ["--context-window", "0"],
                 "--cold-summary-output must be non-negative": ["--cold-summary-output", "-1"]}
        for message, extra in cases.items():
            with self.subTest(message=message):
                done = self.cli("--serve", *extra)
                self.assertEqual(done.returncode, 2)
                self.assertIn(message, done.stderr)

    def test_invalid_pricing_fails_before_binding(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            done = self.cli("--serve", "--port", str(port), "--pricing", str(DATA / "bad-pricing.json"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("archivo de precios inválido", done.stderr)
        self.assertNotIn("already in use", done.stderr)

    def test_port_in_use(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            done = self.cli("--serve", "--port", str(port))
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stderr.strip(), f"error: port {port} is already in use")
        self.assertEqual(done.stdout, "")

    @unittest.skipUnless(hasattr(signal, "SIGINT") and os.name == "posix", "needs POSIX signals")
    def test_serve_with_allowed_options_until_ctrl_c(self):
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--serve", "--port", str(port), "--projects-dir", str(self.projects),
             "--pricing", str(DATA / "pricing.json"), "--cold-summary-output", "500", "--context-window", "1000000"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment(),
            cwd=str(ROOT), preexec_fn=restore_sigint)
        watchdog = threading.Timer(30, proc.kill)
        watchdog.start()
        try:
            banner = [proc.stdout.readline() for _ in range(3)]
            with socket.create_connection(("127.0.0.1", port), timeout=10):
                pass
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=30)
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(banner, [f"Serving on http://127.0.0.1:{port}  (Ctrl+C to stop)\n",
                                  f"  projects dir: {self.projects}\n",
                                  f"  from your machine: ssh -N -L {port}:localhost:{port} <this-host>\n"])
        self.assertEqual(proc.returncode, 0, err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
