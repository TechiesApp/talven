import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from experiments.tooling_workloads import workloads
from talven.context import compiler_hash
from talven.formatter import format_source
from talven.frontend import analyze

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("measure_tooling", ROOT / "scripts/measure-tooling.py")
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


class BaselineTests(unittest.TestCase):
    def test_fixed_workloads_have_canonical_source_and_valid_distinct_candidates(self):
        self.assertEqual(["vectors", "borrowing", "chain-32", "chain-128"], [w["id"] for w in workloads()])
        for workload in workloads():
            with self.subTest(workload=workload["id"]):
                source = workload["source"].decode()
                self.assertEqual(source, format_source(source))
                analysis = analyze(source + baseline.CANDIDATE_SUFFIX.decode())
                self.assertIn("baseline_added", analysis.functions)
                self.assertIn("tv_f_main", workload["oracle"].decode())

    def test_preflight_rejects_invalid_limits_missing_tools_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = str(Path(temporary) / "fresh")
            for changes in ({"repetitions": 0}, {"repetitions": 101}, {"warmups": -1},
                            {"warmups": 11}, {"timeout": float("nan")}, {"timeout": float("inf")},
                            {"timeout": 0}, {"timeout": 301}, {"out": ""}, {"out": temporary},
                            {"cc": "talven-nonexistent-compiler"}):
                args = dict(out=output, repetitions=1, warmups=0, timeout=10, cc="cc", expect_arch=None)
                args.update(changes)
                with self.subTest(changes=changes), self.assertRaises(baseline.MeasurementError):
                    baseline.preflight(**args)
            self.assertFalse(Path(output).exists())
            with mock.patch.object(baseline.platform, "machine", return_value="x86_64"), \
                 self.assertRaisesRegex(baseline.MeasurementError, "actual x86_64"):
                baseline.preflight(output, 1, 0, 10, "cc", "aarch64")

    def test_summary_excludes_warmups_and_verification_and_rejects_missing_samples(self):
        samples = []
        for workload in workloads():
            for operation in baseline.OPERATIONS:
                for value in (10, 30, 20):
                    samples.append({"phase": "measured", "workload": workload["id"], "operation": operation,
                                    "verified": True, "elapsed_ns": value, "stdout": {"bytes": 12},
                                    "artifact": {"bytes": 100}})
        samples.extend([{**samples[0], "phase": "warmup", "elapsed_ns": 1000000},
                        {**samples[0], "phase": "verification", "elapsed_ns": 2000000}])
        result = baseline.summarize(samples, 3)
        self.assertEqual(32, len(result))
        self.assertTrue(all(row["median_ns"] == 20 and row["min_ns"] == 10 and row["max_ns"] == 30 for row in result))
        with self.assertRaises(baseline.MeasurementError):
            baseline.summarize(samples[1:], 3)
        samples[0]["verified"] = False
        with self.assertRaises(baseline.MeasurementError):
            baseline.summarize(samples, 3)

    def recorder(self, root, timeout=5):
        (root / "commands").mkdir()
        return baseline.Recorder(root, {"commands": [], "passed": False, "summary": None}, timeout)

    def test_command_captures_raw_bytes_with_hashes_and_checks_outside_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = self.recorder(Path(temporary))
            output, entry = recorder.command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([195,169,10]))"], phase="measured")
            self.assertEqual(b"\xc3\xa9\n", output)
            self.assertEqual(3, entry["stdout"]["bytes"])
            self.assertEqual(baseline.digest(output), entry["stdout"]["sha256"])
            self.assertEqual(output, (Path(temporary) / entry["stdout"]["path"]).read_bytes())
            self.assertGreater(entry["elapsed_ns"], 0)
            self.assertFalse(entry["verified"])

    def test_failed_exit_launch_and_timeout_retain_incomplete_evidence(self):
        commands = [([sys.executable, "-c", "print('partial'); raise SystemExit(3)"], 5, None, 3),
                    ([sys.executable, "-c", "import time; print('partial', flush=True); time.sleep(10)"], .2, "timeout", None),
                    (["talven-no-such-executable"], 5, "launch:", None)]
        for argv, timeout, error, returncode in commands:
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as temporary:
                recorder = self.recorder(Path(temporary), timeout)
                with self.assertRaises(baseline.MeasurementError):
                    recorder.command(argv)
                report = json.loads((Path(temporary) / "report.json").read_text())
                self.assertFalse(report["passed"])
                self.assertIsNone(report["summary"])
                entry = report["commands"][0]
                self.assertFalse(entry["verified"])
                if error:
                    self.assertTrue(entry["error"].startswith(error))
                if returncode:
                    self.assertEqual(returncode, entry["returncode"])

    def test_semantic_and_determinism_checks_reject_false_success(self):
        source, candidate = b"source", b"candidate"
        for operation, output in (("check", b'{"schema":"talven.diagnostics.v1","ok":false,"diagnostics":[]}'),
                                  ("context", b'{}'), ("snapshot", b'{}'), ("validate", b'{}'),
                                  ("format", b"changed"), ("emit-c", b"")):
            with self.subTest(operation=operation), self.assertRaises(baseline.MeasurementError):
                baseline.check_output(operation, output, source, candidate, "a" * 64)
        with self.assertRaisesRegex(baseline.MeasurementError, "changed between"):
            baseline.check_output("emit-c", b"first", source, candidate, "a" * 64, b"second")

    def test_failure_after_output_creation_saves_no_summary(self):
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(baseline, "input_files", side_effect=baseline.MeasurementError("input drift")):
            output = Path(temporary) / "run"
            with mock.patch.object(baseline, "preflight", return_value=(output, "/fake/cc", "aarch64")):
                report = baseline.run(str(output))
            self.assertFalse(report["complete"])
            self.assertFalse(report["passed"])
            self.assertIsNone(report["summary"])
            self.assertEqual("input drift", json.loads((output / "report.json").read_text())["error"])


