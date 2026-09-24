"""Large-program corpus: generated starters, function-scoped edits, and acceptance."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from experiments.large_tasks import LARGE_CORPUS, LARGE_TASKS, SOURCES, STAGES
from experiments.runner import function_scope, splice_function
from experiments.tasks import get_tasks
from experiments.verifier import verify

CALLS = {
    "mut": "{name}(&mut a, {run})",
    "read": "{name}(&a, {run})",
    "consume": "{name}(Account {{ balance: a.balance, limit: a.limit, tier: a.tier }}, {run})",
    "pure": "{name}({run})",
}


def solution(task, calls=CALLS, order=None):
    lines, run = [], "v"
    stages = STAGES[task] if order is None else order
    for index, (name, form, _) in enumerate(stages):
        lines.append(f"    let r{index} = {calls[form].format(name=name, run=run)};")
        run = f"r{index}"
    return "fn pipeline(a: &mut Account, v: i32) -> i32 {\n" + "\n".join(lines) + f"\n    return {run};\n}}"


def spliced(task, definition):
    return splice_function(SOURCES[task], "pipeline", definition)


class LargeCorpusTests(unittest.TestCase):
    def test_committed_starters_match_the_generator(self):
        self.assertIs(LARGE_TASKS, get_tasks(LARGE_CORPUS))
        for task, spec in LARGE_TASKS.items():
            with self.subTest(task=task):
                self.assertEqual(SOURCES[task], Path(spec["source"]).read_text(encoding="utf-8"))
                self.assertEqual("pipeline", function_scope(spec))
                self.assertEqual({"mut", "read", "consume", "pure"}, {form for _, form, _ in STAGES[task]})

    def test_splice_replaces_only_the_named_function(self):
        source = "fn a() -> i32 { return 1; }\nfn pipeline(x: i32) -> i32 { return x; }\nfn main() -> i32 { return 0; }\n"
        result = splice_function(source, "pipeline", "fn pipeline(x: i32) -> i32 { if (x > 0) { return 2; } return x; }")
        self.assertIn("if (x > 0) { return 2; }", result)
        self.assertTrue(result.startswith("fn a() -> i32 { return 1; }\n"))
        for bad in ("fn other() -> i32 { return 1; }", "fn pipeline(x: i32) -> i32 { return x; } fn b() -> i32 { return 0; }",
                    "not a function", "fn pipeline(x: i32) -> i32 { return x;"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                splice_function(source, "pipeline", bad)


@unittest.skipUnless(shutil.which("cc"), "Native acceptance requires a C11 compiler named cc")
class LargeAcceptanceTests(unittest.TestCase):
    def test_reference_solutions_pass_and_starters_fail(self):
        for task in LARGE_TASKS:
            with self.subTest(task=task):
                result = verify(task, spliced(task, solution(task)))
                self.assertEqual("passed", result["status"], result["feedback"])
                self.assertEqual("failed", verify(task, SOURCES[task])["status"])

    def test_signature_and_order_mistakes_are_rejected(self):
        task = "pipeline-80"
        mistakes = {
            "implicit reborrow": {**CALLS, "mut": "{name}(a, {run})"},
            "shared borrow for a writer": {**CALLS, "mut": "{name}(&a, {run})"},
            "moving out of a borrow": {**CALLS, "consume": "{name}(a, {run})"},
            "borrowing for a by-value helper": {**CALLS, "consume": "{name}(&a, {run})"},
        }
        for label, calls in mistakes.items():
            with self.subTest(mistake=label):
                self.assertNotEqual("passed", verify(task, spliced(task, solution(task, calls)))["status"])
        reordered = list(reversed(STAGES[task]))
        self.assertEqual("failed", verify(task, spliced(task, solution(task, order=reordered)))["status"])

    def test_runner_splices_function_edits_and_archives_the_whole_file(self):
        task = "pipeline-40"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            script = directory / "adapter.py"
            script.write_text("import json, sys\njson.load(sys.stdin)\nprint(json.dumps({'schema': "
                              "'talven.eval.response.v1', 'edits': {'task.tal': " + repr(solution(task)) +
                              "}, 'usage': None}))\n")
            config = directory / "adapter.json"
            config.write_text(json.dumps({"schema": "talven.eval.adapter.v1", "kind": "fixture", "provider": "none",
                                          "model": "scripted-function-edit-v1", "tokenizer": "none", "settings": {},
                                          "command": [sys.executable, str(script)], "artifacts": [str(script)]}))
            result = subprocess.run([sys.executable, "-m", "experiments", "run", "--corpus", LARGE_CORPUS,
                                     "--task", task, "--adapter", str(config), "--out", str(directory / "run")],
                                    capture_output=True, text=True, timeout=300)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            run = json.loads((directory / "run/run.json").read_text())
            self.assertEqual(["passed", "passed"], [t["status"] for t in run["trials"]])
            trial = run["trials"][0]
            archived = (directory / "run" / trial["id"] / "attempt-000/task.tal").read_text()
            self.assertEqual(spliced(task, solution(task)), archived)
            request = json.loads((directory / "run" / trial["id"] / "attempt-000/request.json").read_text())
            self.assertIn("only the complete new definition of function pipeline", request["messages"][0]["content"])

    def test_other_functions_must_stay_unchanged(self):
        task = "pipeline-40"
        name, form, k = STAGES[task][0]
        source = spliced(task, solution(task))
        edited = source.replace(f"* {k};", f"* {k + 1};", 1)
        self.assertNotEqual(source, edited)
        self.assertEqual("failed", verify(task, edited)["status"])


if __name__ == "__main__":
    unittest.main()
