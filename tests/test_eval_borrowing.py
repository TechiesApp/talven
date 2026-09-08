"""Independent acceptance regressions for the public borrowing repair corpus."""

from pathlib import Path
import json
import runpy
import subprocess
import sys
import tempfile
import unittest

from experiments.borrowing_tasks import BORROWING_TASKS
from experiments.verifier import verify
from talven.frontend import CompileError, analyze


ROOT = Path(__file__).resolve().parents[1]
SOLUTIONS = runpy.run_path(str(ROOT / "tests/fixtures/eval_borrow_adapter.py"))["SOLUTIONS"]


class BorrowingAcceptanceTests(unittest.TestCase):
    def test_starters_have_distinct_failures(self):
        for task, code in (("borrow-overlap", "E0302"), ("borrow-permission", "E0303"),
                           ("borrow-reborrow", "E0304"), ("borrow-order", None)):
            with self.subTest(task=task):
                source = (ROOT / BORROWING_TASKS[task]["source"]).read_text()
                if code:
                    with self.assertRaises(CompileError) as raised:
                        analyze(source)
                    self.assertEqual(code, raised.exception.code)
                else:
                    analyze(source)  # Ordering is a semantic bug, not a type error.
                result = verify(task, source)
                self.assertEqual("failed", result["status"], result)

    def test_handwritten_repairs_pass_real_native_checks(self):
        for task, source in SOLUTIONS.items():
            with self.subTest(task=task):
                result = verify(task, source)
                self.assertEqual("passed", result["status"], result)
                self.assertEqual(["frontend", "task-structure", "native-values", "borrow-call-trace"],
                                 [c["name"] for c in result["checks"]])
                self.assertEqual(4, len(result["commands"]))

    def test_comments_layout_and_local_names_do_not_fix_the_solution_spelling(self):
        source = SOLUTIONS["borrow-overlap"].replace("snapshot", "old_scalar")
        source = "// Repair with a different local name.\n" + source.replace(";", "; // comment\n")
        self.assertEqual("passed", verify("borrow-overlap", source)["status"])

    def test_cannot_replace_main_with_constant_success(self):
        for task, source in SOLUTIONS.items():
            with self.subTest(task=task):
                candidate = source[:source.index("fn main")] + "fn main() -> i32 { return 0; }"
                result = verify(task, candidate)
                self.assertEqual("failed", result["status"])
                self.assertIn("main", result["feedback"])

    def test_cannot_weaken_helper_or_mutation_contracts(self):
        source = SOLUTIONS["borrow-permission"]
        for candidate in (source.replace("c.value = c.value + delta;", "c.value = c.value + 3;"),
                          source.replace("fn read(c: &Counter)", "fn read(c: &mut Counter)")
                                .replace("read(&c)", "read(&mut c)")
                                .replace("read(&counter)", "read(&mut counter)")):
            with self.subTest(candidate=candidate):
                self.assertEqual("failed", verify("borrow-permission", candidate)["status"])

    def test_native_values_reject_hardcoded_delta_or_return(self):
        source = SOLUTIONS["borrow-permission"]
        # Preserve the example's answer while breaking other inputs.
        candidates = [source.replace("    add(&mut c, delta);", "    add(&mut c, 3);"),
                      source.replace("return read(&c);", "let observed = read(&c); return 8;")]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result = verify("borrow-permission", candidate)
                self.assertEqual("failed", result["status"], result)
                self.assertEqual("native-values", result["checks"][-1]["name"])

    def test_trace_rejects_field_read_bypass_and_extra_helper_calls(self):
        source = SOLUTIONS["borrow-reborrow"]
        candidates = [source.replace("let before = read(&c);", "let before = c.value;"),
                      source.replace("let before = read(&c);", "read(&c); let before = read(&c);")]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result = verify("borrow-reborrow", candidate)
                self.assertEqual("failed", result["status"], result)
                self.assertTrue(next(c["passed"] for c in result["checks"] if c["name"] == "native-values"))
                self.assertEqual("borrow-call-trace", result["checks"][-1]["name"])

    def test_trace_rejects_compensated_late_snapshot(self):
        source = SOLUTIONS["borrow-order"].replace(
            "let before = read(&c);\n    let after = add(&mut c, delta);",
            "let after = add(&mut c, delta);\n    let before = read(&c) - delta;")
        result = verify("borrow-order", source)
        self.assertEqual("failed", result["status"], result)
        self.assertTrue(next(c["passed"] for c in result["checks"] if c["name"] == "native-values"))
        self.assertEqual("borrow-call-trace", result["checks"][-1]["name"])

    def test_trace_rejects_discarded_helper_return_values(self):
        candidates = {
            "borrow-overlap": """let before = c.value;
    read(&c);
    return with_before(&mut c, before, delta);""",
            "borrow-permission": """add(&mut c, delta);
    read(&c);
    return c.value;""",
            "borrow-reborrow": """read(&c);
    let before = c.value;
    add(&mut c, delta);
    read(&c);
    return before * 100 + c.value;""",
            "borrow-order": """read(&c);
    let before = c.value;
    add(&mut c, delta);
    add(&mut c, delta);
    return before * 10000 + (before + delta) * 100 + before + delta + delta;""",
        }
        for task, body in candidates.items():
            with self.subTest(task=task):
                source = SOLUTIONS[task]
                exercise = analyze(source).functions["exercise"]
                replacement = "fn exercise(c: &mut Counter, delta: i32) -> i32 {\n    " + body + "\n}"
                candidate = source[:exercise.span.start] + replacement + source[exercise.span.end:]
                result = verify(task, candidate)
                self.assertEqual("failed", result["status"], result)
                self.assertTrue(next(c["passed"] for c in result["checks"] if c["name"] == "native-values"))
                self.assertEqual("borrow-call-trace", result["checks"][-1]["name"])
                self.assertEqual(4, len(result["commands"]))

    def test_trace_distinguishes_the_two_add_return_values(self):
        source = SOLUTIONS["borrow-order"].replace("let after = add(&mut c, delta);", "add(&mut c, delta);")
        source = source.replace("after * 100", "(second - delta) * 100")
        result = verify("borrow-order", source)
        self.assertEqual("failed", result["status"], result)
        self.assertTrue(next(c["passed"] for c in result["checks"] if c["name"] == "native-values"))
        self.assertEqual("borrow-call-trace", result["checks"][-1]["name"])
        self.assertEqual(4, len(result["commands"]))

    def test_trace_bounds_offsets_for_extra_calls(self):
        for extra in ("read(&c);\n", "add(&mut c, 0);\n"):
            with self.subTest(extra=extra):
                source = SOLUTIONS["borrow-reborrow"].replace(
                    "let before = read(&c);", extra * 20 + "let before = read(&c);")
                result = verify("borrow-reborrow", source)
                self.assertEqual("failed", result["status"], result)
                self.assertTrue(next(c["passed"] for c in result["checks"] if c["name"] == "native-values"))
                self.assertEqual("borrow-call-trace", result["checks"][-1]["name"])
                self.assertEqual(4, len(result["commands"]))
                # Invalid extra calls should be rejected normally, never crash
                # through an unchecked return-offset or event-trace array access.
                self.assertEqual(1, result["commands"][-1]["returncode"])

    def test_cannot_update_a_reconstructed_record_or_write_directly(self):
        source = SOLUTIONS["borrow-permission"]
        candidates = [source.replace("    add(&mut c, delta);", "    c.value = c.value + delta;"),
                      source.replace("    add(&mut c, delta);", "    let mut copy = Counter { value: c.value };\n"
                                     "    add(&mut copy, delta);\n    c.value = copy.value;")]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result = verify("borrow-permission", candidate)
                self.assertEqual("failed", result["status"], result)
                self.assertEqual("task-structure", result["checks"][-1]["name"])

    def test_cannot_hide_work_in_added_functions_or_branches(self):
        source = SOLUTIONS["borrow-permission"]
        candidates = [source + "fn unused() -> i32 { return 1; }",
                      source.replace("    add(&mut c, delta);", "    if (delta == 3) { add(&mut c, delta); }")]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertEqual("failed", verify("borrow-permission", candidate)["status"])

    def test_native_tool_failure_is_an_error(self):
        result = verify("borrow-permission", SOLUTIONS["borrow-permission"], cc="/missing/compiler")
        self.assertEqual("error", result["status"], result)
        self.assertTrue(result["commands"])


