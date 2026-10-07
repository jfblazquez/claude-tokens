"""Summarize a Claude Code JSONL conversation and its subagents."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import default_projects_dir, list_conversations, resolve_conversation
from .content import bash_commands, last_response, touched_files
from .logs import discover
from .pricing import load_prices
from .reports import report, scan_totals, totals_report
from .text import ANSI, fmt, render_markdown, report_text, show_page, table, totals_text


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
    for entry in commands:
        comment = entry["description"]
        if entry["source"] != "main":
            comment = f"[subagent {entry['source']}] {comment}".rstrip()
        if comment:
            print(f"{ANSI['dim'] if sys.stdout.isatty() else ''}# {comment}"
                  f"{ANSI['reset'] if sys.stdout.isatty() else ''}")
        print(f"$ {entry['command']}\n")
    print(f"{fmt(len(commands))} Bash command(s).")


def show_touched_files(path, as_json):
    files = touched_files(path)
    if as_json:
        print(json.dumps({"files": files}, ensure_ascii=False, indent=2))
        return
    if not files:
        print("(no files read, written or edited)", file=sys.stderr)
        return
    rows = []
    for name in sorted(files):
        tools = files[name]
        rows.append([name, fmt(tools["Read"]), fmt(tools["Write"]), fmt(tools["Edit"]), ", ".join(tools["sources"])])
    table(["File", "Read", "Write", "Edit", "Sources"], rows)
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
    parser.add_argument("--serve", action="store_true",
                        help="start the local web server (JSON API and browser UI) on 127.0.0.1")
    parser.add_argument("--port", type=int, help="port for --serve (default: 8765)")
    args = parser.parse_args()
    if args.context_window is not None and args.context_window <= 0:
        parser.error("--context-window must be positive")
    if args.serve:
        start_server(parser, args)
    if args.port is not None:
        parser.error("--port requires --serve")
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
        report_text(data)


DEFAULT_PORT = 8765
NOT_WITH_SERVE = (("conversation", "a conversation"), ("totals", "--totals"), ("json", "--json"),
                  ("last_response", "--last-response"), ("bash", "--bash"), ("files", "--files"),
                  ("project", "--project"))


def start_server(parser, args):
    for name, label in NOT_WITH_SERVE:
        if getattr(args, name) not in (None, False):
            parser.error(f"--serve cannot be combined with {label}")
    port = DEFAULT_PORT if args.port is None else args.port
    if not 1 <= port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.cold_summary_output < 0:
        parser.error("--cold-summary-output must be non-negative")
    try:
        prices = load_prices(args.pricing)
    except ValueError as error:
        parser.error(str(error))
    from .web import Config, serve as run_server

    sys.exit(run_server(Config(args.projects_dir, prices, args.cold_summary_output, args.context_window), port))
