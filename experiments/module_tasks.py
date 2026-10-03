"""Deterministic multi-file tasks with nominal records and immutable dependencies."""
import random

from talven.formatter import format_source
from talven.project import PROFILE
from .large_tasks import FORMS, INPUTS, _helper, simulate

MODULE_CORPUS = "m1-module-tasks-v1"
BASE = "experiments/corpora/modules-v1/"


def generate(seed, count):
    rng = random.Random(seed)
    table = [(f"stage_{i:02d}", FORMS[i % 4], rng.randint(2, 3), (i // 4) % 2) for i in range(24)]
    while True:
        chosen = [rng.choice([row for row in table if row[1] == form]) for form in FORMS]
        chosen += rng.sample([row for row in table if row not in chosen], count - 4)
        rng.shuffle(chosen)
        if max(abs(v) for inputs in INPUTS for v in simulate([row[:3] for row in chosen], *inputs)) < 10**7:
            break
    dependencies = {}
    imports = []
    for module in range(2):
        rows = [row for row in table if row[3] == module]
        # All four forms occur in each module: assign ownership independently
        # of the signature form so nominal types cannot be guessed from it.
        imports.append(f'import "ledger{module}.tal" {{ Account as Ledger{module}, ' +
                       ", ".join(f"{name} as call_{name}" for name, _, _, _ in rows) + " };")
        source = "pub struct Account { balance: i32, limit: i32, tier: i32 }\n"
        source += "fn adjust(v: i32) -> i32 { return v - 1; }\n"
        for name, form, k, _ in rows:
            helper = _helper(name, form, k).replace("fn ", "pub fn ", 1)
            if form == "pure":
                helper = helper.replace(f"v * {k} - 1", f"adjust(v * {k})")
            source += helper
        dependencies[f"ledger{module}.tal"] = format_source(source, module=True)
    source = "\n".join(imports) + "\nstruct Account { balance: i32, limit: i32, tier: i32 }\n"
    source += "fn pipeline(a: &mut Account, v: i32) -> i32 { return v; }\n"
    source += "fn main() -> i32 { let mut a = Account { balance: 10, limit: 500, tier: 1 }; return pipeline(&mut a, 0); }\n"
    return format_source(source, module=True), dependencies, chosen, table


SOURCES, DEPENDENCIES, STAGES, TABLES, MODULE_TASKS = {}, {}, {}, {}, {}
for task, seed, count in (("module-pipeline-8", 318, 8), ("module-pipeline-12", 412, 12)):
    SOURCES[task], DEPENDENCIES[task], STAGES[task], TABLES[task] = generate(seed, count)
    MODULE_TASKS[task] = {
        "source": BASE + task + "/task.tal",
        "dependencies": {name: BASE + task + "/" + name for name in DEPENDENCIES[task]},
        "profile": PROFILE, "guides": ["docs/module-reference.md"], "edit": "function:pipeline",
        "instruction": "Implement pipeline(a: &mut Account, v: i32) -> i32. The read-only files are explicit "
        "dependencies. Call these imported aliases exactly once each, in this order: " +
        ", ".join("call_" + row[0] for row in STAGES[task]) + ". Start the running value at v and feed each "
        "call's return into the next call, returning the final value. For every helper that takes a record, "
        "construct its defining module's record type from a's current balance, limit and tier fields. Pass it "
        "by value or by an explicit shared/exclusive borrow as the helper requires. After each exclusive-borrow "
        "call, copy all three resulting fields back to a before the next stage. Do not move a, confuse equally "
        "shaped nominal types, reorder/skip/add calls, inline the helper arithmetic, or alter other declarations. "
        "The verifier checks executed call order, arguments, returned values and final state across multiple inputs.",
    }
