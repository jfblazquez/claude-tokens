"""Finding conversations in the projects folder."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
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


def conversation_text(path):
    """User prompts and assistant text of a log, whitespace-collapsed and casefolded for phrase search."""
    parts = []
    for event in lines(path):
        message = event.get("message")
        if event.get("type") not in ("user", "assistant") or not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts += [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return normalized(" ".join(parts))


def normalized(text):
    return " ".join(text.split()).casefold()


CONVERSATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def list_conversations(projects_dir, project_filter=None, project_of=project_path_of, title_of=session_title,
                       search=None, text_of=conversation_text):
    """Top-level session logs across every project, most recent first; search matches the title or the text."""
    phrase = normalized(search or "")
    conversations = []
    for project in projects_dir.iterdir() if projects_dir.is_dir() else []:
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            cwd = project_of(path)
            if project_filter and project_filter.lower() not in cwd.lower():
                continue
            title = title_of(path)
            if phrase and phrase not in normalized(title) and phrase not in text_of(path):
                continue
            stat = path.stat()
            conversations.append({
                "path": path, "mtime": stat.st_mtime, "size_kb": stat.st_size / 1024,
                "subagents": count_subagents(path), "project": cwd, "title": title,
            })
    conversations.sort(key=lambda row: row["mtime"], reverse=True)
    return conversations


def conversation_rows(projects_dir, project_filter=None, project_of=project_path_of, title_of=session_title,
                      search=None, text_of=conversation_text):
    """The picker's list as JSON-ready dicts; modified is ISO 8601 UTC."""
    return [{"id": row["path"].stem,
             "modified": datetime.fromtimestamp(row["mtime"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "size_kb": round(row["size_kb"], 1), "subagents": row["subagents"],
             "project": row["project"], "title": row["title"]}
            for row in list_conversations(projects_dir, project_filter, project_of, title_of, search, text_of)]


def find_conversation(conversation_id, projects_dir):
    """(path or None, matches) for a bare id; never touches the filesystem unless the id is a UUID."""
    if not isinstance(conversation_id, str) or not CONVERSATION_ID.fullmatch(conversation_id):
        return None, []
    if not projects_dir.is_dir():
        return None, []
    root = projects_dir.resolve()
    matches = [path for path in sorted(projects_dir.glob(f"*/{conversation_id}.jsonl"))
               if path.resolve().is_relative_to(root) and path.is_file()]
    return (matches[0] if len(matches) == 1 else None), matches


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
