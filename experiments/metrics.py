"""Accounting for reported observations; unknown is not zero."""

from decimal import Decimal, InvalidOperation


TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens")
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
    cached, total = usage.get("cached_input_tokens"), usage.get("input_tokens")
    if cached is not None and (total is None or cached > total):
        raise ValueError("Cached input tokens must be a subset of reported input tokens")
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


def aggregate(trials):
    correct = sum(t["status"] == "passed" for t in trials)
    result = {"tasks": len(trials), "correct_tasks": correct,
              "failed_tasks": sum(t["status"] == "failed" for t in trials),
              "error_tasks": sum(t["status"] == "error" for t in trials),
              "correctness_rate": correct / len(trials) if trials else None,
              "repair_attempts": sum(t["metrics"]["repair_attempts"] for t in trials),
              "attempts": sum(t["metrics"]["attempts"] for t in trials)}
    for key in MEASUREMENTS:
        result[key] = complete_sum([t["metrics"][key] for t in trials], monetary=key.endswith("_usd"))
    total = result["total_task_cost_usd"]
    result["cost_per_correct_task_usd"] = decimal_text(money(total) / correct) if total is not None and correct else None
    result["complete_cost_tasks"] = sum(t["metrics"]["total_task_cost_usd"] is not None for t in trials)
    return result
