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

from ctokens.logs import FIELDS, accumulate_file, discover, lines, short, zero
from ctokens.pricing import estimated_cost, load_prices, rate_of


# The JSONL never records the context window a session ran with (200k is the
# default; 1M needs a beta flag), so we infer the smallest standard tier that
# fits the largest context actually observed. This avoids reporting a 200k
# session as if it were 1M. Override with --context-window when you know it.
CONTEXT_TIERS = (200_000, 1_000_000)


def infer_context_window(observed_max, override=None):
    if override:
        return override
    if not observed_max:
        return None
    for tier in CONTEXT_TIERS:
        if observed_max <= tier:
            return tier
    return CONTEXT_TIERS[-1]


def report(conversations, prices, cold_summary_output, context_window=None):
    totals, raw_outputs, unknown, guessed = defaultdict(zero), defaultdict(int), set(), set()
    for conversation in conversations:
        conversation["estimated_cost_usd"] = 0
        for model, tokens in conversation["models"].items():
            tokens["total_tokens"] = sum(tokens.values())
            rate = rate_of(prices, model)
            tokens["price_estimated"] = bool(rate and rate[2])
            if tokens["price_estimated"]:
                guessed.add(model)
            tokens["estimated_cost_usd"] = estimated_cost(tokens, rate)
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
        rate = rate_of(prices, model)
        tokens["price_estimated"] = bool(rate and rate[2])
        tokens["estimated_cost_usd"] = estimated_cost(tokens, rate)
        by_model.append({"model": model, **tokens, "raw_output_tokens": raw_outputs[model]})
    main = next(row for row in conversations if row["kind"] == "main")
    for snapshot in main["context_snapshot"]:
        snapshot["context_window_tokens"] = infer_context_window(
            snapshot.get("observed_max_context_tokens"), context_window)
    cold_summaries = []
    for snapshot in main["context_snapshot"]:
        rate = rate_of(prices, snapshot["model"])
        cold_cost = None if rate is None else (snapshot["context_tokens"] * rate[0] + cold_summary_output * rate[1]) / 1_000_000
        cold_summaries.append({**snapshot, "assumed_summary_output_tokens": cold_summary_output,
                               "price_estimated": bool(rate and rate[2]),
                               "estimated_cold_summary_cost_usd": cold_cost})
    return {"conversations": conversations, "by_model": by_model, "main_context_snapshot": main["context_snapshot"],
            "cold_summary_estimate": cold_summaries,
            "estimated_total_cost_usd": sum(x["estimated_cost_usd"] or 0 for x in by_model),
            "unknown_price_models": sorted(unknown),
            "guessed_price_models": sorted(guessed)}


def fmt(number):
    return f"{number:,}".replace(",", ".")


def money(amount, estimated=False, digits=4):
    """Costs priced from a family fallback are prefixed with ~."""
    if amount is None:
        return "N/D"
    return f"{'~' if estimated else ''}${amount:.{digits}f}"


def guessed_notice(models):
    return ("~ estimated price: no published rate for " + ", ".join(models) + "; priced from the "
            "newest known model of the same family. Use --pricing to set the real rate.")


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
            price = money(item["estimated_cost_usd"], item.get("price_estimated"))
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
        price = money(row["estimated_cost_usd"], row.get("price_estimated"))
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
    print("  Window is inferred from the largest context seen (200k/1M tier); pass --context-window to set it.")
    print("\nCold-summary estimate (without cache)")
    summary_rows = []
    for row in data["cold_summary_estimate"]:
        price = money(row["estimated_cold_summary_cost_usd"], row.get("price_estimated"))
        summary_rows.append([row["model"], fmt(row["context_tokens"]), fmt(row["assumed_summary_output_tokens"]), price])
    table(["Model", "Cold input", "Assumed output", "Cost"], summary_rows)
    print(f"\nEstimated cost: ${data['estimated_total_cost_usd']:.4f}")
    if data["unknown_price_models"]:
        print("Models without pricing: " + ", ".join(data["unknown_price_models"]))
    if data.get("guessed_price_models"):
        print(guessed_notice(data["guessed_price_models"]))


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
        rows.append([index + 1, when, row["path"].stem, f"{row['size_kb']:,.0f}".replace(",", "."),
                     row["subagents"], row["project"], short(row["title"], 50)])
    table(["#", "Date", "GUID", "Size KB", "Subagents", "Project", "Title"], rows)


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
    by_model, total_cost, total_tokens, unknown, guessed = [], 0.0, 0, set(), set()
    for model, tokens in scan["models"].items():
        tokens["total_tokens"] = sum(tokens[field] for field in FIELDS)
        if not tokens["total_tokens"]:
            continue
        rate = rate_of(prices, model)
        tokens["price_estimated"] = bool(rate and rate[2])
        if tokens["price_estimated"]:
            guessed.add(model)
        tokens["estimated_cost_usd"] = estimated_cost(tokens, rate)
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
        "unknown_price_models": sorted(unknown),
        "guessed_price_models": sorted(guessed)}


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
        cost = money(row["estimated_cost_usd"], row.get("price_estimated"), digits=2)
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
    if data.get("guessed_price_models"):
        print("\n" + guessed_notice(data["guessed_price_models"]))


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


