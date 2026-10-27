"""Interactive shells the web UI opens in a conversation's folder: a pseudo-terminal per shell, read by a thread."""
from __future__ import annotations

import fcntl
import os
import pty
import secrets
import signal
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

MAX_SHELLS = 8
# A reconnecting page gets what it missed from here; a full-screen program redraws itself on the next resize anyway.
MAX_BUFFER = 1 << 20
READ_CHUNK = 1 << 16
# A shell nobody reads (the page was closed or lost its connection) ends after this long.
DETACHED_GRACE = 120.0
KILL_GRACE = 2.0
MIN_SIZE, MAX_SIZE = 2, 1000


class ShellError(Exception):
    pass


def set_size(fd, cols, rows):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def clamp(n, default):
    return max(MIN_SIZE, min(MAX_SIZE, n)) if isinstance(n, int) and not isinstance(n, bool) else default


def take_terminal():
    # Runs in the child between fork and exec: the pty becomes the controlling terminal, so job control and ^C work.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class Shell:
    def __init__(self, token, conversation_id, cwd, cols, rows, cond):
        self.token, self.conversation_id, self.cwd = token, conversation_id, cwd
        self.started = time.time()
        master, slave = pty.openpty()
        set_size(master, cols, rows)
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        try:
            self.proc = subprocess.Popen([os.environ.get("SHELL") or "/bin/bash"], cwd=cwd, env=env, stdin=slave,
                                         stdout=slave, stderr=slave, start_new_session=True, preexec_fn=take_terminal)
        except OSError as error:
            os.close(master)
            raise ShellError(f"Could not start a shell: {error.strerror or error}") from None
        finally:
            os.close(slave)
        self.fd = master
        # Shared by every shell, so one stream can wait for output from any of them.
        self.cond = cond
        self.buffer = bytearray()
        self.base = 0
        self.code = None
        self.exited = False
        self.readers = 0
        self.detached_at = time.monotonic()
        threading.Thread(target=self.pump, daemon=True, name=f"shell-{token[:6]}").start()

    @property
    def end(self):
        return self.base + len(self.buffer)

    def pump(self):
        while True:
            try:
                data = os.read(self.fd, READ_CHUNK)
            except OSError:
                data = b""
            if not data:
                break
            with self.cond:
                self.buffer += data
                if len(self.buffer) > MAX_BUFFER:
                    drop = len(self.buffer) - MAX_BUFFER
                    del self.buffer[:drop]
                    self.base += drop
                self.cond.notify_all()
        code = self.proc.wait()
        with self.cond:
            self.code, self.exited = code, True
            self.cond.notify_all()
        try:
            os.close(self.fd)
        except OSError:
            pass

    def read(self, offset, timeout):
        """(offset after the data, data from offset on, exited); data starts later when offset fell off the buffer."""
        with self.cond:
            if offset >= self.end and not self.exited:
                self.cond.wait(timeout)
            start = max(offset, self.base)
            return self.end, bytes(self.buffer[start - self.base:]), self.exited

    def write(self, data):
        if self.exited:
            raise ShellError("The shell has ended.")
        view = memoryview(data)
        while view:
            try:
                written = os.write(self.fd, view)
            except OSError as error:
                raise ShellError(f"Could not write to the shell: {error.strerror or error}") from None
            view = view[written:]

    def resize(self, cols, rows):
        if not self.exited:
            try:
                set_size(self.fd, cols, rows)
            except OSError:
                pass

    def attach(self):
        with self.cond:
            self.readers += 1

    def detach(self):
        with self.cond:
            self.readers -= 1
            if not self.readers:
                self.detached_at = time.monotonic()

    def abandoned(self, now):
        with self.cond:
            return not self.readers and (self.exited or now - self.detached_at > DETACHED_GRACE)

    def close(self):
        """Hang up the whole session, as closing a terminal window does; kill what ignores it."""
        if self.exited:
            return
        for sig, wait in ((signal.SIGHUP, KILL_GRACE), (signal.SIGKILL, KILL_GRACE)):
            try:
                os.killpg(self.proc.pid, sig)
            except OSError:
                return
            with self.cond:
                if self.cond.wait_for(lambda: self.exited, wait):
                    return

    def public(self):
        return {"id": self.token, "conversation_id": self.conversation_id, "cwd": self.cwd, "pid": self.proc.pid,
                "started": self.started, "exited": self.exited, "code": self.code}


class Shells:
    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition()
        self.shells = {}

    def open(self, conversation_id, cwd, cols=None, rows=None):
        if not cwd or not Path(cwd).is_dir():
            raise ShellError(f"The folder {cwd} does not exist.")
        self.reap()
        with self.lock:
            if len(self.shells) >= MAX_SHELLS:
                raise ShellError(f"There are already {MAX_SHELLS} shells open; close one first.")
            token = secrets.token_urlsafe(24)
            shell = self.shells[token] = Shell(token, conversation_id, str(cwd), clamp(cols, 80), clamp(rows, 24), self.cond)
        return shell

    def read(self, offsets, timeout):
        """[(token, offset after the data, data, exited, exit code)] for the shells of {token: offset} with news; waits
        up to timeout for some. A token no shell has any more comes back as exited, with no code."""
        shells = {token: self.get(token) for token in offsets}

        def news(token, shell):
            return shell is None or shell.exited or shell.end > offsets[token]

        with self.cond:
            if not any(news(t, s) for t, s in shells.items()):
                self.cond.wait(timeout)
            changes = []
            for token, shell in shells.items():
                if shell is None:
                    changes.append((token, offsets[token], b"", True, None))
                elif news(token, shell):
                    start = max(offsets[token], shell.base)
                    changes.append((token, shell.end, bytes(shell.buffer[start - shell.base:]), shell.exited, shell.code))
            return changes

    def get(self, token):
        with self.lock:
            return self.shells.get(token)

    def close(self, token):
        with self.lock:
            shell = self.shells.pop(token, None)
        if shell:
            shell.close()
        return shell is not None

    def reap(self):
        now = time.monotonic()
        with self.lock:
            gone = [t for t, s in self.shells.items() if s.abandoned(now)]
            shells = [self.shells.pop(t) for t in gone]
        for shell in shells:
            shell.close()

    def close_all(self):
        with self.lock:
            shells, self.shells = list(self.shells.values()), {}
        for shell in shells:
            shell.close()
