"""Accounting for reported observations; unknown is not zero."""

from decimal import Decimal, InvalidOperation
import math


# Cache reads and cache writes are separately reported subsets of input tokens.
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens")
COST_FIELDS = ("model_cost_usd", "tool_cost_usd")
MEASUREMENTS = (*TOKEN_FIELDS, *COST_FIELDS, "verification_cost_usd", "total_task_cost_usd")


def money(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Money must be a finite nonnegative decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Invalid decimal money") from error
    if not number.is_finite() or number < 0 or number > Decimal("1e12") or abs(number.as_tuple().exponent) > 12:
        raise ValueError("Money must be between 0 and 1e12 USD with at most 12 decimal places")
    return number


def decimal_text(value):
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def provenance(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires a nonempty provenance string")


def validate_usage(usage):
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise ValueError("usage must be an object or null")
    allowed = {*TOKEN_FIELDS, *COST_FIELDS, "usage_source", "model_cost_source", "tool_cost_source"}
    if usage.keys() - allowed:
        raise ValueError("Unrecognized usage fields")
    for key in TOKEN_FIELDS:
        value = usage.get(key)
        if value is not None and (type(value) is not int or value < 0 or value > 10**12):
            raise ValueError(f"{key} must be a nonnegative integer or null")
    if any(usage.get(key) is not None for key in TOKEN_FIELDS):
        provenance(usage.get("usage_source"), "Token usage")
    total = usage.get("input_tokens")
    subsets = [usage.get(key) for key in ("cached_input_tokens", "cache_write_input_tokens")]
    if any(value is not None for value in subsets) and (
            total is None or sum(value or 0 for value in subsets) > total):
        raise ValueError("Cache read and write tokens must be subsets of reported input tokens")
    for key in COST_FIELDS:
        if usage.get(key) is not None:
            money(usage[key])
            provenance(usage.get(key.replace("_usd", "_source")), key)
    return usage


def complete_sum(values, monetary=False):
    if not values or any(value is None for value in values):
        return None
    if monetary:
        return decimal_text(sum((money(value) for value in values), Decimal(0)))
    return sum(values)


def summarize_trial(attempts, kind, verification_cost=None):
    if kind not in ("live", "fixture"):
        raise ValueError("Unknown measurement kind")
    for attempt in attempts:
        validate_usage(attempt.get("usage"))
    result = {"attempts": len(attempts), "repair_attempts": max(0, len(attempts) - 1),
              "usage_reported_attempts": sum(a.get("usage") is not None for a in attempts)}
    result.update(dict.fromkeys(MEASUREMENTS))
    if kind != "live":
        return result
    for key in (*TOKEN_FIELDS, *COST_FIELDS):
        result[key] = complete_sum([(a.get("usage") or {}).get(key) for a in attempts],
                                   monetary=key in COST_FIELDS)
    if verification_cost is not None:
        if not isinstance(verification_cost, dict) or set(verification_cost) != {"amount_usd", "source"}:
            raise ValueError("Verification cost requires amount_usd and source")
        provenance(verification_cost["source"], "Verification cost")
        result["verification_cost_usd"] = decimal_text(money(verification_cost["amount_usd"]))
    result["total_task_cost_usd"] = complete_sum(
        [result[key] for key in (*COST_FIELDS, "verification_cost_usd")], monetary=True)
    return result


def wilson_interval(successes, total, z=1.959963984540054):
    """Two-sided 95% Wilson score interval for a binomial proportion."""
    if not total:
        return None
    rate = successes / total
    scale = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / scale
    half = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / scale
    return [max(0.0, centre - half), min(1.0, centre + half)]


def exact_mcnemar(only_first, only_second):
    """Two-sided exact McNemar p-value over discordant pairs."""
    discordant = only_first + only_second
    if not discordant:
        return None
    tail = sum(math.comb(discordant, k) for k in range(min(only_first, only_second) + 1))
    return min(1.0, 2 * tail / 2 ** discordant)


def paired_comparison(trials, first="source", second="compiler"):
    """Compare conditions on the same task and repetition.

    Pairs containing an infrastructure error are excluded and counted, so an
    outage in one condition cannot masquerade as a model difference.
    """
    by_pair = {}
    for trial in trials:
        by_pair.setdefault((trial["task"], trial["repetition"]), {})[trial["context_mode"]] = trial["status"]
    counts = {"both_passed": 0, f"only_{first}": 0, f"only_{second}": 0, "neither": 0}
    excluded = 0
    for statuses in by_pair.values():
        if set(statuses) != {first, second}:
            continue
        if "error" in statuses.values():
            excluded += 1
            continue
        a, b = statuses[first] == "passed", statuses[second] == "passed"
        counts["both_passed" if a and b else f"only_{first}" if a else f"only_{second}" if b else "neither"] += 1
    return {"conditions": [first, second], "pairs": sum(counts.values()), "excluded_error_pairs": excluded,
            **counts, "exact_mcnemar_p": exact_mcnemar(counts[f"only_{first}"], counts[f"only_{second}"])}


def aggregate(trials):
    correct = sum(t["status"] == "passed" for t in trials)
    evaluable = sum(t["status"] in ("passed", "failed") for t in trials)
    result = {"tasks": len(trials), "correct_tasks": correct,
              "failed_tasks": sum(t["status"] == "failed" for t in trials),
              "error_tasks": sum(t["status"] == "error" for t in trials),
              "correctness_rate": correct / len(trials) if trials else None,
              # Infrastructure errors say nothing about the model; report both views.
              "correctness_rate_excluding_errors": correct / evaluable if evaluable else None,
              "correctness_interval_95_excluding_errors": wilson_interval(correct, evaluable),
              "repair_attempts": sum(t["metrics"]["repair_attempts"] for t in trials),
              "attempts": sum(t["metrics"]["attempts"] for t in trials)}
    for key in MEASUREMENTS:
        result[key] = complete_sum([t["metrics"][key] for t in trials], monetary=key.endswith("_usd"))
    total = result["total_task_cost_usd"]
    result["cost_per_correct_task_usd"] = decimal_text(money(total) / correct) if total is not None and correct else None
    result["complete_cost_tasks"] = sum(t["metrics"]["total_task_cost_usd"] is not None for t in trials)
    return result
