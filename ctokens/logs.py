"""Reading Claude Code JSONL logs: events, per-log usage and the sources of a conversation."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime


FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def zero():
    return dict.fromkeys(FIELDS, 0)


def lines(path):
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                print(f"warning: {path}:{n}: {error.msg}", file=sys.stderr)
                continue
            if isinstance(value, dict):
                yield value


def short(value, limit=160):
    if isinstance(value, list):
        value = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in value)
    if isinstance(value, dict):
        value = value.get("text", "")
    value = " ".join(str(value or "").split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def parse_timestamp(value):
    """ISO-8601 like 2026-07-16T19:23:21.369Z; seconds precision is enough."""
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def task_from_log(path):
    for event in lines(path):
        message = event.get("message")
        if event.get("type") == "user" and isinstance(message, dict):
            task = short(message.get("content"))
            if task:
                return task
    return "(no task summary available)"


def parse_log(path, kind, identifier, task):
    models = defaultdict(zero)
    seen, records, duplicates, last_context, raw_outputs = set(), 0, 0, {}, defaultdict(int)
    max_context = defaultdict(int)
    for event in lines(path):
        message = event.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        model = str(message.get("model") or "modelo-desconocido")
        raw_outputs[model] += int(usage.get("output_tokens") or 0)
        # A persisted stream may write several event UUIDs for one API response.
        # Anthropic's message.id identifies that response; fall back to event UUID.
        identity = message.get("id") or event.get("uuid")
        if isinstance(identity, str) and identity in seen:
            duplicates += 1
            continue
        if isinstance(identity, str):
            seen.add(identity)
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        creation = usage.get("cache_creation") or {}
        five = int(creation.get("ephemeral_5m_input_tokens") or 0)
        hour = int(creation.get("ephemeral_1h_input_tokens") or 0)
        # Undifferentiated legacy cache writes are assumed to be the API default: 5m.
        five += max(0, int(usage.get("cache_creation_input_tokens") or 0) - five - hour)
        if not any((input_tokens, output_tokens, cache_read, five, hour)):
            continue
        tokens = models[model]
        tokens["input"] += input_tokens
        tokens["output"] += output_tokens
        tokens["cache_read"] += cache_read
        tokens["cache_write_5m"] += five
        tokens["cache_write_1h"] += hour
        context_tokens = input_tokens + cache_read + five + hour
        max_context[model] = max(max_context[model], context_tokens)
        last_context[model] = {
            "model": model, "input_tokens": input_tokens, "cache_read_tokens": cache_read,
            "cache_write_tokens": five + hour,
            "context_tokens": context_tokens,
            "last_output_tokens": output_tokens,
        }
        records += 1
    for model, snapshot in last_context.items():
        snapshot["observed_max_context_tokens"] = max_context[model]
    return {"id": identifier, "kind": kind, "task": task, "source": str(path),
            "records": records, "skipped_duplicates": duplicates, "models": dict(models),
            "context_snapshot": list(last_context.values()), "raw_output_tokens": dict(raw_outputs)}


def conversation_sources(main):
    """("main", main) followed by (subagent id, path) for each subagent log, sorted by path."""
    folder = main.parent / main.stem / "subagents"
    subagents = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    return [("main", main)] + [(path.stem.removeprefix("agent-"), path) for path in subagents]


def subagent_task(path):
    description = ""
    try:
        description = short(json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8")).get("description"))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return description or task_from_log(path)


def discover(main, parse=parse_log):
    _, *subagents = conversation_sources(main)
    main_conversation = parse(main, "main", "main", task_from_log(main))
    result = [parse(path, "subagent", identifier, subagent_task(path)) for identifier, path in subagents]
    return result + [main_conversation]


def tool_uses(message, seen):
    """tool_use blocks of a message whose id is not in seen (which is updated); blocks without an id always count."""
    content = message.get("content")
    for block in content if isinstance(content, list) else []:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
            continue
        identity = block.get("id")
        if isinstance(identity, str):
            if identity in seen:
                continue
            seen.add(identity)
        yield block


def file_stats(path):
    """Token totals plus tool/skill/time metrics of one log; pure, so the result can be cached per file."""
    models, daily_models, seen, seen_tools = defaultdict(zero), defaultdict(lambda: defaultdict(zero)), set(), set()
    tools, skills, responses, window = Counter(), Counter(), Counter(), None
    for event in lines(path):
        stamp = parse_timestamp(event.get("timestamp"))
        if stamp:
            window = [min(window[0], stamp), max(window[1], stamp)] if window else [stamp, stamp]
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        # Tool calls are counted before the message.id dedup: each event of a response carries other blocks.
        for block in tool_uses(message, seen_tools):
            name = str(block.get("name") or "unknown")
            tools[name] += 1
            if name == "Skill" and isinstance(block.get("input"), dict):
                skill = block["input"].get("skill")
                if skill:
                    skills[str(skill)] += 1
        day = stamp.strftime("%Y-%m-%d") if stamp else None
        if event.get("type") == "assistant":
            identity = message.get("id") or event.get("uuid")
            if isinstance(identity, str):
                if identity in seen:
                    continue
                seen.add(identity)
            if day:
                responses[day] += 1
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        model = str(message.get("model") or "modelo-desconocido")
        creation = usage.get("cache_creation") or {}
        five = int(creation.get("ephemeral_5m_input_tokens") or 0)
        hour = int(creation.get("ephemeral_1h_input_tokens") or 0)
        five += max(0, int(usage.get("cache_creation_input_tokens") or 0) - five - hour)
        record = {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0),
                  "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                  "cache_write_5m": five, "cache_write_1h": hour}
        for tokens in (models[model], daily_models[day][model]):
            for field in FIELDS:
                tokens[field] += record[field]
    return {"models": dict(models), "tools": tools, "skills": skills, "window": window, "responses": responses,
            "daily_models": {day: dict(by_model) for day, by_model in daily_models.items()}}
