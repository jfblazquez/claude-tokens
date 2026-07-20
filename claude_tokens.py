#!/usr/bin/env python3
"""Summarize a Claude Code JSONL conversation and its subagents."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# USD per million tokens. See README for source and overrides.
PRICES = {
    "claude-fable-5": (10, 50), "claude-mythos-5": (10, 50),
    "claude-opus-4-8": (5, 25), "claude-opus-4-7": (5, 25),
    "claude-opus-4-6": (5, 25), "claude-opus-4-5": (5, 25),
    "claude-opus-4-1": (15, 75), "claude-opus-4": (15, 75),
    "claude-sonnet-5": (2, 10), "claude-sonnet-4-6": (3, 15),
    "claude-sonnet-4-5": (3, 15), "claude-sonnet-4": (3, 15),
    "claude-haiku-4-5": (1, 5), "claude-haiku-3-5": (.8, 4),
}
FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
CONTEXT_WINDOWS = {"claude-fable-5": 1_000_000, "claude-mythos-5": 1_000_000,
                   "claude-opus-4-8": 1_000_000, "claude-opus-4-7": 1_000_000,
                   "claude-opus-4-6": 1_000_000, "claude-sonnet-5": 1_000_000,
                   "claude-sonnet-4-6": 1_000_000}


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
        last_context[model] = {
            "model": model, "input_tokens": input_tokens, "cache_read_tokens": cache_read,
            "cache_write_tokens": five + hour,
            "context_tokens": input_tokens + cache_read + five + hour,
            "last_output_tokens": output_tokens,
            "context_window_tokens": CONTEXT_WINDOWS.get(model),
        }
        records += 1
    return {"id": identifier, "kind": kind, "task": task, "source": str(path),
            "records": records, "skipped_duplicates": duplicates, "models": dict(models),
            "context_snapshot": list(last_context.values()), "raw_output_tokens": dict(raw_outputs)}


def discover(main):
    main_conversation = parse_log(main, "main", "main", task_from_log(main))
    result = []
    folder = main.parent / main.stem / "subagents"
    if not folder.is_dir():
        return [main_conversation]
    for path in sorted(folder.glob("*.jsonl")):
        description = ""
        metadata = path.with_suffix(".meta.json")
        try:
            description = short(json.loads(metadata.read_text(encoding="utf-8")).get("description"))
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        result.append(parse_log(path, "subagent", path.stem.removeprefix("agent-"), description or task_from_log(path)))
    return result + [main_conversation]


def load_prices(path):
    prices = PRICES.copy()
    if not path:
        return prices
    try:
        custom = json.loads(path.read_text(encoding="utf-8"))
        for model, value in custom.items():
            prices[model] = (float(value["input"]), float(value["output"]))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"archivo de precios inválido: {error}") from error
    return prices


def rate_of(prices, model):
    """Look up a model rate, tolerating a trailing -YYYYMMDD release date."""
    if model in prices:
        return prices[model]
    head, _, tail = model.rpartition("-")
    return prices.get(head) if tail.isdigit() and len(tail) == 8 else None


def estimated_cost(tokens, rate):
    if rate is None:
        return None
    input_rate, output_rate = rate
    billable_input = tokens["input"] + .1 * tokens["cache_read"] + 1.25 * tokens["cache_write_5m"] + 2 * tokens["cache_write_1h"]
    return (billable_input * input_rate + tokens["output"] * output_rate) / 1_000_000


def report(conversations, prices, cold_summary_output):
    totals, raw_outputs, unknown = defaultdict(zero), defaultdict(int), set()
    for conversation in conversations:
        conversation["estimated_cost_usd"] = 0
        for model, tokens in conversation["models"].items():
            tokens["total_tokens"] = sum(tokens.values())
            tokens["estimated_cost_usd"] = estimated_cost(tokens, rate_of(prices, model))
            if tokens["estimated_cost_usd"] is None:
                unknown.add(model)
                conversation["estimated_cost_usd"] = None
            elif conversation["estimated_cost_usd"] is not None:
                conversation["estimated_cost_usd"] += tokens["estimated_cost_usd"]
            for field in FIELDS:
                totals[model][field] += tokens[field]
        for model, amount in conversation["raw_output_tokens"].items():
            raw_outputs[model] += amount
    by_model = []
    for model, tokens in sorted(totals.items()):
        tokens["total_tokens"] = sum(tokens.values())
        tokens["estimated_cost_usd"] = estimated_cost(tokens, rate_of(prices, model))
        by_model.append({"model": model, **tokens, "raw_output_tokens": raw_outputs[model]})
    main = next(row for row in conversations if row["kind"] == "main")
    cold_summaries = []
    for snapshot in main["context_snapshot"]:
        rate = rate_of(prices, snapshot["model"])
        cold_cost = None if rate is None else (snapshot["context_tokens"] * rate[0] + cold_summary_output * rate[1]) / 1_000_000
        cold_summaries.append({**snapshot, "assumed_summary_output_tokens": cold_summary_output,
                               "estimated_cold_summary_cost_usd": cold_cost})
    return {"conversations": conversations, "by_model": by_model, "main_context_snapshot": main["context_snapshot"],
            "cold_summary_estimate": cold_summaries,
            "estimated_total_cost_usd": sum(x["estimated_cost_usd"] or 0 for x in by_model),
            "unknown_price_models": sorted(unknown)}


def fmt(number):
    return f"{number:,}".replace(",", ".")


def table(headers, rows):
    """Print a simple dependency-free text table."""
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    separator = "+".join("-" * (width + 2) for width in widths)
    render = lambda row: "|".join(f" {cell:<{widths[index]}} " for index, cell in enumerate(row))
    print(render(headers))
    print(separator)
    for row in rows:
        print(render(row))


def text(data):
    conversation_rows = []
    for row in data["conversations"]:
        for model, item in sorted(row["models"].items()):
            price = "N/D" if item["estimated_cost_usd"] is None else f"${item['estimated_cost_usd']:.4f}"
            conversation_rows.append([
                row["kind"], row["id"], short(row["task"], 48), model, fmt(item["total_tokens"]),
                fmt(item["input"]), fmt(item["output"]), fmt(item["cache_read"]),
                f"{fmt(item['cache_write_5m'])}/{fmt(item['cache_write_1h'])}", price,
            ])
    print("Conversation usage")
    table(["Scope", "ID", "Task", "Model", "Total", "Input", "Output", "Cache read", "Cache write 5m/1h", "Cost"], conversation_rows)
    duplicates = ", ".join(f"{row['id']}={row['skipped_duplicates']}" for row in data["conversations"] if row["skipped_duplicates"])
    print("\nDuplicates skipped: " + (duplicates or "none"))

    print("\nSummary by model")
    model_rows = []
    for row in data["by_model"]:
        price = "N/D" if row["estimated_cost_usd"] is None else f"${row['estimated_cost_usd']:.4f}"
        raw = "" if row["raw_output_tokens"] == row["output"] else fmt(row["raw_output_tokens"])
        model_rows.append([row["model"], fmt(row["total_tokens"]), fmt(row["input"]), fmt(row["output"]), raw,
                           fmt(row["cache_read"]), f"{fmt(row['cache_write_5m'])}/{fmt(row['cache_write_1h'])}", price])
    table(["Model", "Total", "Input", "Output", "Raw output*", "Cache read", "Cache write 5m/1h", "Cost"], model_rows)
    print("* Raw output is shown only when persisted stream events differ from de-duplicated API responses.")

    print("\nLast observed context (main conversation)")
    context_rows = []
    for row in data["main_context_snapshot"]:
        window = row["context_window_tokens"]
        percent = "N/D" if not window else f"{row['context_tokens'] / window:.1%}"
        maximum = "N/D" if not window else fmt(window)
        context_rows.append([row["model"], f"{fmt(row['context_tokens'])}/{maximum}", percent, fmt(row["input_tokens"]),
                             fmt(row["cache_read_tokens"]), fmt(row["cache_write_tokens"]), fmt(row["last_output_tokens"])])
    table(["Model", "Context/window", "Used", "New input", "Cache read", "Cache write", "Last output"], context_rows)
    print("  System prompt/tools/memory/skills/messages categories are not broken down in the JSONL.")
    print("\nCold-summary estimate (without cache)")
    summary_rows = []
    for row in data["cold_summary_estimate"]:
        price = "N/D" if row["estimated_cold_summary_cost_usd"] is None else f"${row['estimated_cold_summary_cost_usd']:.4f}"
        summary_rows.append([row["model"], fmt(row["context_tokens"]), fmt(row["assumed_summary_output_tokens"]), price])
    table(["Model", "Cold input", "Assumed output", "Cost"], summary_rows)
    print(f"\nEstimated cost: ${data['estimated_total_cost_usd']:.4f}")
    if data["unknown_price_models"]:
        print("Models without pricing: " + ", ".join(data["unknown_price_models"]))


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


def show_page(conversations, start, end):
    rows = []
    for index in range(start, end):
        row = conversations[index]
        when = datetime.fromtimestamp(row["mtime"]).strftime("%Y-%m-%d %H:%M")
        rows.append([index + 1, when, f"{row['size_kb']:,.0f}".replace(",", "."),
                     row["subagents"], row["project"], short(row["title"], 50)])
    table(["#", "Date", "Size KB", "Subagents", "Project", "Title"], rows)


def pick_conversation(projects_dir, project_filter, page_size=10):
    conversations = list_conversations(projects_dir, project_filter)
    total = len(conversations)
    if not total:
        print(f"No conversations found in {projects_dir}"
              + (f" for project matching '{project_filter}'" if project_filter else ""), file=sys.stderr)
        return None
    if not sys.stdin.isatty():
        show_page(conversations, 0, total)
        print("\nNo TTY: pass the conversation path explicitly.", file=sys.stderr)
        return None

    def select(choice):
        if choice.isdigit() and 1 <= int(choice) <= total:
            return conversations[int(choice) - 1]["path"]
        return None

    shown, all_mode = 0, False
    while shown < total:
        end = total if all_mode else min(shown + page_size, total)
        show_page(conversations, shown, end)
        shown = end
        if shown >= total:
            break
        prompt = f"\nSelect 1-{total}, Enter for next {page_size}, 'a' for all, 'q' to quit: "
        try:
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice == "":
            continue
        if choice == "a":
            all_mode = True
            continue
        if choice == "q":
            return None
        return select(choice)
    try:
        choice = input(f"\nSelect 1-{total} (Enter to cancel): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    return select(choice)


def parse_timestamp(value):
    """ISO-8601 like 2026-07-16T19:23:21.369Z; seconds precision is enough."""
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def accumulate_file(path, tools, skills, window, daily):
    """Collect per-file token totals plus tool/skill/time metrics."""
    models, seen = defaultdict(zero), set()
    for event in lines(path):
        stamp = parse_timestamp(event.get("timestamp"))
        if stamp:
            window[0] = stamp if window[0] is None or stamp < window[0] else window[0]
            window[1] = stamp if window[1] is None or stamp > window[1] else window[1]
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        if event.get("type") == "assistant":
            identity = message.get("id") or event.get("uuid")
            if isinstance(identity, str):
                if identity in seen:
                    continue
                seen.add(identity)
            if stamp:
                daily[stamp.strftime("%Y-%m-%d")] += 1
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name") or "unknown")
                    tools[name] += 1
                    if name == "Skill" and isinstance(block.get("input"), dict):
                        skill = block["input"].get("skill")
                        if skill:
                            skills[str(skill)] += 1
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        model = str(message.get("model") or "modelo-desconocido")
        creation = usage.get("cache_creation") or {}
        five = int(creation.get("ephemeral_5m_input_tokens") or 0)
        hour = int(creation.get("ephemeral_1h_input_tokens") or 0)
        five += max(0, int(usage.get("cache_creation_input_tokens") or 0) - five - hour)
        tokens = models[model]
        tokens["input"] += int(usage.get("input_tokens") or 0)
        tokens["output"] += int(usage.get("output_tokens") or 0)
        tokens["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
        tokens["cache_write_5m"] += five
        tokens["cache_write_1h"] += hour
    return models


def scan_totals(projects_dir, project_filter=None):
    """One pass over every session (and its subagents) in the projects folder."""
    models = defaultdict(zero)
    project_models = defaultdict(lambda: defaultdict(zero))
    tools, skills, daily, project_convs = Counter(), Counter(), Counter(), Counter()
    window, conversations, subagents = [None, None], 0, 0
    for project in sorted(projects_dir.iterdir()) if projects_dir.is_dir() else []:
        if not project.is_dir():
            continue
        for path in sorted(project.glob("*.jsonl")):
            cwd = project_path_of(path)
            if project_filter and project_filter.lower() not in cwd.lower():
                continue
            conversations += 1
            project_convs[cwd] += 1
            files = [path]
            folder = path.parent / path.stem / "subagents"
            if folder.is_dir():
                subs = sorted(folder.glob("*.jsonl"))
                subagents += len(subs)
                files += subs
            for source in files:
                for model, tokens in accumulate_file(source, tools, skills, window, daily).items():
                    for field in FIELDS:
                        models[model][field] += tokens[field]
                        project_models[cwd][model][field] += tokens[field]
    return {"models": dict(models), "project_models": {k: dict(v) for k, v in project_models.items()},
            "tools": dict(tools), "skills": dict(skills), "daily": dict(daily),
            "project_convs": dict(project_convs), "window": window,
            "conversations": conversations, "subagents": subagents}


def totals_report(scan, prices):
    """Turn a raw scan into cost/percentage figures ready to print or dump."""
    by_model, total_cost, total_tokens, unknown = [], 0.0, 0, set()
    for model, tokens in scan["models"].items():
        tokens["total_tokens"] = sum(tokens[field] for field in FIELDS)
        if not tokens["total_tokens"]:
            continue
        tokens["estimated_cost_usd"] = estimated_cost(tokens, rate_of(prices, model))
        total_tokens += tokens["total_tokens"]
        if tokens["estimated_cost_usd"] is None:
            unknown.add(model)
        else:
            total_cost += tokens["estimated_cost_usd"]
        by_model.append({"model": model, **tokens})
    for row in by_model:
        row["pct_tokens"] = row["total_tokens"] / total_tokens if total_tokens else 0
        row["pct_cost"] = (row["estimated_cost_usd"] / total_cost
                           if total_cost and row["estimated_cost_usd"] is not None else None)
    by_model.sort(key=lambda row: row["estimated_cost_usd"] or 0, reverse=True)

    projects = []
    for cwd, models in scan["project_models"].items():
        cost = sum(estimated_cost(t, rate_of(prices, m)) or 0 for m, t in models.items())
        tokens = sum(sum(t[field] for field in FIELDS) for t in models.values())
        projects.append({"project": cwd, "conversations": scan["project_convs"].get(cwd, 0),
                         "total_tokens": tokens, "estimated_cost_usd": cost})
    projects.sort(key=lambda row: row["estimated_cost_usd"], reverse=True)

    tool_total = sum(scan["tools"].values())
    start, end = scan["window"]
    span_days = (end - start).days + 1 if start and end else 0
    cache_read = sum(t["cache_read"] for t in scan["models"].values())
    cache_write = sum(t["cache_write_5m"] + t["cache_write_1h"] for t in scan["models"].values())
    fresh_input = sum(t["input"] for t in scan["models"].values())
    context_input = cache_read + cache_write + fresh_input
    busiest = max(scan["daily"].items(), key=lambda kv: kv[1]) if scan["daily"] else None
    return {
        "window": {"start": start.isoformat(sep=" ") if start else None,
                   "end": end.isoformat(sep=" ") if end else None,
                   "span_days": span_days, "active_days": len(scan["daily"]),
                   "busiest_day": busiest[0] if busiest else None,
                   "busiest_day_responses": busiest[1] if busiest else 0},
        "conversations": scan["conversations"], "subagents": scan["subagents"],
        "projects_count": len(scan["project_convs"]), "total_tokens": total_tokens,
        "output_tokens": sum(t["output"] for t in scan["models"].values()),
        "estimated_total_cost_usd": total_cost,
        "cost_per_conversation_usd": total_cost / scan["conversations"] if scan["conversations"] else 0,
        "cache_hit_ratio": cache_read / context_input if context_input else 0,
        "by_model": by_model, "projects": projects,
        "tools": scan["tools"], "tool_calls": tool_total, "skills": scan["skills"],
        "unknown_price_models": sorted(unknown)}


def totals_text(data, top=15):
    window = data["window"]
    print("Overall usage (projects folder)")
    if window["start"]:
        print(f"  Time window : {window['span_days']} days ({window['start'][:10]} → {window['end'][:10]}), "
              f"{window['active_days']} active days")
        print(f"  Busiest day : {window['busiest_day']} ({fmt(window['busiest_day_responses'])} responses)")
    print(f"  Volume      : {fmt(data['conversations'])} conversations across "
          f"{fmt(data['projects_count'])} projects, {fmt(data['subagents'])} subagents")
    print(f"  Tokens      : {fmt(data['total_tokens'])} total, {fmt(data['output_tokens'])} generated (output)")
    print(f"  Cache hits  : {data['cache_hit_ratio']:.1%} of input tokens served from cache")
    print(f"  Total cost  : ${data['estimated_total_cost_usd']:.2f} "
          f"(${data['cost_per_conversation_usd']:.4f} per conversation)")

    print("\nUsage by model")
    rows = []
    for row in data["by_model"]:
        cost = "N/D" if row["estimated_cost_usd"] is None else f"${row['estimated_cost_usd']:.2f}"
        pct_cost = "N/D" if row["pct_cost"] is None else f"{row['pct_cost']:.1%}"
        rows.append([row["model"], fmt(row["total_tokens"]), f"{row['pct_tokens']:.1%}", cost, pct_cost])
    table(["Model", "Total tokens", "% tokens", "Cost", "% cost"], rows)

    print("\nTop tools")
    rows = []
    for name, count in sorted(data["tools"].items(), key=lambda kv: kv[1], reverse=True)[:top]:
        share = count / data["tool_calls"] if data["tool_calls"] else 0
        rows.append([name, fmt(count), f"{share:.1%}"])
    table(["Tool", "Calls", "% of calls"], rows)

    print("\nSkills used")
    if data["skills"]:
        rows = [[name, fmt(count)] for name, count in sorted(data["skills"].items(), key=lambda kv: kv[1], reverse=True)]
        table(["Skill", "Invocations"], rows)
    else:
        print("  (none)")

    print("\nTop projects by cost")
    rows = []
    for row in sorted(data["projects"], key=lambda r: r["estimated_cost_usd"], reverse=True)[:top]:
        rows.append([row["project"], fmt(row["conversations"]), fmt(row["total_tokens"]),
                     f"${row['estimated_cost_usd']:.2f}"])
    table(["Project", "Conversations", "Total tokens", "Cost"], rows)

    if data["unknown_price_models"]:
        print("\nModels without pricing: " + ", ".join(data["unknown_price_models"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("conversation", type=Path, nargs="?",
                        help="main conversation JSONL; if omitted, pick from the projects folder")
    parser.add_argument("--projects-dir", type=Path, default=default_projects_dir(),
                        help="Claude projects folder to browse when no conversation is given")
    parser.add_argument("--project", help="only list/aggregate conversations whose project path matches this substring")
    parser.add_argument("--totals", action="store_true",
                        help="aggregate usage across the whole projects folder instead of a single conversation")
    parser.add_argument("--pricing", type=Path, help="USD/MTok pricing JSON that overrides built-in rates")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument("--cold-summary-output", type=int, default=2000, help="assumed output tokens for the cold summary (default: 2000)")
    args = parser.parse_args()
    if args.totals:
        try:
            data = totals_report(scan_totals(args.projects_dir, args.project), load_prices(args.pricing))
        except ValueError as error:
            parser.error(str(error))
        if not data["conversations"]:
            parser.error(f"no conversations found in {args.projects_dir}")
        print(json.dumps(data, ensure_ascii=False, indent=2)) if args.json else totals_text(data)
        return
    if args.conversation is None:
        args.conversation = pick_conversation(args.projects_dir, args.project)
        if args.conversation is None:
            return
    if not args.conversation.is_file():
        parser.error(f"does not exist: {args.conversation}")
    try:
        if args.cold_summary_output < 0:
            parser.error("--cold-summary-output must be non-negative")
        data = report(discover(args.conversation), load_prices(args.pricing), args.cold_summary_output)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        text(data)


if __name__ == "__main__":
    main()