class BorrowingFixtureTests(unittest.TestCase):
    def command(self, *args):
        return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)

    def test_both_contexts_archive_repairs_and_reverify_without_usage_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "adapter.json"
            created = self.command("tests/fixtures/eval_borrow_adapter.py", "--write-config", config)
            self.assertEqual(0, created.returncode, created.stderr)
            completed = self.command("-m", "experiments", "run", "--corpus", "m1c-borrowing-tasks-v1",
                                     "--adapter", config, "--out", directory / "run", "--max-repairs", "1")
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            run = json.loads((directory / "run/run.json").read_text())
            self.assertEqual("m1c-borrowing-tasks-v1", run["corpus_version"])
            self.assertEqual("fixture", run["measurement_kind"])
            self.assertTrue(run["complete"])
            self.assertEqual(8, run["summary"]["correct_tasks"])
            self.assertEqual(16, run["summary"]["attempts"])
            self.assertEqual(8, run["summary"]["repair_attempts"])
            for key in ("input_tokens", "output_tokens", "total_task_cost_usd"):
                self.assertIsNone(run["summary"][key])
            for trial in run["trials"]:
                with self.subTest(trial=trial["id"]):
                    self.assertEqual(["failed", "passed"], [a["status"] for a in trial["attempts"]])
                    attempt = directory / "run" / trial["id"] / "attempt-000"
                    request = json.loads((attempt / "request.json").read_text())
                    self.assertEqual(run["corpus_version"], request["corpus_version"])
                    self.assertEqual(["task.tal"], request["allowed_files"])
                    payload = json.loads(request["messages"][-1]["content"])
                    self.assertIsNone(payload["feedback"])
                    if trial["context_mode"] == "compiler":
                        context = json.loads(payload["compiler_context"])
                        expected = "talven.context.v2" if trial["task"] == "borrow-order" else "talven.diagnostics.v1"
                        self.assertEqual(expected, context["schema"])
                    else:
                        self.assertNotIn("compiler_context", payload)
            checked = self.command("-m", "experiments", "reverify", directory / "run",
                                   "--out", directory / "verified.json")
            self.assertEqual(0, checked.returncode, checked.stderr + checked.stdout)
            result = json.loads((directory / "verified.json").read_text())
            self.assertEqual(run["corpus_version"], result["corpus_version"])
            self.assertEqual(["passed"] * 8, [trial["status"] for trial in result["trials"]])
