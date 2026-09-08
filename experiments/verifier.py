"""Independent, finite acceptance checks for the pinned four-task corpus.

This module and its generated C harness are trusted runner inputs, outside the
candidate edit set. Candidates are analyzed by the shared Talven frontend. Native
checks compare i32 values inside C, avoiding operating-system exit truncation.

Move/type tasks deliberately require straight-line main bodies and direct binding
provenance. Vector tasks test small, bounded inputs and perturb only the required
example call to check main's sensitivity to wrong results. These are reproducible
acceptance constraints, not a proof of general semantics or an OS sandbox. The
caller must bound the verifier process itself; each compiler/native command here
also has a timeout. C compiler and host are trusted infrastructure.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import tempfile

from experiments.process import run_process
from talven.backend import emit_c
from talven.frontend import Analysis, CompileError, Expr, Statement, analyze, require_entry


C_FLAGS = ("-std=c11", "-O2")
TASK_IDS = {"move-scalar", "strict-type", "rename-field", "squared-length"}


def _expressions(expr: Expr):
    yield expr
    for child in expr.args:
        yield from _expressions(child)
    for _, child in expr.fields:
        yield from _expressions(child)


def _statements(body: list[Statement]):
    for statement in body:
        yield statement
        yield from _statements(statement.then)
        yield from _statements(statement.otherwise)


def _name(expr: Expr, name: str) -> bool:
    return expr.kind == "name" and expr.value == name


def _integer(expr: Expr, value: int) -> bool:
    return expr.kind == "int" and int(expr.value) == value


def _record(analysis: Analysis, name: str, fields: dict[str, str]) -> bool:
    record = analysis.records.get(name)
    return record is not None and {n.text: t.text for n, t in record.fields} == fields


def _contract(analysis: Analysis, name: str, params: list[tuple[str, str]]) -> bool:
    function = analysis.functions.get(name)
    return (function is not None and function.result.text == "i32" and
            [(n.text, t.text) for n, t in function.params] == params)


def _structure(task: str, analysis: Analysis) -> tuple[bool, str]:
    main = analysis.functions["main"]
    if task in {"move-scalar", "strict-type"}:
        # Bounded shape prevents an unreachable decorative binding/move from
        # standing in for the requested work on the executed path.
        if (not main.body or main.body[-1].kind != "return" or
                any(s.kind != "let" for s in main.body[:-1])):
            return False, "main must use straight-line let bindings and a final binding return"
        bindings = {s.name.text: (i, s) for i, s in enumerate(main.body[:-1])}
        returned = main.body[-1].expr
        if task == "strict-type":
            count = bindings.get("count")
            valid = (count is not None and count[1].annotation is not None and
                     count[1].annotation.text == "i32" and count[1].expr.typ == "i32" and _name(returned, "count"))
            return valid, "main must return the explicitly annotated count: i32 binding"
        original = bindings.get("original")
        transferred = bindings.get("transferred")
        if (not _record(analysis, "Item", {"value": "i32"}) or original is None or
                transferred is None or original[1].mutable or
                original[1].expr.kind != "record" or original[1].expr.value != "Item" or
                len(original[1].expr.fields) != 1 or
                original[1].expr.fields[0][0].text != "value" or
                not _integer(original[1].expr.fields[0][1], 7) or
                not _name(transferred[1].expr, "original")):
            return False, "preserve immutable original = Item { value: 7 } and let transferred = original"
        # Follow scalar aliases back to the direct snapshot, with declaration
        # order supplied by successful frontend analysis.
        seen = set()
        while returned.kind == "name" and returned.value in bindings and returned.value not in seen:
            seen.add(returned.value)
            index, binding = bindings[returned.value]
            expr = binding.expr
            if (expr.kind == "field" and expr.value == "value" and _name(expr.args[0], "original") and
                    original[0] < index < transferred[0]):
                return True, "original scalar is copied before the direct record move and returned through bindings"
            returned = expr
        return False, "return a binding containing original.value copied before transferring original"

    horizontal = "horizontal" if task == "rename-field" else "x"
    if not _record(analysis, "Vec2", {horizontal: "i32", "y": "i32"}):
        return False, f"Vec2 must have exactly {horizontal}: i32 and y: i32"
    if not _contract(analysis, "dot", [("a", "Vec2"), ("b", "Vec2")]):
        return False, "preserve fn dot(a: Vec2, b: Vec2) -> i32"
    if task == "rename-field":
        if any(n.text == "x" for record in analysis.program.records for n, _ in record.fields):
            return False, "old field x must be absent from record declarations"
        for fn in analysis.program.functions:
            for statement in _statements(fn.body):
                roots = [statement.expr] + ([statement.target] if statement.target else [])
                for root in roots:
                    for expr in _expressions(root):
                        if (expr.kind == "field" and expr.value == "x") or any(n.text == "x" for n, _ in expr.fields):
                            return False, "old field x must be absent from reads, writes, and constructors"
        return True, "renamed record and dot contracts preserved; no old field remains"
    valid = _contract(analysis, "squared_length", [("value", "Vec2")])
    return valid, "require fn squared_length(value: Vec2) -> i32"


def _run(argv: list[str], timeout: float, commands: list[dict]) -> dict:
    # Keep children in the outer verifier's group. The runner owns that group
    # and kills it on total timeout or completion, including any grandchildren.
    command = run_process(argv, cwd=Path.cwd(), timeout=timeout, start_new_session=False)
    error = command.get("error")
    if error == "timeout":
        command["timed_out"] = True
    elif error == "output_limit":
        command["output_limited"] = True
    elif error:
        command["launch_error"] = error
    commands.append(command)
    return command


def _harness(task: str) -> str:
    expected = {"move-scalar": 7, "strict-type": 1}.get(task, 0)
    checks = [f'if (tv_f_main() != INT32_C({expected})) {{ puts("main returned an unexpected i32 value"); return 1; }}']
    if task in {"rename-field", "squared-length"}:
        checks += ["""const int32_t values[][4] = {
            {0,0,0,0}, {2,3,4,5}, {1,0,0,1}, {1,0,7,-2},
            {0,1,7,-2}, {-3,4,5,-6}, {-2,-7,-5,3}, {8,9,-2,4}
        };
        for (unsigned i = 0; i < sizeof(values)/sizeof(values[0]); ++i) {
            int32_t a = values[i][0], b = values[i][1], c = values[i][2], d = values[i][3];
            struct tv_s_Vec2 left = {.tv_m_horizontal=a, .tv_m_y=b};
            struct tv_s_Vec2 right = {.tv_m_horizontal=c, .tv_m_y=d};
            if (tv_f_dot(left, right) != a*c + b*d) { puts("dot vector mismatch"); return 1; }
        }""".replace("tv_m_horizontal", "tv_m_horizontal" if task == "rename-field" else "tv_m_x")]
    if task == "squared-length":
        checks += ["""const int32_t values[][2] = {
            {0,0}, {3,4}, {4,3}, {1,0}, {0,1}, {-3,4}, {3,-4}, {-3,-4}, {2,7}, {-8,1}
        };
        for (unsigned i = 0; i < sizeof(values)/sizeof(values[0]); ++i) {
            int32_t x = values[i][0], y = values[i][1];
            struct tv_s_Vec2 value = {.tv_m_x=x, .tv_m_y=y};
            if (tv_f_squared_length(value) != x*x + y*y) { puts("squared_length vector mismatch"); return 1; }
        }"""]
    return ("int main(void) {\n" + "\n".join("{\n" + check + "\n}" for check in checks) +
            '\nputs("native checks passed"); return 0; }\n')


def _mutant(task: str, analysis: Analysis, wrong: int, function: str) -> Analysis:
    """Perturb only the specified example arguments; other inputs remain correct."""
    if function == "dot":
        fn = analysis.functions["dot"]
        field = "horizontal" if task == "rename-field" else "x"
        body = f"""fn dot(a: Vec2, b: Vec2) -> i32 {{
            if (a.{field} == 2 && a.y == 3 && b.{field} == 4 && b.y == 5) {{ return {wrong}; }}
            return a.{field} * b.{field} + a.y * b.y;
        }}"""
    else:
        fn = analysis.functions["squared_length"]
        body = f"""fn squared_length(value: Vec2) -> i32 {{
            if (value.x == 3 && value.y == 4) {{ return {wrong}; }}
            return value.x * value.x + value.y * value.y;
        }}"""
    return analyze(analysis.source[:fn.span.start] + body + analysis.source[fn.span.end:])


def verify(task_id: str, source: str, cc: str = "cc", timeout: float = 5.0) -> dict:
    """Return JSON-serializable acceptance and actual command evidence."""
    result = {"status": "failed", "checks": [], "feedback": "", "commands": []}

    def check(name: str, passed: bool, message: str):
        result["checks"].append({"name": name, "passed": passed, "message": message})
        if not passed:
            result["feedback"] = message

    if task_id not in TASK_IDS or not math.isfinite(timeout) or timeout <= 0:
        result.update(status="error", feedback="unknown task or invalid positive finite timeout")
        return result
    try:
        analysis = analyze(source)
        require_entry(analysis)
    except CompileError as exc:
        check("frontend", False, f"{exc.code}: {exc.message}")
        result["diagnostics"] = [exc.diagnostic(source)]
        return result
    check("frontend", True, "shared frontend and native entry checks passed")
    valid, message = _structure(task_id, analysis)
    check("task-structure", valid, message)
    if not valid:
        return result

    def native(directory: Path, name: str, checked: Analysis, harness: str) -> bool:
        c_path, executable = directory / f"{name}.c", directory / name
        c_path.write_text(emit_c(checked, freestanding=True) +
                          "\n#include <stdlib.h>\n#include <stdio.h>\n"
                          "_Noreturn void talven_trap(void) { abort(); }\n" + harness, encoding="utf-8")
        compiled = _run([cc, *C_FLAGS, str(c_path), "-o", str(executable)], timeout, result["commands"])
        if compiled["returncode"] != 0 or compiled.get("error"):
            result["status"] = "error"
            check(name, False, "native C compilation failed, timed out, or could not launch; inspect command evidence")
            return False
        executed = _run([str(executable)], timeout, result["commands"])
        passed = executed["returncode"] == 0 and not executed.get("error")
        if "launch_error" in executed:
            result["status"] = "error"
        check(name, passed, "native check passed" if passed else
              f"{name} failed or timed out; the required calculation or main check did not meet acceptance")
        return passed

    try:
        with tempfile.TemporaryDirectory(prefix="talven-acceptance-") as temporary:
            directory = Path(temporary)
            if not native(directory, "native-values", analysis, _harness(task_id)):
                return result
            if task_id in {"rename-field", "squared-length"}:
                functions = [("dot", 23)]
                if task_id == "squared-length":
                    functions.append(("squared_length", 25))
                for function, expected in functions:
                    for wrong in (0, expected - 1, expected + 1):
                        harness = ('int main(void) { if (tv_f_main() == 0) { '
                                   'puts("main accepted a wrong example result"); return 1; } '
                                   'puts("main rejected the wrong example result"); return 0; }\n')
                        if not native(directory, f"main-{function}-sensitivity-{wrong}",
                                      _mutant(task_id, analysis, wrong, function), harness):
                            return result
    except (OSError, UnicodeError, CompileError) as exc:
        result.update(status="error", feedback=f"verifier infrastructure error: {exc}")
        return result
    result.update(status="passed", feedback="all task acceptance checks passed")
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--timeout", type=float, default=5.0)
    try:
        args = parser.parse_args()
        result = verify(args.task, Path(args.source).read_text(encoding="utf-8"), args.cc, args.timeout)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "error", "checks": [], "feedback": str(exc), "commands": []}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return {"passed": 0, "failed": 1, "error": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
