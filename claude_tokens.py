#!/usr/bin/env python3
"""Summarize a Claude Code JSONL conversation and its subagents."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from ctokens.catalog import default_projects_dir, list_conversations, resolve_conversation
from ctokens.logs import discover, lines, short
from ctokens.pricing import load_prices
from ctokens.reports import report, scan_totals, totals_report


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
