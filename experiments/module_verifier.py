"""Finite multi-file acceptance with instrumented executed calls and independent values."""
from pathlib import Path
import tempfile

from talven.backend import emit_c, signature
from talven.frontend import CompileError, lex, require_entry
from talven.project import analyze_project, parse_module
from .large_tasks import INPUTS
from .module_tasks import DEPENDENCIES, MODULE_TASKS, SOURCES, STAGES, TABLES

TASK_IDS = set(MODULE_TASKS)


def _tokens(source):
    return [(t.kind, t.text) for t in lex(source) if t.kind != "eof"]


def structure(task, source):
    module = parse_module(source)
    fn = module.declarations.get("pipeline")
    if fn is None or not hasattr(fn, "params") or fn.signature() != "fn pipeline(a: &mut Account, v: i32) -> i32":
        return False
    expected = parse_module(SOURCES[task]).declarations["pipeline"]
    restored = source[:fn.span.start] + SOURCES[task][expected.span.start:expected.span.end] + source[fn.span.end:]
    return _tokens(restored) == _tokens(SOURCES[task])


def instrument(task, project, generated):
    for index, (name, form, _, module) in enumerate(TABLES[task]):
        fn = project.analysis.functions[project.scopes[f"ledger{module}.tal"][name]]
        marker = signature(fn) + " {"
        if generated.count(marker) != 1:
            raise ValueError("Cannot identify the checked helper definition")
        fields = ("0, 0, 0" if form == "pure" else
                  ", ".join(f"tv_v_a{'->' if form != 'consume' else '.'}tv_m_{field}"
                            for field in ("balance", "limit", "tier")))
        generated = generated.replace(marker, marker + f"\n    tv_trace({index}, tv_v_v, {fields});", 1)
    count = len(STAGES[task])
    return f"""#include <stdint.h>
static int trace_count, trace_bad;
static int64_t expected[{count}][5];
static void tv_trace(int id, int32_t v, int32_t b, int32_t l, int32_t t) {{
    if (trace_count >= {count}) {{ trace_bad = 1; return; }}
    const int64_t *row = expected[trace_count++];
    if (row[0] != id || row[1] != v || row[2] != b || row[3] != l || row[4] != t) trace_bad = 1;
}}
""" + generated


def harness(task, project):
    steps = []
    ids = {row[0]: index for index, row in enumerate(TABLES[task])}
    for index, (name, form, k, _) in enumerate(STAGES[task]):
        fields = "0, 0, 0" if form == "pure" else "balance, limit, tier"
        steps.append(f"int64_t row_{index}[] = {{{ids[name]}, running, {fields}}}; "
                     f"for (int j = 0; j < 5; ++j) expected[{index}][j] = row_{index}[j];")
        operation = {"mut": f"balance += running * {k}; running = balance;",
                     "read": f"running = balance - running * {k};",
                     "consume": f"running = balance + tier * {k} - running;",
                     "pure": f"running = running * {k} - 1;"}[form]
        steps.append(operation)
    record = project.scopes["task.tal"]["Account"]
    function = project.scopes["task.tal"]["pipeline"]
    rows = ", ".join("{%d, %d, %d, %d}" % row for row in INPUTS)
    return f"""int main(void) {{
    const int64_t inputs[][4] = {{{rows}}};
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {{
        int64_t balance = inputs[i][0], limit = inputs[i][1], tier = inputs[i][2], running = inputs[i][3];
        {" ".join(steps)}
        struct tv_s_{record} account = {{.tv_m_balance = (int32_t)inputs[i][0], .tv_m_limit = (int32_t)limit,
                                         .tv_m_tier = (int32_t)tier}};
        trace_count = 0; trace_bad = 0;
        int32_t result = tv_f_{function}(&account, (int32_t)inputs[i][3]);
        if (trace_bad || trace_count != {len(STAGES[task])}) {{ puts("wrong executed calls or arguments"); return 1; }}
        if (result != running || account.tv_m_balance != balance || account.tv_m_limit != limit || account.tv_m_tier != tier) {{
            puts("wrong return or final account fields"); return 1;
        }}
    }}
    puts("module native acceptance passed"); return 0;
}}
"""


def verify(task, source, cc, timeout):
    # Import after the dispatcher has loaded, sharing its bounded command receipts.
    from .verifier import C_FLAGS, _run
    result = {"status": "failed", "checks": [], "feedback": "", "commands": []}

    def check(name, passed, message):
        result["checks"].append({"name": name, "passed": passed, "message": message})
        if not passed:
            result["feedback"] = message
        return passed

    try:
        root = Path(__file__).resolve().parents[1]
        fixed = {name: (root / path).read_text(encoding="utf-8")
                 for name, path in MODULE_TASKS[task]["dependencies"].items()}
        if fixed != DEPENDENCIES[task] or (root / MODULE_TASKS[task]["source"]).read_text(encoding="utf-8") != SOURCES[task]:
            result.update(status="error", feedback="trusted committed corpus differs from its generator")
            return result
        project = analyze_project("task.tal", {"task.tal": source, **DEPENDENCIES[task]})
        require_entry(project.analysis)
    except CompileError as error:
        check("frontend", False, f"{error.code}: {error.message}")
        result["diagnostics"] = [error.diagnostic(source)]
        return result
    except (OSError, UnicodeError) as error:
        result.update(status="error", feedback=f"trusted corpus cannot be read: {error}")
        return result
    check("frontend", True, "shared project frontend passed with fixed dependencies")
    if not check("task-structure", structure(task, source), "keep all declarations and imports except pipeline's body"):
        return result
    try:
        with tempfile.TemporaryDirectory(prefix="talven-module-acceptance-") as temporary:
            directory = Path(temporary)
            c_path, executable = directory / "candidate.c", directory / "candidate"
            generated = instrument(task, project, emit_c(project.analysis, freestanding=True))
            c_path.write_text(generated + "\n#include <stdlib.h>\n#include <stdio.h>\n"
                              "_Noreturn void talven_trap(void) { abort(); }\n" + harness(task, project), encoding="utf-8")
            compiled = _run([cc, *C_FLAGS, str(c_path), "-o", str(executable)], timeout, result["commands"])
            if compiled["returncode"] != 0 or compiled.get("error"):
                result.update(status="error", feedback="native compilation failed; inspect command evidence")
                return result
            executed = _run([str(executable)], timeout, result["commands"], candidate=True)
            if "launch_error" in executed:
                result["status"] = "error"
            if not check("native-values-and-trace", executed["returncode"] == 0 and not executed.get("error"),
                         "native call order/arguments, result and final fields " +
                         ("passed" if executed["returncode"] == 0 and not executed.get("error") else "failed")):
                return result
    except (OSError, UnicodeError, CompileError, ValueError) as error:
        result.update(status="error", feedback=f"verifier infrastructure error: {error}")
        return result
    result.update(status="passed", feedback="all module task acceptance checks passed")
    return result