# Minimal Markdown → ANSI so a saved response reads on the terminal the way it
# was written: inline `code` and **bold** stand out, headings are highlighted.
ANSI = {"reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "cyan": "\033[36m"}


def render_markdown(source, color=True):
    if not color:
        return source
    def wrap(codes, body):
        return "".join(ANSI[c] for c in codes) + body + ANSI["reset"]
    import re
    out = []
    for line in source.splitlines():
        stripped = line.lstrip()
        heading = re.match(r"(#{1,6})\s+(.*)", stripped)
        if heading:
            line = wrap(["bold", "cyan"], heading.group(2))
        else:
            line = re.sub(r"`([^`]+)`", lambda m: wrap(["cyan"], m.group(1)), line)
            line = re.sub(r"\*\*([^*]+)\*\*", lambda m: wrap(["bold"], m.group(1)), line)
            line = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: wrap(["bold"], m.group(1)), line)
        out.append(line)
    return "\n".join(out)


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


def show_last_response(path, as_json):
    body = last_response(path)
    if as_json:
        print(json.dumps({"last_response": body}, ensure_ascii=False, indent=2))
    elif not body:
        print("(no assistant text response found)", file=sys.stderr)
    else:
        print(render_markdown(body, color=sys.stdout.isatty()))


def show_bash_commands(path, as_json):
    commands = bash_commands(path)
    if as_json:
        print(json.dumps({"bash_commands": commands}, ensure_ascii=False, indent=2))
        return
    if not commands:
        print("(no Bash commands run)", file=sys.stderr)
        return
    for index, entry in enumerate(commands, 1):
        if entry["description"]:
            print(f"{ANSI['dim'] if sys.stdout.isatty() else ''}# {entry['description']}"
                  f"{ANSI['reset'] if sys.stdout.isatty() else ''}")
        print(f"$ {entry['command']}\n")
    print(f"{fmt(len(commands))} Bash command(s).")


def show_touched_files(path, as_json):
    files = touched_files(path)
    if as_json:
        print(json.dumps({"files": {name: dict(tools) for name, tools in files.items()}},
                         ensure_ascii=False, indent=2))
        return
    if not files:
        print("(no files read, written or edited)", file=sys.stderr)
        return
    rows = []
    for name in sorted(files):
        tools = files[name]
        rows.append([name, fmt(tools.get("Read", 0)), fmt(tools.get("Write", 0)), fmt(tools.get("Edit", 0))])
    table(["File", "Read", "Write", "Edit"], rows)
    print(f"\n{fmt(len(files))} distinct file(s).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("conversation", type=Path, nargs="?",
                        help="conversation JSONL path or a bare conversation id (its filename "
                             "stem); if omitted, pick from the projects folder")
    parser.add_argument("--projects-dir", type=Path, default=default_projects_dir(),
                        help="Claude projects folder to browse when no conversation is given")
    parser.add_argument("--project", help="only list/aggregate conversations whose project path matches this substring")
    parser.add_argument("--totals", action="store_true",
                        help="aggregate usage across the whole projects folder instead of a single conversation")
    parser.add_argument("--pricing", type=Path, help="USD/MTok pricing JSON that overrides built-in rates")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument("--cold-summary-output", type=int, default=2000, help="assumed output tokens for the cold summary (default: 2000)")
    parser.add_argument("--context-window", type=int, help="context window in tokens for percentages (default: inferred from usage)")
    parser.add_argument("--last-response", action="store_true", help="print the last assistant response instead of the usage report")
    parser.add_argument("--bash", action="store_true", help="print every Bash command the conversation ran")
    parser.add_argument("--files", action="store_true", help="print the files read or written by the conversation")
    args = parser.parse_args()
    if args.context_window is not None and args.context_window <= 0:
        parser.error("--context-window must be positive")
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
    else:
        resolved, matches = resolve_conversation(args.conversation, args.projects_dir)
        if resolved is None:
            if len(matches) > 1:
                parser.error("ambiguous id, matches:\n  " + "\n  ".join(str(m) for m in matches))
            parser.error(f"does not exist: {args.conversation}")
        args.conversation = resolved
    if not args.conversation.is_file():
        parser.error(f"does not exist: {args.conversation}")
    if args.last_response or args.bash or args.files:
        if args.last_response:
            show_last_response(args.conversation, args.json)
        if args.bash:
            show_bash_commands(args.conversation, args.json)
        if args.files:
            show_touched_files(args.conversation, args.json)
        return
    try:
        if args.cold_summary_output < 0:
            parser.error("--cold-summary-output must be non-negative")
        data = report(discover(args.conversation), load_prices(args.pricing),
                      args.cold_summary_output, args.context_window)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        text(data)


if __name__ == "__main__":
    main()
