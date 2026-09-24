import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "experiments", *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)

    def config(self, directory, behavior="repair"):
        script = directory / "adapter.py"
        script.write_text('''import json, sys, time
r = json.load(sys.stdin)
behavior = sys.argv[1]
if behavior == "timeout": time.sleep(10)
if behavior == "invalid": print("not json"); sys.exit(0)
source = "fn main() -> i32 { let count: i32 = 1; return count; }"
if behavior == "fail" or (behavior == "repair" and r["attempt"] == 0):
    source = "fn main() -> i32 { let count: i32 = true; return count; }"
edits = {"task.tal": source}
if behavior == "scope": edits["../marker"] = "bad"
usage = {"input_tokens": 17, "output_tokens": 3, "usage_source": "synthetic test receipt"} if behavior == "billed-error" else None
print(json.dumps({"schema": "talven.eval.response.v1", "edits": edits, "usage": usage}))
if behavior == "billed-error": sys.exit(1)
''', encoding="utf-8")
        config = directory / "adapter.json"
        config.write_text(json.dumps({"schema": "talven.eval.adapter.v1", "kind": "fixture",
             "provider": "none", "model": "scripted-test-v1", "tokenizer": "none",
             "settings": {}, "command": [sys.executable, str(script), behavior], "artifacts": [str(script)]}))
        return config

    def test_cli_runs_both_conditions_and_repetitions_with_bounded_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = self.command("run", "--adapter", self.config(directory), "--out", directory / "run",
                                  "--task", "strict-type", "--context", "both", "--repetitions", 2)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            run = json.loads((directory / "run/run.json").read_text())
            self.assertEqual(4, len(run["trials"]))
            self.assertTrue(all(t["status"] == "passed" for t in run["trials"]))
            self.assertEqual(4, run["summary"]["repair_attempts"])
            self.assertIsNone(run["summary"]["input_tokens"])
            self.assertEqual("fixture", run["measurement_kind"])
            self.assertEqual(0, run["order_seed"])
            self.assertEqual(sorted(run["trial_order"]), sorted(t["id"] for t in run["trials"]))
            self.assertEqual(run["trial_order"], [t["id"] for t in run["trials"]])
            first = next(t for t in run["trials"] if t["context_mode"] == "source")
            request = json.loads((directory / "run" / first["id"] / "attempt-000/request.json").read_text())
            self.assertEqual(["task.tal"], request["allowed_files"])
            self.assertEqual("source", request["context_mode"])
            self.assertNotIn("compiler_context", json.loads(request["messages"][-1]["content"]))
            compiler_trial = next(t for t in run["trials"] if t["context_mode"] == "compiler")
            # Repairs: only the compiler condition receives diagnostic text.
            def repair_feedback(trial):
                repair = json.loads((directory / "run" / trial["id"] / "attempt-001/request.json").read_text())
                return json.loads(repair["messages"][-1]["content"])["feedback"]
            self.assertNotIn("E0201", repair_feedback(first))
            self.assertIn("rejected by the language checks", repair_feedback(first))
            self.assertIn("E0201", repair_feedback(compiler_trial))
            report = json.loads((directory / "run/report.json").read_text())
            self.assertEqual({"conditions": ["source", "compiler"], "pairs": 2, "excluded_error_pairs": 0,
                              "both_passed": 2, "only_source": 0, "only_compiler": 0, "neither": 0,
                              "exact_mcnemar_p": None}, report["paired"])
            self.assertEqual(1.0, report["summary"]["correctness_rate_excluding_errors"])
            self.assertEqual(2, len(report["summary"]["correctness_interval_95_excluding_errors"]))
            compiler_request = json.loads((directory / "run" / compiler_trial["id"] / "attempt-000/request.json").read_text())
            context = json.loads(json.loads(compiler_request["messages"][-1]["content"])["compiler_context"])
            self.assertEqual("talven.agent-context.v1", context["schema"])
            self.assertIn(" E0201 ", context["errors"][0])
            repeated = self.command("run", "--adapter", self.config(directory), "--out", directory / "run")
            self.assertNotEqual(0, repeated.returncode)
            verified = self.command("reverify", directory / "run", "--out", directory / "reverified.json")
            self.assertEqual(0, verified.returncode, verified.stderr + verified.stdout)
            self.assertEqual(4, len(json.loads((directory / "reverified.json").read_text())["trials"]))
            candidate = directory / "run" / first["id"] / "attempt-001/task.tal"
            candidate.write_text("fn main() -> i32 { return 0; }")
            tampered = self.command("reverify", directory / "run", "--out", directory / "tampered.json")
            self.assertEqual(2, tampered.returncode)
            self.assertIn("artifact changed", tampered.stderr)

    def test_failure_and_invalid_edit_stop_at_repair_budget(self):
        for behavior in ("fail", "scope"):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                result = self.command("run", "--adapter", self.config(directory, behavior),
                                      "--out", directory / "run", "--task", "strict-type",
                                      "--context", "source", "--max-repairs", 1)
                self.assertEqual(1, result.returncode, result.stderr + result.stdout)
                run = json.loads((directory / "run/run.json").read_text())
                self.assertEqual(2, len(run["trials"][0]["attempts"]))
                self.assertEqual(0, run["summary"]["correct_tasks"])
                self.assertFalse((directory / "marker").exists())
                # Reverification succeeds when the archived failure reproduces.
                verified = self.command("reverify", directory / "run", "--out", directory / "reverified.json")
                self.assertEqual(0, verified.returncode, verified.stderr + verified.stdout)
                self.assertTrue(json.loads((directory / "reverified.json").read_text())["matches_archive"])

    def test_adapter_error_is_recorded_with_unknown_usage(self):
        for behavior in ("invalid", "timeout"):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                result = self.command("run", "--adapter", self.config(directory, behavior),
                    "--out", directory / "run", "--task", "strict-type", "--context", "source",
                    "--adapter-timeout", "0.2")
                self.assertEqual(2, result.returncode, result.stderr + result.stdout)
                run = json.loads((directory / "run/run.json").read_text())
                self.assertEqual("error", run["trials"][0]["status"])
                self.assertEqual(1, len(run["trials"][0]["attempts"]))
                self.assertIsNone(run["summary"]["input_tokens"])

    def test_context_budget_and_missing_compiler_never_claim_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = self.config(directory)
            budget = self.command("run", "--adapter", config, "--out", directory / "budget",
                                  "--task", "strict-type", "--context", "compiler", "--context-bytes", "1")
            self.assertEqual(2, budget.returncode)
            run = json.loads((directory / "budget/run.json").read_text())
            self.assertEqual(0, run["summary"]["attempts"])
            self.assertEqual(1, run["summary"]["error_tasks"])
            missing = self.command("run", "--adapter", config, "--out", directory / "missing",
                                   "--cc", "/missing/compiler")
            self.assertEqual(2, missing.returncode)
            self.assertFalse((directory / "missing").exists())

    def test_failed_adapter_retains_valid_usage_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config_path = self.config(directory, "billed-error")
            config = json.loads(config_path.read_text())
            # Synthetic live-protocol accounting regression, not a model run.
            config["kind"] = "live"
            config_path.write_text(json.dumps(config))
            refused = self.command("run", "--adapter", config_path, "--out", directory / "uncapped",
                                   "--task", "strict-type", "--context", "source")
            self.assertEqual(2, refused.returncode)
            self.assertIn("--max-cost-usd", refused.stderr)
            self.assertFalse((directory / "uncapped").exists())
            result = self.command("run", "--adapter", config_path, "--out", directory / "run",
                                  "--task", "strict-type", "--context", "both", "--max-cost-usd", "1",
                                  "--allow-dirty")
            self.assertEqual(2, result.returncode)
            run = json.loads((directory / "run/run.json").read_text())
            self.assertEqual(17, run["summary"]["input_tokens"])
            self.assertEqual(3, run["summary"]["output_tokens"])
            self.assertEqual(0, run["summary"]["correct_tasks"])
            # A call with unknown cost stops the run: the cap can no longer be enforced.
            self.assertFalse(run["complete"])
            self.assertEqual({"cap_usd": "1", "spent_usd": "0", "largest_call_usd": "0", "calls": 1,
                              "stopped": "unknown_call_cost"}, run["budget"])
            self.assertEqual(1, len(run["trials"]))

    def test_reverification_never_executes_an_archived_compiler_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = self.command("run", "--adapter", self.config(directory, "success"),
                                  "--out", directory / "run", "--task", "strict-type", "--context", "source")
            self.assertEqual(0, result.returncode, result.stderr)
            untrusted = directory / "untrusted-cc"
            marker = directory / "executed"
            untrusted.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n")
            untrusted.chmod(0o755)
            run_path = directory / "run/run.json"
            run = json.loads(run_path.read_text())
            run["environment"]["cc"] = str(untrusted)
            run_path.write_text(json.dumps(run))
            verified = self.command("reverify", directory / "run", "--out", directory / "reverified.json")
            self.assertEqual(0, verified.returncode, verified.stderr + verified.stdout)
            self.assertFalse(marker.exists())

    def test_report_adds_only_explicit_verification_receipts(self):
        from experiments.runner import make_report
        # This is test data, separate from any fixture/model run artifacts.
        trial = {"id": "strict-type-source-001", "status": "passed", "context_mode": "source",
                 "elapsed_seconds": 2.0, "attempts": [{"usage": {
                    "input_tokens": 10, "output_tokens": 5, "usage_source": "test receipt",
                    "model_cost_usd": "0.02", "model_cost_source": "test bill",
                    "tool_cost_usd": "0", "tool_cost_source": "test: no tool charges"}}]}
        run = {"measurement_kind": "live", "trials": [trial], "complete": True, "planned_trials": 1}
        report = make_report(run)
        self.assertIsNone(report["summary"]["total_task_cost_usd"])
        report = make_report(run, {trial["id"]: {"amount_usd": "0.01", "source": "test compute receipt"}})
        self.assertEqual("0.03", report["summary"]["total_task_cost_usd"])
        with self.assertRaises(ValueError):
            make_report(run, {"wrong-trial": {"amount_usd": "0.01", "source": "test"}})
        run["complete"] = False
        run["planned_trials"] = 4
        interrupted = make_report(run)
        self.assertIsNone(interrupted["summary"]["correctness_rate"])
        self.assertEqual(4, interrupted["planned_trials"])


