"""Large-program tasks: implement a pipeline over helpers buried in a big file.

Each starter declares one record and many helpers with similar names. A helper
takes the account in one of four ways (exclusive borrow, shared borrow, by
value, or not at all), and the correct call for each stage depends on that
signature. The source-only condition must find each signature in the file;
the compiler condition also gets the compact, sorted signature list.

Programs are generated deterministically from the specifications below and
committed; tests check that the files match this generator.
"""

import random

from talven.formatter import format_source

LARGE_CORPUS = "m1-large-tasks-v1"
_BASE = "experiments/corpora/large-v1/"
FORMS = ("mut", "read", "consume", "pure")
_PREFIXES = ("ledger", "audit", "settle", "accrue", "rebate", "levy", "credit", "debit", "adjust", "post")

# (task id, file, seed, helper count, stage count)
_SPECS = (
    ("pipeline-40", "pipeline40.tal", 40, 40, 4),
    ("pipeline-80", "pipeline80.tal", 80, 80, 5),
    ("pipeline-140", "pipeline140.tal", 140, 140, 6),
    ("pipeline-200", "pipeline200.tal", 200, 200, 6),
)

# Test inputs for acceptance: (balance, limit, tier, v).
INPUTS = tuple((balance, limit, tier, v) for balance in (-40, 0, 25, 100) for limit in (500,)
               for tier in (1, 3) for v in (-7, 0, 13))


def _helper(name, form, k):
    if form == "mut":
        return (f"fn {name}(a: &mut Account, v: i32) -> i32 {{\n    a.balance = a.balance + v * {k};\n"
                f"    return a.balance;\n}}\n")
    if form == "read":
        return f"fn {name}(a: &Account, v: i32) -> i32 {{\n    return a.balance - v * {k};\n}}\n"
    if form == "consume":
        return f"fn {name}(a: Account, v: i32) -> i32 {{\n    return a.balance + a.tier * {k} - v;\n}}\n"
    return f"fn {name}(v: i32) -> i32 {{\n    return v * {k} - 1;\n}}\n"


def simulate(stages, balance, limit, tier, v):
    """Reference semantics of pipeline; also used to keep values within i32."""
    running = v
    for _, form, k in stages:
        if form == "mut":
            balance += running * k
            running = balance
        elif form == "read":
            running = balance - running * k
        elif form == "consume":
            running = balance + tier * k - running
        else:
            running = running * k - 1
    return running, balance


def generate(seed, helpers, stage_count):
    """Return (source, stages) where stages are (name, form, k) in call order."""
    rng = random.Random(seed)
    while True:
        names = rng.sample([f"{p}_{n:02d}" for p in _PREFIXES for n in range(100)], helpers)
        table = [(name, FORMS[i % 4], rng.randint(2, 5)) for i, name in enumerate(names)]
        rng.shuffle(table)
        # Stages cover every form, so each kind of call must be written correctly.
        by_form = {form: [row for row in table if row[1] == form] for form in FORMS}
        stages = [rng.choice(by_form[form]) for form in FORMS]
        stages += rng.sample([row for row in table if row not in stages], stage_count - len(FORMS))
        rng.shuffle(stages)
        extremes = [abs(value) for inputs in INPUTS for value in simulate(stages, *inputs)]
        if max(extremes) < 10**6:
            break
    body = ["struct Account {\n    balance: i32,\n    limit: i32,\n    tier: i32\n}\n"]
    body += [_helper(*row) for row in table]
    body.append("fn pipeline(a: &mut Account, v: i32) -> i32 {\n    return v;\n}\n")
    body.append("fn main() -> i32 {\n    let mut account = Account { balance: 10, limit: 500, tier: 1 };\n"
                "    return pipeline(&mut account, 0) - pipeline(&mut account, 0);\n}\n")
    return format_source("\n".join(body)), stages


def _instruction(stages):
    order = ", ".join(name for name, _, _ in stages)
    return (
        "Implement pipeline(a: &mut Account, v: i32) -> i32. Keep a running value that starts at v. Call these "
        f"functions exactly once each, in this order: {order}. Pass each one the running value, and pass the "
        "account in whatever way that function's parameters require; a function that takes an Account by value "
        "gets a new Account built from a's current field values. Each call's result becomes the running value. "
        "Return the final running value. Do not change any other function, the struct, or main."
    )


STAGES = {}
SOURCES = {}
LARGE_TASKS = {}
for _task, _file, _seed, _helpers, _count in _SPECS:
    SOURCES[_task], STAGES[_task] = generate(_seed, _helpers, _count)
    LARGE_TASKS[_task] = {"source": _BASE + _file, "instruction": _instruction(STAGES[_task]),
                          "edit": "function:pipeline"}
