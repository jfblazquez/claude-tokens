"""Per-file caches of parse results: whole results valid while a log is unchanged, and growing transcripts."""
from __future__ import annotations

import multiprocessing
import os
import signal
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..content import Transcript

# Fewer logs than this are read by the request's own thread, as they are asked for: starting processes costs more.
WARM_MIN = 8
MAX_WORKERS = 16
WORKERS_IDLE = 120.0
FAILED = object()


class StatsCache:
    """(namespace, path) -> ((st_mtime_ns, st_size), value); values must not be mutated by callers."""

    def __init__(self):
        self._entries = {}
        self._lock = threading.Lock()

    def get(self, namespace, path, compute):
        path = Path(path)
        # Stat before computing: a file that changes meanwhile is stored under its old stamp and re-read next time.
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            entry = self._entries.get((namespace, path))
        if entry is not None and entry[0] == stamp:
            return entry[1]
        # Computed outside the lock so a cold totals scan doesn't block the list or the report views.
        value = compute(path)
        with self._lock:
            self._entries[(namespace, path)] = (stamp, value)
        return value

    def warm(self, namespace, paths, compute, workers):
        """Computes at once, in worker processes, the entries of the paths that are missing or out of date, so that the
        get() calls that follow find them; compute must be a function the processes can import."""
        stale = []
        for path in map(Path, paths):
            try:
                stat = os.stat(path)
            except OSError:
                continue
            with self._lock:
                entry = self._entries.get((namespace, path))
            if entry is None or entry[0] != (stat.st_mtime_ns, stat.st_size):
                stale.append((path, (stat.st_mtime_ns, stat.st_size)))
        if len(stale) < WARM_MIN:
            return
        values = workers.map(compute, [path for path, _ in stale])
        with self._lock:
            for (path, stamp), value in zip(stale, values):
                if value is not FAILED:
                    self._entries[(namespace, path)] = (stamp, value)

    def prune(self, seen):
        """Evict entries of paths not in seen that no longer exist (deleted logs)."""
        with self._lock:
            candidates = [key for key in self._entries if key[1] not in seen]
        gone = [key for key in candidates if not key[1].exists()]
        with self._lock:
            for key in gone:
                self._entries.pop(key, None)

    def paths(self, namespace):
        with self._lock:
            return {path for name, path in self._entries if name == namespace}


class TranscriptCache:
    """One Transcript per log, advanced in place as the log grows; one log is read by one request at a time."""

    def __init__(self):
        self._entries = {}
        self._lock = threading.Lock()

    def get(self, path, prices):
        path = Path(path)
        with self._lock:
            entry = self._entries.get(path)
            if entry is None:
                entry = self._entries[path] = (threading.Lock(), Transcript(path, prices))
        lock, transcript = entry
        with lock:
            return list(transcript.advance())


def worker_start():
    """Ctrl+C reaches the workers too, but it is the server that closes them; and they end with it, even when it is
    killed outright, instead of being left behind."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    parent = multiprocessing.parent_process()
    if parent is not None:
        threading.Thread(target=lambda: (parent.join(), os._exit(0)), daemon=True).start()


class Workers:
    """Processes that read many logs at once. The server's threads share one interpreter lock: a cold scan of thousands
    of logs in a thread runs on one core and slows every other request meanwhile."""

    def __init__(self, size=None):
        self.size = size or min(MAX_WORKERS, os.cpu_count() or 1)
        self._pool, self._used, self._busy = None, 0.0, 0
        self._lock = threading.Lock()

    def map(self, compute, items):
        """compute(item) for each item, FAILED for those that raised; all FAILED when no process could be started, and
        the caller's thread does the work then."""
        with self._lock:
            try:
                if self._pool is None:
                    method = "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
                    self._pool = ProcessPoolExecutor(self.size, mp_context=multiprocessing.get_context(method),
                                                     initializer=worker_start)
                futures = [self._pool.submit(compute, item) for item in items]
            except (OSError, RuntimeError):
                self._close()
                return [FAILED] * len(items)
            self._busy += 1
        results = []
        try:
            for future in futures:
                try:
                    results.append(future.result())
                except Exception:
                    results.append(FAILED)
        finally:
            with self._lock:
                self._busy -= 1
                self._used = time.monotonic()
        return results

    def reap(self):
        """Lets the processes go once they have been idle a while; the next cold scan starts them again."""
        with self._lock:
            if self._pool is not None and not self._busy and time.monotonic() - self._used > WORKERS_IDLE:
                self._close()

    def close(self):
        with self._lock:
            self._close()

    def _close(self):
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        self._pool = None
