"""Per-file caches of parse results: whole results valid while a log is unchanged, and growing transcripts."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from ..content import Transcript


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
