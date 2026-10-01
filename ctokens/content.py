"""Content views of a conversation: last response, Bash commands and touched files."""
from __future__ import annotations

from collections import Counter, defaultdict

from .logs import lines


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


def bash_commands(path):
    """Every Bash tool_use command, in order, with its description."""
    commands = []
    for event in lines(path):
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                data = block.get("input") or {}
                commands.append({"command": str(data.get("command") or ""),
                                 "description": str(data.get("description") or "")})
    return commands


def touched_files(path):
    """Files opened by Read or changed by Write/Edit, with per-tool call counts."""
    counts = defaultdict(lambda: Counter())
    for event in lines(path):
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            name = block.get("name")
            if name not in ("Read", "Write", "Edit"):
                continue
            target = (block.get("input") or {}).get("file_path")
            if target:
                counts[str(target)][name] += 1
    return counts
