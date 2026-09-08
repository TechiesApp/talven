"""Acceptance tests exercise behavior independently of candidate-owned checks."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.verifier import verify


MOVE = """struct Item { value: i32 }
fn main() -> i32 {
    let original = Item { value: 7 };
    let saved = original.value;
    let transferred = original;
    return saved;
}
"""
STRICT = "fn main() -> i32 { let count: i32 = 1; return count; }"
VECTORS = """struct Vec2 { x: i32, y: i32 }
fn dot(a: Vec2, b: Vec2) -> i32 { return a.x * b.x + a.y * b.y; }
fn main() -> i32 {
    let left = Vec2 { x: 2, y: 3 };
    let right = Vec2 { x: 4, y: 5 };
    let result = dot(left, right);
    if (result == 23) { return 0; } else { return 1; }
}
"""
RENAME = VECTORS.replace("x", "horizontal")
SQUARED_FUNCTION = """fn squared_length(value: Vec2) -> i32 {
    return value.x * value.x + value.y * value.y;
}
"""
SQUARED = VECTORS.replace("fn main() -> i32 {", """fn main() -> i32 {
    let point = Vec2 { x: 3, y: 4 };
    if (squared_length(point) != 25) { return 1; }
""") + SQUARED_FUNCTION


def command_result(returncode=0, error=None, stderr=""):
    return {"argv": ["test-command"], "returncode": returncode, "stdout": "",
            "stderr": stderr, "error": error, "elapsed_seconds": 0.01}


class VerifierStructureTests(unittest.TestCase):
    def test_rejects_invalid_frontend_and_unknown_task(self):
        self.assertEqual(verify("strict-type", "not Talven")["status"], "failed")
        self.assertEqual(verify("not-a-task", STRICT)["status"], "error")

    def test_move_rejects_literal_return_or_borrow_or_no_move(self):
        candidates = [MOVE.replace("return saved", "return 7"),
                      MOVE.replace("let transferred = original;", ""),
                      MOVE.replace("let transferred = original;", "read(&original);") +
                      "fn read(item: &Item) -> i32 { return item.value; }"]
        for source in candidates:
            with self.subTest(source=source):
                self.assertEqual(verify("move-scalar", source)["status"], "failed")

    def test_strict_rejects_removed_or_bypassed_count(self):
        for source in ["fn main() -> i32 { return 1; }",
                       STRICT.replace("return count", "return 1"),
                       STRICT.replace("count: i32", "count"),
                       "fn main() -> bool { let count = true; return count; }"]:
            self.assertEqual(verify("strict-type", source)["status"], "failed")

    def test_rename_requires_complete_contract(self):
        self.assertEqual(verify("rename-field", VECTORS)["status"], "failed")
        extra = RENAME + "struct Other { x: i32 }"
        self.assertEqual(verify("rename-field", extra)["status"], "failed")

    def test_squared_requires_exact_function_contract(self):
        self.assertEqual(verify("squared-length", VECTORS)["status"], "failed")
        source = SQUARED.replace("value: Vec2", "value: &Vec2").replace("squared_length(point)", "squared_length(&point)")
        self.assertEqual(verify("squared-length", source)["status"], "failed")

    def test_missing_cc_is_error_with_command_evidence(self):
        result = verify("strict-type", STRICT, cc="/no/such/talven-test-cc")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["commands"][0]["returncode"])

    def test_compile_failure_is_error(self):
        with patch("experiments.verifier.run_process", return_value=command_result(1, stderr="C error")):
            result = verify("strict-type", STRICT)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["commands"][0]["stderr"], "C error")

    def test_compile_timeout_is_infrastructure_error(self):
        with patch("experiments.verifier.run_process", return_value=command_result(-9, "timeout")):
            result = verify("strict-type", STRICT, timeout=0.1)
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["commands"][0]["timed_out"])

    def test_native_timeout_is_bounded_and_reported(self):
        with patch("experiments.verifier.run_process", side_effect=[command_result(), command_result(-9, "timeout")]) as run:
            result = verify("strict-type", STRICT, timeout=0.1)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["commands"][-1]["timed_out"])
        self.assertTrue(all(call.kwargs["start_new_session"] is False for call in run.call_args_list))

    def test_output_limit_fails_even_if_command_exits_zero(self):
        with patch("experiments.verifier.run_process", return_value=command_result(0, "output_limit")):
            result = verify("strict-type", STRICT)
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["commands"][0]["output_limited"])
        with patch("experiments.verifier.run_process", side_effect=[command_result(), command_result(0, "output_limit")]):
            result = verify("strict-type", STRICT)
        self.assertEqual(result["status"], "failed")


@unittest.skipUnless(shutil.which("cc"), "native acceptance requires cc")
class VerifierNativeTests(unittest.TestCase):
    def test_successful_repairs(self):
        for task, source in [("move-scalar", MOVE), ("strict-type", STRICT),
                             ("rename-field", RENAME), ("squared-length", SQUARED)]:
            with self.subTest(task=task):
                result = verify(task, source)
                self.assertEqual(result["status"], "passed", result)
                self.assertTrue(result["commands"])
                self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_exact_i32_not_truncated_exit(self):
        self.assertEqual(verify("strict-type", STRICT.replace("= 1", "= 257"))["status"], "failed")

    def test_rename_rejects_constant_dot_and_unused_main_check(self):
        candidates = [RENAME.replace("return a.horizontal * b.horizontal + a.y * b.y", "return 23"),
                      RENAME.replace("if (result == 23)", "if (true || result == 23)"),
                      RENAME.replace("return 1;", "return 0;")]
        for source in candidates:
            self.assertEqual(verify("rename-field", source)["status"], "failed")

    def test_squared_rejects_constant_and_unused_function(self):
        candidates = [SQUARED.replace("value.x * value.x + value.y * value.y", "25"),
                      VECTORS + SQUARED_FUNCTION,
                      SQUARED.replace("if (squared_length(point) != 25)", "if (false && squared_length(point) != 25)"),
                      SQUARED.replace("return 1;", "return 0;"),
                      SQUARED.replace("x: 3, y: 4", "x: 4, y: 3")]
        for source in candidates:
            with self.subTest(source=source):
                self.assertEqual(verify("squared-length", source)["status"], "failed")

    def test_squared_requires_dot_contract_behavior_and_main_check(self):
        candidates = [
            SQUARED.replace("return a.x * b.x + a.y * b.y", "return 23"),
            SQUARED.replace("if (result == 23)", "if (true || result == 23)"),
            SQUARED.replace("dot(a: Vec2, b: Vec2)", "product(a: Vec2, b: Vec2)").replace("dot(left, right)", "product(left, right)"),
        ]
        for source in candidates:
            with self.subTest(source=source):
                self.assertEqual(verify("squared-length", source)["status"], "failed")

    def test_unreachable_fake_main_check(self):
        source = SQUARED.replace("let point", "if (true) { return 0; }\n    let point")
        self.assertEqual(verify("squared-length", source)["status"], "failed")

    def test_real_native_nontermination(self):
        source = ("fn spin(n: i32) -> i32 { return spin(n); } "
                  "fn main() -> i32 { let count: i32 = spin(1); return count; }")
        result = verify("strict-type", source, timeout=2.0)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["commands"][0]["returncode"], 0)
        self.assertTrue(result["commands"][-1]["timed_out"])

    def test_renaming_ignores_comments(self):
        result = verify("rename-field", RENAME + "// The old x field was renamed.\n")
        self.assertEqual(result["status"], "passed", result)

    def test_cli_emits_one_json_object(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "task.tal"
            source.write_text(STRICT, encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "experiments.verifier", "--task", "strict-type", "--source", str(source)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "passed")
        self.assertEqual(len(result.stdout.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