@unittest.skipUnless(shutil.which("cc"), "Tooling baseline acceptance requires native cc")
class NativeBaselineTests(unittest.TestCase):
    def test_complete_cli_suite_preserves_sources_and_records_actual_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "baseline"
            before = {p: p.read_bytes() for p in (ROOT / "examples").glob("*.tal")}
            completed = subprocess.run([sys.executable, str(ROOT / "scripts/measure-tooling.py"),
                                        "--out", str(output), "--repetitions", "1", "--warmups", "0"],
                                       cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            report = json.loads((output / "report.json").read_text())
            self.assertTrue(report["complete"] and report["passed"])
            self.assertEqual(32, len(report["summary"]))
            self.assertTrue(all(w["native_verified"] for w in report["workloads"]))
            self.assertEqual(compiler_hash(), report["compiler_hash"])
            self.assertTrue(report["host"]["cc"]["target"])
            for sample in report["commands"]:
                for stream in ("stdout", "stderr"):
                    self.assertEqual(baseline.fingerprint(output / sample[stream]["path"]),
                                     {key: sample[stream][key] for key in ("bytes", "sha256")})
            for name, fact in report["inputs"].items():
                self.assertEqual(fact, baseline.fingerprint(output / "inputs" / name))
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            again = subprocess.run([sys.executable, str(ROOT / "scripts/measure-tooling.py"), "--out", str(output)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertEqual(1, again.returncode)
            self.assertIn("already exists", again.stderr)

    def test_native_oracle_rejects_type_valid_wrong_program_before_measurement(self):
        workload = workloads()[0]
        workload["source"] = ("struct Vec2 {\n    x: i32,\n    y: i32\n}\n\n"
                              "fn dot(a: Vec2, b: Vec2) -> i32 {\n    return 0;\n}\n\n"
                              "fn main() -> i32 {\n    return 0;\n}\n").encode()
        analyze(workload["source"].decode())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "commands").mkdir()
            report = {"commands": [], "workloads": []}
            recorder = baseline.Recorder(output, report, 30)
            with self.assertRaisesRegex(baseline.MeasurementError, "failed"):
                baseline.measure_workload(recorder, workload, shutil.which("cc"), compiler_hash(), 1, 0)
            self.assertFalse(report["workloads"][0]["native_verified"])
            self.assertFalse(any(c["phase"] == "measured" for c in report["commands"]))
            self.assertEqual(1, report["commands"][-1]["returncode"])


if __name__ == "__main__":
    unittest.main()
