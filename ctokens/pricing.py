"""Model prices and cost estimation."""
from __future__ import annotations

import json


# USD per million tokens, plus an optional cache-read multiplier (default 0.1x).
# See README for source and overrides.
PRICES = {
    "claude-fable-5-1": (10, 50, .025), "claude-mythos-5-1": (10, 50, .025),
    "claude-fable-5": (10, 50), "claude-mythos-5": (10, 50),
    "claude-mythos-preview": (10, 50),
    "claude-opus-5-5": (4, 20, .05),
    "claude-opus-5": (5, 25),
    "claude-opus-4-8": (5, 25), "claude-opus-4-7": (5, 25),
    "claude-opus-4-6": (5, 25), "claude-opus-4-5": (5, 25),
    "claude-opus-4-1": (15, 75), "claude-opus-4": (15, 75),
    "claude-3-opus": (15, 75),
    "claude-sonnet-5-5": (2, 10),
    "claude-sonnet-5": (2, 10), "claude-sonnet-4-6": (3, 15),
    "claude-sonnet-4-5": (3, 15), "claude-sonnet-4": (3, 15),
    "claude-3-7-sonnet": (3, 15), "claude-3-5-sonnet": (3, 15),
    "claude-haiku-4-5": (1, 5),
    "claude-haiku-3-5": (.8, 4), "claude-3-5-haiku": (.8, 4),
    "claude-3-haiku": (.25, 1.25),
}


# Known model families. Used to price unreleased versions (opus-6, fable-5-2,
# ...) from the newest known sibling of the same family.
FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku")


def load_prices(path):
    prices = PRICES.copy()
    if not path:
        return prices
    try:
        custom = json.loads(path.read_text(encoding="utf-8"))
        for model, value in custom.items():
            rate = (float(value["input"]), float(value["output"]))
            prices[model] = rate + (float(value["cache_read"]),) if "cache_read" in value else rate
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"archivo de precios inválido: {error}") from error
    return prices


def parse_model(model):
    """(family, version tuple) for a model id, or None when unrecognised.

    Handles both id styles: claude-opus-4-8 and claude-3-5-sonnet-20241022.
    """
    parts = [part for part in model.split("-") if part]
    family = next((part for part in parts if part in FAMILIES), None)
    if family is None:
        return None
    return family, tuple(int(p) for p in parts if p.isdigit() and len(p) != 8)


def priced(rate, estimated):
    input_rate, output_rate, *cache_read = rate
    return input_rate, output_rate, estimated, cache_read[0] if cache_read else .1


def rate_of(prices, model):
    """(input, output, estimated, cache_read multiplier) for a model, or None when unpriceable.

    Tolerates a trailing -YYYYMMDD release date. A model that is unknown but
    belongs to a known family (claude-opus-6, claude-fable-5-2, ...) is priced
    from the closest earlier sibling and flagged as estimated.
    """
    head, _, tail = model.rpartition("-")
    base = head if tail.isdigit() and len(tail) == 8 else model
    if base in prices:
        return priced(prices[base], False)
    parsed = parse_model(base)
    if parsed is None:
        return None
    family, version = parsed
    known = [(other[1], rate) for name, rate in prices.items()
             for other in [parse_model(name)] if other and other[0] == family]
    if not known:
        return None
    earlier = [entry for entry in known if entry[0] <= version]
    _, rate = max(earlier, key=lambda e: e[0]) if earlier else min(known, key=lambda e: e[0])
    return priced(rate, True)


def estimated_cost(tokens, rate):
    if rate is None:
        return None
    input_rate, output_rate, _, cache_read = rate
    billable_input = tokens["input"] + cache_read * tokens["cache_read"] + 1.25 * tokens["cache_write_5m"] + 2 * tokens["cache_write_1h"]
    return (billable_input * input_rate + tokens["output"] * output_rate) / 1_000_000
