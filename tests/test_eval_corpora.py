import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import CORPUS_VERSION, SCHEMA
from experiments.__main__ import main
from experiments import runner
from experiments.protocol import digest, encode
from experiments.tasks import CORPORA, TASKS, get_tasks


BORROWING_CORPUS = "m1c-borrowing-tasks-v1"
LIMITS = {"max_repairs": 0, "context_bytes": 16384, "adapter_timeout": 5,
          "native_timeout": 5, "verification_timeout": 5, "task_timeout": 30}


def archive(corpus_version=CORPUS_VERSION, **changes):
    return {"schema": SCHEMA, "corpus_version": corpus_version,
            "measurement_kind": "fixture", "complete": True, "planned_trials": 0,
            "trials": [], "task_order": [], "input_hashes": {}, "limits": LIMITS,
            **changes}


class CorpusTests(unittest.TestCase):
    def test_original_public_corpus_and_order_are_unchanged(self):
        self.assertEqual("m1c-agent-tasks-v1", CORPUS_VERSION)
        self.assertIs(TASKS, get_tasks())
        self.assertIs(TASKS, CORPORA[CORPUS_VERSION])
        self.assertEqual(["move-scalar", "strict-type", "rename-field", "squared-length"], list(TASKS))
        # Pin the existing version's exact public source paths and instructions.
        serialized = json.dumps(TASKS, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual("ffd1ddbf5a865efdb8d91ee73d94781c251da789f0edee936d2b32e494ca5622",
                         hashlib.sha256(serialized).hexdigest())
        self.assertEqual(["borrow-overlap", "borrow-permission", "borrow-reborrow", "borrow-order"],
                         list(get_tasks(BORROWING_CORPUS)))
        self.assertFalse(TASKS.keys() & get_tasks(BORROWING_CORPUS).keys())

    def test_tasks_cli_defaults_to_original_and_selects_named_corpus(self):
        for arguments, version in ((["tasks"], CORPUS_VERSION),
                                   (["tasks", "--corpus", BORROWING_CORPUS], BORROWING_CORPUS)):
            with self.subTest(corpus=version), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(0, main(arguments))
                self.assertEqual(get_tasks(version), json.loads(output.getvalue()))

    def test_run_cli_preserves_default_order_and_selects_corpus_order(self):
        for version in CORPORA:
            with self.subTest(corpus=version), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "run"
                arguments = ["run", "--adapter", "unused.json", "--out", str(output)]
                if version != CORPUS_VERSION:
                    arguments.extend(["--corpus", version])
                result = archive(version)
                result["summary"] = runner.make_report(result)["summary"]
                with patch("experiments.__main__.run_experiment", return_value=result) as execute, \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(0, main(arguments))
                self.assertEqual(list(get_tasks(version)), execute.call_args.args[2])
                self.assertEqual(["source", "compiler"], execute.call_args.args[3])
                self.assertEqual(1, execute.call_args.args[4])
                self.assertEqual(version, execute.call_args.kwargs["corpus_version"])
                self.assertFalse(output.exists())

    def test_mismatched_cli_tasks_fail_before_adapter_environment_or_output(self):
        for version, task in ((CORPUS_VERSION, "borrow-overlap"),
                              (BORROWING_CORPUS, "strict-type"),
                              (BORROWING_CORPUS, "not-a-task")):
            with self.subTest(corpus=version, task=task), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "run"
                with patch.object(runner, "read_config") as config, \
                        patch.object(runner, "environment") as environment, \
                        patch.object(runner, "run_process") as process, \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(2, main(["run", "--adapter", "missing.json", "--out", str(output),
                                               "--corpus", version, "--task", task]))
                self.assertIn("not in corpus", errors.getvalue())
                config.assert_not_called()
                environment.assert_not_called()
                process.assert_not_called()
                self.assertFalse(output.exists())

    def test_programmatic_selection_is_validated_before_side_effects(self):
        for version, tasks in (("unknown", ["strict-type"]),
                               (CORPUS_VERSION, ["borrow-overlap"]),
                               (BORROWING_CORPUS, ["strict-type"]),
                               (CORPUS_VERSION, ["strict-type", "strict-type"])):
            with self.subTest(corpus=version, tasks=tasks), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "run"
                with patch.object(runner, "read_config") as config, \
                        patch.object(runner, "environment") as environment:
                    with self.assertRaises(ValueError):
                        runner.run_experiment("missing.json", output, tasks, ["source"], 1, "cc", LIMITS,
                                              corpus_version=version)
                config.assert_not_called()
                environment.assert_not_called()
                self.assertFalse(output.exists())

    def test_unknown_corpus_is_rejected_by_registry_cli_and_archive_loader(self):
        for value in ("unknown", None, [], 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Unsupported evaluation corpus"):
                get_tasks(value)
        for arguments in (["tasks", "--corpus", "unknown"],
                          ["run", "--adapter", "missing.json", "--out", "unused", "--corpus", "unknown"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(arguments)
                self.assertEqual(2, error.exception.code)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            runner.write_json(directory / "run.json", archive("unknown"))
            with self.assertRaisesRegex(ValueError, "Unsupported evaluation corpus"):
                runner.load_run(directory)

    def test_selected_requests_archives_reports_and_reverification_share_provenance(self):
        # Mock only external infrastructure; exercise request creation, archiving,
        # accounting, candidate integrity, and reverification routing offline.
        for version, task in ((CORPUS_VERSION, "strict-type"), (BORROWING_CORPUS, "borrow-overlap")):
            with self.subTest(corpus=version), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                config_path = directory / "adapter.json"
                config_path.write_text("{}", encoding="utf-8")
                config = {"kind": "fixture", "provider": "none", "model": "test-fixture",
                          "tokenizer": "none", "settings": {}, "artifact_hashes": {}, "command": ["fixture"]}
                source = "fn main() -> i32 { return 0; }\n"
                inputs = {name: f"Pinned guide: {name}".encode() for name in runner.GUIDES}
                inputs[get_tasks(version)[task]["source"]] = source.encode()
                response = encode({"schema": "talven.eval.response.v1", "edits": {"task.tal": source},
                                   "usage": None})
                with patch.object(runner, "read_config", return_value=config), \
                        patch.object(runner, "environment", return_value={"cc": "trusted-cc"}), \
                        patch.object(runner, "pinned_files", return_value=inputs) as pin, \
                        patch.object(runner, "compiler_context", return_value="test compiler context"), \
                        patch.object(runner, "run_process", return_value={"stdout": response, "stderr": "",
                                     "returncode": 0, "error": None}) as process, \
                        patch.object(runner, "verify_candidate", return_value={"status": "passed"}) as verify:
                    kwargs = {} if version == CORPUS_VERSION else {"corpus_version": version}
                    run = runner.run_experiment(config_path, directory / "run", [task], ["source", "compiler"],
                                                1, "cc", LIMITS, **kwargs)
                    loaded = runner.load_run(directory / "run")
                    self.assertEqual(run, loaded)
                    self.assertEqual(version, run["corpus_version"])
                    self.assertEqual([task], run["task_order"])
                    self.assertEqual(2, run["planned_trials"])
                    self.assertEqual(2, process.call_count)
                    for trial in run["trials"]:
                        request_path = directory / "run" / trial["id"] / "attempt-000/request.json"
                        request_bytes = request_path.read_bytes()
                        request = json.loads(request_bytes)
                        self.assertEqual(version, request["corpus_version"])
                        self.assertEqual(task, request["task_id"])
                        self.assertEqual(digest(request_bytes), trial["attempts"][0]["request_sha256"])
                        payload = json.loads(request["messages"][-1]["content"])
                        self.assertEqual(get_tasks(version)[task]["instruction"], payload["instruction"])
                        self.assertEqual(source, payload["source"])
                        self.assertEqual(trial["context_mode"] == "compiler", "compiler_context" in payload)
                    report = runner.make_report(loaded)
                    self.assertEqual(version, report["corpus_version"])
                    self.assertIsNone(report["summary"]["input_tokens"])
                    self.assertIsNone(report["summary"]["total_task_cost_usd"])
                    saved_report = json.loads((directory / "run/report.json").read_text())
                    self.assertEqual(report, saved_report)
                    reverification = runner.reverify(directory / "run")
                    self.assertEqual(version, reverification["corpus_version"])
                    self.assertTrue(all(t["status"] == "passed" for t in reverification["trials"]))
                    self.assertEqual(4, verify.call_count)
                    self.assertTrue(all(call.args[0] == task for call in verify.call_args_list))
                    self.assertTrue(all(call.args == (version,) for call in pin.call_args_list))

    def test_pins_select_sources_and_require_every_current_compiler_and_harness_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {*runner.GUIDES, "talven/frontend.py", "experiments/runner.py", "experiments/borrowing_tasks.py"}
            for corpus in CORPORA.values():
                paths.update(task["source"] for task in corpus.values())
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"Original input: {name}\n", encoding="utf-8")
            with patch.object(runner, "ROOT", root):
                original = {name: digest(data) for name, data in runner.pinned_files().items()}
                borrowing = {name: digest(data) for name, data in runner.pinned_files(BORROWING_CORPUS).items()}
                self.assertNotEqual(original, borrowing)
                original_sources = {task["source"] for task in TASKS.values()}
                borrowing_sources = {task["source"] for task in get_tasks(BORROWING_CORPUS).values()}
                self.assertEqual(original_sources - borrowing_sources, original.keys() - borrowing.keys())
                self.assertEqual(borrowing_sources - original_sources, borrowing.keys() - original.keys())
                for name in ("talven/frontend.py", "experiments/runner.py", "experiments/borrowing_tasks.py"):
                    self.assertIn(name, original)
                    self.assertIn(name, borrowing)
                with self.assertRaisesRegex(ValueError, "Pinned compiler"):
                    runner.assert_unchanged(original, corpus_version=BORROWING_CORPUS)
                source = next(iter(borrowing_sources - original_sources))
                (root / source).write_text("Changed borrowing source", encoding="utf-8")
                runner.assert_unchanged(original)
                with self.assertRaisesRegex(ValueError, "Pinned compiler"):
                    runner.assert_unchanged(borrowing, corpus_version=BORROWING_CORPUS)
                (root / "experiments/borrowing_tasks.py").write_text("Changed acceptance input", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Pinned compiler"):
                    runner.assert_unchanged(original)

    def test_reverification_rejects_cross_corpus_metadata_before_any_verification(self):
        valid = {"id": "borrow-overlap-source-001", "task": "borrow-overlap", "context_mode": "source",
                 "repetition": 1, "attempts": []}
        foreign = {**valid, "id": "strict-type-source-001", "task": "strict-type"}
        cases = [archive(BORROWING_CORPUS, trials=[valid, foreign]),
                 archive(BORROWING_CORPUS, trials=[{**valid, "id": foreign["id"]}]),
                 archive(BORROWING_CORPUS, task_order=["strict-type"]),
                 archive(CORPUS_VERSION, trials=[valid])]
        for run in cases:
            with self.subTest(run=run), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                runner.write_json(directory / "run.json", run)
                with patch.object(runner, "environment") as environment, \
                        patch.object(runner, "assert_unchanged") as unchanged, \
                        patch.object(runner, "verify_candidate") as verify:
                    with self.assertRaises(ValueError):
                        runner.reverify(directory)
                environment.assert_not_called()
                unchanged.assert_not_called()
                verify.assert_not_called()

    def test_historical_original_reports_work_without_weakening_reverification_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            historical = archive(input_hashes={"experiments/runner.py": "historical-hash"})
            runner.write_json(directory / "run.json", historical)
            report = runner.make_report(runner.load_run(directory))
            self.assertEqual(CORPUS_VERSION, report["corpus_version"])
            with patch.object(runner, "pinned_files", return_value={"experiments/runner.py": b"current source"}), \
                    patch.object(runner, "environment") as environment:
                with self.assertRaisesRegex(ValueError, "Pinned compiler"):
                    runner.reverify(directory)
                environment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