class HarnessUnitTests(unittest.TestCase):
    def test_trial_plan_is_complete_and_seed_deterministic(self):
        from experiments.runner import trial_plan
        fixed = trial_plan(["a", "b"], ["source", "compiler"], 2, None)
        self.assertEqual((1, "a", "source"), fixed[0])
        shuffled = trial_plan(["a", "b"], ["source", "compiler"], 2, 7)
        self.assertEqual(sorted(fixed), sorted(shuffled))
        self.assertEqual(shuffled, trial_plan(["a", "b"], ["source", "compiler"], 2, 7))
        self.assertNotEqual(fixed, shuffled)

    def test_child_environments_exclude_credentials_and_limit_cpu(self):
        from unittest.mock import patch
        from experiments.process import TOOL_ENVIRONMENT, environment_subset, run_process
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sentinel-key", "PATH": "/usr/bin:/bin"}):
            env = environment_subset(TOOL_ENVIRONMENT)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            result = run_process([sys.executable, "-c", "import os; print(os.environ.get('ANTHROPIC_API_KEY'))"],
                                 cwd=ROOT, timeout=10, env=env)
            self.assertEqual("None", result["stdout"].strip())
        if sys.platform != "win32":
            spin = run_process([sys.executable, "-c", "while True: pass"], cwd=ROOT, timeout=20,
                               cpu_seconds=1, file_bytes=1024)
            self.assertIsNone(spin["error"])
            self.assertLess(spin["elapsed_seconds"], 15)
            self.assertNotEqual(0, spin["returncode"])

    def test_budget_stops_before_a_call_could_exceed_the_cap(self):
        from experiments.runner import Budget, BudgetExhausted
        budget = Budget("1")
        budget.before_call()
        budget.after_call({"model_cost_usd": "0.4", "model_cost_source": "test"})
        budget.before_call()
        budget.after_call({"model_cost_usd": "0.4", "model_cost_source": "test"})
        with self.assertRaises(BudgetExhausted):
            budget.before_call()  # 0.8 spent + 0.4 largest call > 1.
        self.assertEqual("spend_cap", budget.record()["stopped"])
