import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.process import run_process
from experiments.protocol import candidate_source, parse_response, strict_json


class ProtocolTests(unittest.TestCase):
    def test_only_source_edits_are_accepted(self):
        for edits in ({"../task.tal": "x"}, {"task.tal": "x", "tests/test.py": "pass"},
                      {"/tmp/task.tal": "x"}, {}, {"task.tal": 7}, {"task.tal": "x" * 262145},
                      {"task.tal": "\ud800"}):
            with self.subTest(edits=str(edits)[:70]), self.assertRaises(ValueError):
                candidate_source({"edits": edits})

    def test_scope_rejection_does_not_lose_reported_usage(self):
        response, usage = parse_response(json.dumps({"schema": "talven.eval.response.v1",
            "edits": {"tests.py": ""}, "usage": {"input_tokens": 30, "usage_source": "test"}}))
        self.assertEqual(30, usage["input_tokens"])
        with self.assertRaises(ValueError):
            candidate_source(response)

    def test_ambiguous_or_nonfinite_json_is_rejected(self):
        for text in ('{"edits":{},"edits":{}}', '{"count":NaN}', '{"cost":Infinity}',
                     '{"edits":{"task.tal":"\\ud800"}}', '{"settings":{"temperature":1e999}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)

    def test_process_times_out_and_captures_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_process([sys.executable, "-c", "import time; time.sleep(10)"],
                                 cwd=temporary, timeout=0.1)
            self.assertEqual("timeout", result["error"])
            self.assertLess(result["elapsed_seconds"], 3)
            result = run_process(["/missing/talven-eval-command"], cwd=temporary, timeout=1)
            self.assertIn("launch:", result["error"])

    def test_process_output_is_bounded_and_argv_never_uses_a_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_process([sys.executable, "-c", "print('x' * 100000)"],
                                 cwd=temporary, timeout=3, max_bytes=100)
            self.assertEqual("output_limit", result["error"])
            self.assertEqual(100, len(result["stdout"]))
            result = run_process([sys.executable, "-c", "import sys; print(sys.argv[1])", "; touch marker"],
                                 cwd=temporary, timeout=3)
            self.assertEqual("; touch marker\n", result["stdout"])
            self.assertFalse((Path(temporary) / "marker").exists())

    def test_invalid_utf8_output_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_process([sys.executable, "-c", "import os; os.write(1, bytes([255]))"],
                                 cwd=temporary, timeout=3)
            self.assertEqual("invalid_utf8", result["error"])
            self.assertEqual("/w==", result["stdout_base64"])

    def test_interruption_reaps_the_actual_adapter_process(self):
        import subprocess
        processes = []
        popen = subprocess.Popen

        def capture(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            return process

        try:
            with tempfile.TemporaryDirectory() as temporary, patch("experiments.process.subprocess.Popen", side_effect=capture), \
                    patch("experiments.process.time.sleep", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run_process([sys.executable, "-c", "import time; time.sleep(60)"], cwd=temporary, timeout=2)
            self.assertIsNotNone(processes[0].poll(), "Interrupted adapter was left alive")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait()
