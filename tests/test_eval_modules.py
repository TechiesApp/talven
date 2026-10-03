"""Multi-file corpus acceptance, immutable inputs and bounded prompt integration."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from experiments.module_tasks import DEPENDENCIES, MODULE_CORPUS, MODULE_TASKS, SOURCES, STAGES
from experiments.runner import pinned_files, splice_function, task_context
from experiments.tasks import get_tasks
from experiments.verifier import verify
from talven.project import analyze_project


def solution(task, *, order=None, copy_back=True, wrong_type=False):
    lines, running = [], "v"
    for i, (name, form, _, module) in enumerate(STAGES[task] if order is None else order):
        record = f"Ledger{1 - module if wrong_type else module}"
        if form != "pure":
            lines.append(f"    let {'mut ' if form == 'mut' else ''}owner{i} = {record} {{ balance: a.balance, limit: a.limit, tier: a.tier }};")
        arg = {"mut": f"&mut owner{i}, ", "read": f"&owner{i}, ", "consume": f"owner{i}, ", "pure": ""}[form]
        lines.append(f"    let r{i} = call_{name}({arg}{running});")
        if form == "mut" and copy_back:
            for field in ("balance", "limit", "tier"):
                lines.append(f"    a.{field} = owner{i}.{field};")
        running = f"r{i}"
    return "fn pipeline(a: &mut Account, v: i32) -> i32 {\n" + "\n".join(lines) + f"\n    return {running};\n}}"


def spliced(task, **options):
    return splice_function(SOURCES[task], "pipeline", solution(task, **options))


class ModuleCorpusTests(unittest.TestCase):
    def test_starters_dependencies_and_guides_are_pinned(self):
        self.assertIs(MODULE_TASKS, get_tasks(MODULE_CORPUS))
        inputs = pinned_files(MODULE_CORPUS)
        self.assertIn("docs/module-reference.md", inputs)
        for task, spec in MODULE_TASKS.items():
            self.assertEqual(SOURCES[task], inputs[spec["source"]].decode())
            for name, path in spec["dependencies"].items():
                self.assertEqual(DEPENDENCIES[task][name], inputs[path].decode())
            analyze_project("task.tal", {"task.tal": SOURCES[task], **DEPENDENCIES[task]})

    def test_context_has_module_identity_and_alias_contracts(self):
        task = "module-pipeline-8"
        text = task_context(MODULE_TASKS[task], SOURCES[task], DEPENDENCIES[task], 65536)
        context = json.loads(text)
        self.assertEqual("talven.project-context.v1", context["schema"])
        self.assertIn("ledger0.tal::Account", text)
        self.assertIn("ledger1.tal::Account", text)
        invalid = spliced(task, wrong_type=True)
        errors = json.loads(task_context(MODULE_TASKS[task], invalid, DEPENDENCIES[task], 65536))
        self.assertEqual("task.tal", errors["diagnostics"][0]["file"])
        with self.assertRaises(ValueError):
            task_context(MODULE_TASKS[task], SOURCES[task], DEPENDENCIES[task], 1)


@unittest.skipUnless(shutil.which("cc"), "Native module acceptance requires cc")
class ModuleAcceptanceTests(unittest.TestCase):
    def test_solutions_pass_starters_fail_and_bad_nominal_types_fail(self):
        for task in MODULE_TASKS:
            with self.subTest(task=task):
                result = verify(task, spliced(task))
                self.assertEqual("passed", result["status"], result["feedback"])
                self.assertEqual("failed", verify(task, SOURCES[task])["status"])
                result = verify(task, spliced(task, wrong_type=True))
                self.assertEqual("failed", result["status"])
                self.assertFalse(result["checks"][0]["passed"])

    def test_call_trace_rejects_reordering_missing_extra_and_decorative_calls(self):
        task = "module-pipeline-8"
        for order in (list(reversed(STAGES[task])), STAGES[task][1:], STAGES[task] + STAGES[task][:1]):
            with self.subTest(order=order):
                self.assertEqual("failed", verify(task, spliced(task, order=order))["status"])
        decorative = "fn pipeline(a: &mut Account, v: i32) -> i32 { if (false) {\n" + solution(task).split("{", 1)[1]
        # A never-executed correct pipeline must not count as required work.
        decorative = decorative.rsplit("}", 1)[0] + "}\nreturn v;\n}"
        self.assertEqual("failed", verify(task, splice_function(SOURCES[task], "pipeline", decorative))["status"])
        self.assertEqual("failed", verify(task, spliced(task, copy_back=False))["status"])

    def test_imports_and_other_declarations_are_immutable(self):
        task = "module-pipeline-8"
        source = spliced(task)
        for edited in (source.replace('return pipeline(&mut a, 0);', 'return 0;'),
                       source.replace('balance: 10', 'balance: 11')):
            self.assertNotEqual(source, edited)
            self.assertEqual("failed", verify(task, edited)["status"])

    def test_fixture_runner_retains_equal_read_only_sources_and_reverifies(self):
        task = "module-pipeline-8"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            script = directory / "adapter.py"
            script.write_text("import json, sys\nr = json.load(sys.stdin)\nprint(json.dumps({'schema': "
                              "'talven.eval.response.v1', 'edits': {'task.tal': " + repr(solution(task)) +
                              "}, 'usage': None}))\n")
            config = directory / "adapter.json"
            config.write_text(json.dumps({"schema": "talven.eval.adapter.v1", "kind": "fixture", "provider": "none",
                                          "model": "module-function-fixture-v1", "tokenizer": "none", "settings": {},
                                          "command": [sys.executable, str(script)], "artifacts": [str(script)]}))
            result = subprocess.run([sys.executable, "-m", "experiments", "run", "--corpus", MODULE_CORPUS,
                                     "--task", task, "--context-bytes", "65536", "--adapter", str(config),
                                     "--out", str(directory / "run")], capture_output=True, text=True, timeout=180)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            run = json.loads((directory / "run/run.json").read_text())
            self.assertEqual("m1-local-modules-v1", run["environment"]["language_profile"])
            requests = {}
            for trial in run["trials"]:
                self.assertEqual("passed", trial["status"])
                request = json.loads((directory / "run" / trial["id"] / "attempt-000/request.json").read_text())
                requests[trial["context_mode"]] = json.loads(request["messages"][-1]["content"])
                self.assertIn("module-reference.md", request["messages"][0]["content"])
            self.assertEqual(DEPENDENCIES[task], requests["source"]["read_only_sources"])
            self.assertEqual(requests["source"]["read_only_sources"], requests["compiler"]["read_only_sources"])
            self.assertNotIn("compiler_context", requests["source"])
            self.assertIn("compiler_context", requests["compiler"])
            result = subprocess.run([sys.executable, "-m", "experiments", "reverify", str(directory / "run"), "--out", str(directory / "reverified.json")],
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
