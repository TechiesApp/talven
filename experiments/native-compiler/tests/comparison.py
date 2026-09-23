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
        info["source_files"]["src/lib.rs"] += "// stale"
        with self.assertRaises(comparison.base.MeasurementError):
            comparison.verify_build_sources(info, ROOT / "experiments/native-compiler")

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
