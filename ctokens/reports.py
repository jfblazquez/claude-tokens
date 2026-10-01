"""Usage report of one conversation and totals across the projects folder."""
from __future__ import annotations

from collections import Counter, defaultdict

from .catalog import project_path_of
from .logs import FIELDS, conversation_sources, file_stats, zero
from .pricing import estimated_cost, rate_of


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


def scan_totals(projects_dir, project_filter=None, stats=file_stats):
    """One pass over every session (and its subagents) in the projects folder; stats(path) reads one log."""
    models = defaultdict(zero)
    project_models = defaultdict(lambda: defaultdict(zero))
    daily_models = defaultdict(lambda: defaultdict(zero))
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
            sources = conversation_sources(path)
            subagents += len(sources) - 1
            for _, source in sources:
                result = stats(source)
                for model, tokens in result["models"].items():
                    for field in FIELDS:
                        models[model][field] += tokens[field]
                        project_models[cwd][model][field] += tokens[field]
                for day, by_model in result["daily_models"].items():
                    for model, tokens in by_model.items():
                        for field in FIELDS:
                            daily_models[day][model][field] += tokens[field]
                tools.update(result["tools"])
                skills.update(result["skills"])
                daily.update(result["responses"])
                if result["window"]:
                    first, last = result["window"]
                    window = [first if window[0] is None else min(window[0], first),
                              last if window[1] is None else max(window[1], last)]
    return {"models": dict(models), "project_models": {k: dict(v) for k, v in project_models.items()},
            "tools": dict(tools), "skills": dict(skills), "daily": dict(daily),
            "daily_models": {k: dict(v) for k, v in daily_models.items()},
            "project_convs": dict(project_convs), "window": window,
            "conversations": conversations, "subagents": subagents}


def daily_series(daily_models, responses, prices):
    """Tokens and cost per Day and model, days ascending; records without a timestamp go last under day None."""
    series = []
    for day in sorted(set(daily_models) | set(responses), key=lambda d: (d is None, d or "")):
        models, day_tokens, day_cost = {}, 0, 0.0
        for model, tokens in sorted(daily_models.get(day, {}).items()):
            row = {field: tokens[field] for field in FIELDS}
            row["total_tokens"] = sum(row.values())
            if not row["total_tokens"]:
                continue
            row["estimated_cost_usd"] = estimated_cost(row, rate_of(prices, model))
            day_tokens += row["total_tokens"]
            day_cost += row["estimated_cost_usd"] or 0
            models[model] = row
        if models or responses.get(day):
            series.append({"day": day, "responses": responses.get(day, 0), "total_tokens": day_tokens,
                           "estimated_cost_usd": day_cost, "models": models})
    return series


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
        "guessed_price_models": sorted(guessed),
        "daily": daily_series(scan["daily_models"], scan["daily"], prices)}
