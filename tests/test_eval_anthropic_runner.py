"""Offline Messages fixtures pass through the real runner and native acceptance."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiments.metrics import MEASUREMENTS
from experiments.protocol import encode


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "experiments/adapters/anthropic_messages.py"
FIXTURE = ROOT / "tests/fixtures/anthropic_messages.json"
SENTINEL = "test-only-key-never-send-or-archive"


class AnthropicRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        guard = self.directory / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import socket\n"
            "def blocked(*args, **kwargs):\n"
            "    raise RuntimeError('offline test forbids network')\n"
            "socket.create_connection = blocked\n"
            "socket.socket.connect = blocked\n"
            "socket.socket.connect_ex = blocked\n", encoding="utf-8")
        self.environment = {**os.environ, "PYTHONPATH": str(guard),
                            "ANTHROPIC_API_KEY": SENTINEL}

    def command(self, *arguments):
        result = subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT,
                                env=self.environment, capture_output=True, text=True, timeout=120)
        self.assertNotIn(SENTINEL, result.stdout + result.stderr)
        return result

    def configure(self, name, fixture=FIXTURE):
        config = self.directory / f"{name}.json"
        result = self.command(ADAPTER, "--fixture", fixture, "--write-config", config,
                              "--model", "fixture-messages-v1", "--tokenizer", "fixture: no tokenizer")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        value = json.loads(config.read_text())
        self.assertEqual("fixture", value["kind"])
        self.assertEqual("anthropic", value["provider"])
        self.assertIn(str(fixture.resolve()), value["artifacts"])
        self.assertIn(str(ADAPTER), value["artifacts"])
        self.assertNotIn(SENTINEL, config.read_text())
        return config

    def run_fixture(self, name, config, task="strict-type", corpus="m1c-agent-tasks-v1", context="source"):
        output = self.directory / name
        result = self.command("-m", "experiments", "run", "--corpus", corpus, "--task", task,
                              "--context", context, "--adapter", config, "--out", output,
                              "--max-repairs", "1")
        run = json.loads((output / "run.json").read_text())
        self.assertTrue(run["complete"])
        self.assertEqual("fixture", run["measurement_kind"])
        self.assertEqual(corpus, run["corpus_version"])
        self.assertEqual("fixture-messages-v1", run["adapter"]["model"])
        for field in MEASUREMENTS:
            self.assertIsNone(run["summary"][field])
        for trial in run["trials"]:
            for attempt in trial["attempts"]:
                self.assertIsNone(attempt["usage"])
        for path in output.rglob("*"):
            if path.is_file():
                self.assertNotIn(SENTINEL.encode(), path.read_bytes(), str(path))
        return result, run, output

    def changed_fixture(self, name, modify):
        fixture = json.loads(FIXTURE.read_text())
        modify(fixture["responses"]["strict-type"])
        path = self.directory / f"{name}-fixture.json"
        path.write_text(encode(fixture), encoding="utf-8")
        return path

    def test_both_corpora_and_contexts_repair_archive_and_reverify_offline(self):
        from experiments.adapters.anthropic_messages import build_request

        # Confirm that the subprocess guard really prevents Python network use.
        guard = self.command("-c", "import socket; socket.create_connection(('example.invalid', 443))")
        self.assertNotEqual(0, guard.returncode)
        self.assertIn("offline test forbids network", guard.stderr)
        config = self.configure("adapter")
        for task, corpus in (("strict-type", "m1c-agent-tasks-v1"),
                             ("borrow-permission", "m1c-borrowing-tasks-v1")):
            with self.subTest(task=task):
                result, run, output = self.run_fixture(task, config, task, corpus, "both")
                self.assertEqual(0, result.returncode, result.stderr + result.stdout)
                self.assertEqual(2, run["summary"]["correct_tasks"])
                self.assertEqual(4, run["summary"]["attempts"])
                self.assertEqual(2, run["summary"]["repair_attempts"])
                self.assertEqual({"source", "compiler"}, {t["context_mode"] for t in run["trials"]})
                for trial in run["trials"]:
                    self.assertEqual(["failed", "passed"], [a["status"] for a in trial["attempts"]])
                    for index in range(2):
                        directory = output / trial["id"] / f"attempt-{index:03d}"
                        request = json.loads((directory / "request.json").read_text())
                        response = json.loads((directory / "response.txt").read_text())
                        self.assertTrue(response["provider_metadata"]["synthetic"])
                        expected = hashlib.sha256(encode(build_request(request)).encode("utf-8")).hexdigest()
                        self.assertEqual(expected, response["provider_metadata"]["request_sha256"])
                        self.assertEqual(2 + 2 * index, len(request["messages"]))
                for artifact in (ADAPTER, FIXTURE):
                    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                    self.assertEqual(digest, run["adapter"]["artifact_hashes"][str(artifact)])
                    self.assertEqual(artifact.read_bytes(), (output / "adapter-artifacts" / digest).read_bytes())
                verified = self.directory / f"{task}-verified.json"
                check = self.command("-m", "experiments", "reverify", output, "--out", verified)
                self.assertEqual(0, check.returncode, check.stderr + check.stdout)
                self.assertEqual(["passed", "passed"], [t["status"] for t in json.loads(verified.read_text())["trials"]])

    def test_invalid_completed_json_is_a_repairable_candidate(self):
        fixture = self.changed_fixture("invalid-json", lambda entries: entries[0]["body"]["content"][0].update(text="{invalid"))
        result, run, output = self.run_fixture("repair", self.configure("adapter", fixture))
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual(["failed", "passed"], [a["status"] for a in run["trials"][0]["attempts"]])
        response = json.loads((output / run["trials"][0]["id"] / "attempt-000/response.txt").read_text())
        self.assertEqual({}, response["edits"])
        self.assertIn("candidate_error", response["provider_metadata"])

    def test_incomplete_or_refused_response_stops_without_accepting_an_edit(self):
        for reason in ("max_tokens", "refusal"):
            with self.subTest(reason=reason):
                def modify(entries):
                    entries[0] = entries[1]  # Even a correct edit is invalid on a failed response.
                    entries[0]["body"]["stop_reason"] = reason
                fixture = self.changed_fixture(reason, modify)
                result, run, output = self.run_fixture(reason, self.configure(f"adapter-{reason}", fixture))
                self.assertEqual(2, result.returncode)
                self.assertEqual(1, run["summary"]["error_tasks"])
                self.assertEqual(1, run["summary"]["attempts"])
                self.assertEqual(0, run["summary"]["repair_attempts"])
                self.assertFalse((output / run["trials"][0]["id"] / "attempt-000/task.tal").exists())

    def test_fixture_exhaustion_is_an_error_without_repeating_a_response(self):
        fixture = self.changed_fixture("exhausted", lambda entries: entries.pop())
        result, run, _ = self.run_fixture("exhaustion", self.configure("adapter", fixture))
        self.assertEqual(2, result.returncode)
        self.assertEqual(["failed", "error"], [a["status"] for a in run["trials"][0]["attempts"]])
        self.assertEqual(2, run["summary"]["attempts"])


if __name__ == "__main__":
    unittest.main()
