"""Plain-text rendering for the terminal."""
from __future__ import annotations

from datetime import datetime

from .logs import short


# Minimal Markdown → ANSI so a saved response reads on the terminal the way it
# was written: inline `code` and **bold** stand out, headings are highlighted.
ANSI = {"reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "cyan": "\033[36m"}


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


def report_text(data):
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


ROLE_LABELS = {"prompt": "user", "meta": "meta", "summary": "summary",
               "response": "assistant", "error": "api error"}


def message_preview(message):
    blocks = message["blocks"]
    texts = [b["text"] for b in blocks if b["type"] == "text"]
    if texts:
        return short(texts[0], 60)
    tools = [b["name"] for b in blocks if b["type"] == "tool_use"]
    if tools:
        return "→ " + ", ".join(tools)
    return "(thinking)"


def messages_text(data):
    rows, cost, guessed = [], 0, False
    # Tool results are shown under the call that made them in the web UI, so neither view numbers them.
    shown = [m for m in data["messages"] if m["kind"] != "tool_result"]
    for index, message in enumerate(shown, 1):
        when = (message["timestamp"] or "")[:19].replace("T", " ")
        row = [index, when, ROLE_LABELS[message["kind"]]]
        if message["role"] == "assistant":
            u = message["usage"]
            output = fmt(u["output"]) + (f" ({fmt(u['thinking'])} th)" if u["thinking"] else "")
            row += [message["model"], fmt(u["input"]), output, fmt(u["cache_read"]),
                    f"{fmt(u['cache_write_5m'])}/{fmt(u['cache_write_1h'])}", fmt(u["context"]),
                    money(message["estimated_cost_usd"], message["price_estimated"])]
            cost += message["estimated_cost_usd"] or 0
            guessed = guessed or message["price_estimated"]
        else:
            row += [""] * 7
        rows.append(row + [message_preview(message)])
    task = next((s["task"] for s in data["sources"] if s["id"] == data["source"]), "")
    print(f"Messages ({data['source']}): {task}")
    table(["#", "Time (UTC)", "Role", "Model", "Input", "Output", "Cache read", "Cache write 5m/1h", "Context", "Cost",
           "Content"], rows)
    responses = sum(m["role"] == "assistant" for m in shown)
    print(f"\n{fmt(len(rows))} message(s), {fmt(responses)} response(s). Estimated cost: {money(cost, guessed)}")


def show_page(conversations, start, end):
    rows = []
    for index in range(start, end):
        row = conversations[index]
        when = datetime.fromtimestamp(row["mtime"]).strftime("%Y-%m-%d %H:%M")
        rows.append([index + 1, when, row["path"].stem, f"{row['size_kb']:,.0f}".replace(",", "."),
                     row["subagents"], row["project"], short(row["title"], 50)])
    table(["#", "Date", "GUID", "Size KB", "Subagents", "Project", "Title"], rows)
