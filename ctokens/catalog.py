"""Finding conversations in the projects folder."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .logs import lines


def default_projects_dir():
    root = os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")
    return Path(root) / "projects"


def project_path_of(path):
    """Real cwd stored in the log; fall back to the encoded folder name."""
    for event in lines(path):
        cwd = event.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return "/" + path.parent.name.lstrip("-").replace("-", "/")


def count_subagents(path):
    folder = path.parent / path.stem / "subagents"
    return len(list(folder.glob("*.jsonl"))) if folder.is_dir() else 0


def session_title(path, tail=131072):
    """Last user-facing session rename (aiTitle); empty when there is none."""
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            if size > tail:
                f.seek(-tail, 2)
            data = f.read()
    except OSError:
        return ""
    title = ""
    for line in data.decode("utf-8", "ignore").splitlines():
        if '"aiTitle"' not in line:
            continue
        try:
            value = json.loads(line).get("aiTitle")
        except json.JSONDecodeError:
            continue
        if value:
            title = value
    return title


def list_conversations(projects_dir, project_filter=None):
    """Top-level session logs across every project, most recent first."""
    conversations = []
    for project in projects_dir.iterdir() if projects_dir.is_dir() else []:
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            cwd = project_path_of(path)
            if project_filter and project_filter.lower() not in cwd.lower():
                continue
            stat = path.stat()
            conversations.append({
                "path": path, "mtime": stat.st_mtime, "size_kb": stat.st_size / 1024,
                "subagents": count_subagents(path), "project": cwd, "title": session_title(path),
            })
    conversations.sort(key=lambda row: row["mtime"], reverse=True)
    return conversations


def resolve_conversation(reference, projects_dir):
    """Accept a JSONL path or a bare conversation id (its filename stem)."""
    path = Path(reference)
    if path.is_file():
        return path, []
    stem = path.name[:-6] if path.name.endswith(".jsonl") else path.name
    matches = sorted(projects_dir.glob(f"*/{stem}.jsonl")) if projects_dir.is_dir() else []
    if len(matches) == 1:
        return matches[0], matches
    return None, matches
