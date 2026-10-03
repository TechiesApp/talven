"""Correctness gates and failure retention for the native comparison runner."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("native_comparison", ROOT / "scripts/measure-native-prototype.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)
BINARY = Path(os.environ.get("TALVEN_NATIVE", ROOT / "experiments/native-compiler/target/release/talven-native")).resolve()


class ComparisonTests(unittest.TestCase):
    def test_stale_native_build_sources_are_rejected(self):
        info = json.loads(subprocess.check_output([str(BINARY), "--build-info"]))
        comparison.verify_build_sources(info, ROOT / "experiments/native-compiler")
        for name in ("src/lib.rs", "src/format.rs", "src/context.rs", "src/input.rs", "src/edit.rs", "src/c_api.rs", "src/resources.rs",
                     "../supplied-storage/runtime.h", "../supplied-storage/source-runtime.c"):
            with self.subTest(source=name):
                original = info["source_files"][name]
                info["source_files"][name] += "// stale"
                with self.assertRaises(comparison.base.MeasurementError):
                    comparison.verify_build_sources(info, ROOT / "experiments/native-compiler")
                info["source_files"][name] = original

    def test_incomplete_or_unverified_samples_never_get_summary(self):
        with self.assertRaises(comparison.base.MeasurementError):
            comparison.summarize([], 1)
        rows = [{"phase": "measured", "workload": w, "implementation": i, "operation": op,
                 "verified": True, "elapsed_ns": 5}
                for w in ("hello", "chain-32", "chain-128") for i in ("reference", "native") for op in ("check", "emit-c")]
        self.assertEqual(12, len(comparison.summarize(rows, 1)))
        rows[-1]["verified"] = False
        with self.assertRaises(comparison.base.MeasurementError):
            comparison.summarize(rows, 1)

    def test_agent_tool_outputs_require_exact_facts_and_layout(self):
        for operation, correct in (("context", b'{"functions":[],"records":[],"schema":"talven.agent-context.v2"}\n'),
                                   ("fmt", b"fn f() -> i32 {\n    return 0;\n}\n")):
            comparison.validate_output(operation, "native", correct, expected=correct)
            for wrong in (b"", b"{}", correct + b" "):
                with self.assertRaises(comparison.base.MeasurementError):
                    comparison.validate_output(operation, "native", wrong, expected=correct)
            with self.assertRaises(comparison.base.MeasurementError):
                comparison.validate_output(operation, "native", correct)
        with self.assertRaises(comparison.base.MeasurementError):
            comparison.validate_output("unknown", "native", b"output")

    def test_agent_tool_summary_rejects_missing_or_unverified_operations(self):
        rows = [{"phase": "measured", "workload": w, "implementation": i, "operation": op,
                 "verified": True, "elapsed_ns": 5}
                for w in ("hello", "chain-32", "chain-128") for i in ("reference", "native")
                for op in comparison.AGENT_OPERATIONS]
        self.assertEqual(24, len(comparison.summarize(rows, 1, comparison.AGENT_OPERATIONS)))
        for missing in ("context", "fmt"):
            with self.assertRaises(comparison.base.MeasurementError):
                comparison.summarize([r for r in rows if r["operation"] != missing], 1, comparison.AGENT_OPERATIONS)
        rows[-1]["verified"] = False
        with self.assertRaises(comparison.base.MeasurementError):
            comparison.summarize(rows, 1, comparison.AGENT_OPERATIONS)

    def test_agent_tool_comparison_retains_verified_facts_formatting_and_native_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "run"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/measure-native-prototype.py"),
                                     "--native", str(BINARY), "--out", str(out), "--repetitions", "1",
                                     "--warmups", "0", "--agent-tools"], capture_output=True, timeout=60)
            self.assertEqual(0, result.returncode, result.stderr)
            report = json.loads((out / "report.json").read_text())
            self.assertTrue(report["complete"] and report["passed"])
            self.assertEqual("talven.native-agent-tools.v1", report["schema"])
            self.assertEqual(list(comparison.AGENT_OPERATIONS), report["operations"])
            self.assertEqual(24, len(report["summary"]))
            measured = [c for c in report["commands"] if c["phase"] == "measured"]
            self.assertEqual(24, len(measured))
            verification = [c for c in report["commands"]
                            if c["phase"] == "verification" and c.get("operation") in
                            ("formatted-emit-c", "formatted-check")]
            self.assertEqual(12, len(verification))
            self.assertTrue(all(c["verified"] for c in measured + verification))
            for workload in report["workloads"]:
                self.assertGreater(workload["agent_tools"]["context_bytes"], 0)
                self.assertEqual({"reference", "native"}, set(workload["native_acceptance"]))
            self.assertIn("experiments/native-compiler/src/format.rs", report["inputs"])

    def test_independent_chain_oracle_rejects_constant_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            (out / "commands").mkdir()
            recorder = comparison.base.Recorder(out, {"commands": []}, 10)
            workload = comparison.selected_workloads()[1]
            wrong = b"#include <stdint.h>\nint32_t tv_f_step_31(int32_t x){(void)x;return 0;} int32_t tv_f_main(void){return 0;} int main(void){return 0;}\n"
            with self.assertRaises(comparison.base.MeasurementError):
                comparison.verify_c(recorder, "cc", out, wrong, workload)

    def test_failure_is_retained_without_summary_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "run"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/measure-native-prototype.py"),
                                     "--native", sys.executable, "--out", str(out), "--repetitions", "1"],
                                    capture_output=True, timeout=10)
            self.assertEqual(1, result.returncode)
            report = json.loads((out / "report.json").read_text())
            self.assertFalse(report["passed"])
            self.assertFalse(report["complete"])
            self.assertIsNone(report["summary"])
            self.assertIn("error", report)
            before = (out / "report.json").read_bytes()
            again = subprocess.run([sys.executable, str(ROOT / "scripts/measure-native-prototype.py"),
                                    "--native", str(BINARY), "--out", str(out)], capture_output=True, timeout=10)
            self.assertEqual(1, again.returncode)
            self.assertEqual(before, (out / "report.json").read_bytes())

    def test_complete_offline_comparison_retains_inputs_and_verified_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "run"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/measure-native-prototype.py"),
                                     "--native", str(BINARY), "--out", str(out), "--repetitions", "1", "--warmups", "0"],
                                    capture_output=True, timeout=60)
            self.assertEqual(0, result.returncode, result.stderr)
            report = json.loads((out / "report.json").read_text())
            self.assertTrue(report["complete"] and report["passed"])
            self.assertEqual(12, len(report["summary"]))
            self.assertEqual(12, sum(c["phase"] == "measured" for c in report["commands"]))
            self.assertTrue(all(c["verified"] for c in report["commands"]))
            self.assertIn("experiments/native-compiler/src/lib.rs", report["inputs"])
            self.assertTrue((out / "inputs" / "native-executable").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
