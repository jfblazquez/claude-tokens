"""Content views of a conversation: last response, Bash commands and touched files."""
from __future__ import annotations

import re
from datetime import datetime

from .logs import conversation_sources, lines, parse_timestamp, tool_uses


def last_response(path):
    """Text of the final assistant turn (concatenated text blocks)."""
    result = ""
    for event in lines(path):
        message = event.get("message")
        if event.get("type") != "assistant" or not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text_blocks = [content]
        elif isinstance(content, list):
            text_blocks = [b.get("text", "") for b in content
                           if isinstance(b, dict) and b.get("type") == "text"]
        else:
            text_blocks = []
        joined = "\n".join(t for t in text_blocks if t)
        if joined.strip():
            result = joined
    return result


def chronological_key(timestamp):
    """Sort key: dated entries by time (with sub-second precision), undated ones after them."""
    stamp = parse_timestamp(timestamp)
    if stamp is None:
        return (1, datetime.min, 0.0)
    fraction = re.match(r"\.(\d+)", timestamp[19:])
    return (0, stamp, float("0." + fraction.group(1)) if fraction else 0.0)


def bash_commands(main):
    """Every Bash tool_use command of the conversation and its subagents, in chronological order."""
    commands, seen = [], set()
    for source, path in conversation_sources(main):
        for event in lines(path):
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            timestamp = event.get("timestamp")
            timestamp = timestamp if parse_timestamp(timestamp) else None
            for block in tool_uses(message, seen):
                if block.get("name") == "Bash":
                    data = block.get("input") or {}
                    commands.append({"command": str(data.get("command") or ""),
                                     "description": str(data.get("description") or ""),
                                     "source": source, "timestamp": timestamp})
    # sorted() is stable, so undated entries keep their log order.
    return sorted(commands, key=lambda entry: chronological_key(entry["timestamp"]))


def touched_files(main):
    """Files opened by Read or changed by Write/Edit across the conversation and its subagents."""
    files, seen = {}, set()
    for source, path in conversation_sources(main):
        for event in lines(path):
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            for block in tool_uses(message, seen):
                name = block.get("name")
                if name not in ("Read", "Write", "Edit"):
                    continue
                target = (block.get("input") or {}).get("file_path")
                if not target:
                    continue
                entry = files.setdefault(str(target), {"Read": 0, "Write": 0, "Edit": 0, "sources": []})
                entry[name] += 1
                if source not in entry["sources"]:
                    entry["sources"].append(source)
    return files
