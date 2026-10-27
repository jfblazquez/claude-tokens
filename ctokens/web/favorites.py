"""Starred conversations, kept in a small JSON file so every browser and every run of the server sees the same ones."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


def favorites_path(projects_dir):
    return Path(projects_dir).parent / "claude-tokens" / "favorites.json"


class Favorites:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def ids(self):
        """Starred ids, the most recently starred first; an unreadable file counts as none."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        ids = data.get("favorites") if isinstance(data, dict) else None
        return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []

    def set(self, conversation_id, starred):
        with self._lock:
            ids = [i for i in self.ids() if i != conversation_id]
            if starred:
                ids.insert(0, conversation_id)
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps({"favorites": ids}, indent=1), encoding="utf-8")
            os.replace(temporary, self.path)
            return ids
