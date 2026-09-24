"""Several diagnostics per check, without changing which error comes first."""
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

from talven.context import agent_context
from talven.frontend import MAX_DIAGNOSTICS, CompileError, analyze, check_source, lex

MULTI = Path("experiments/corpora/hard-v1/syntax-errors/multi.tal")


def strict_first(source):
    try:
        analyze(source)
    except CompileError as error:
        return error.code, error.message, error.span
    return None


def sources():
    paths = sorted({*Path("examples").rglob("*.tal"), *Path("tests/fixtures").glob("*.tal"),
                    *Path("experiments/corpora").rglob("*.tal")})
    for path in paths:
        yield str(path), path.read_text(encoding="utf-8")
    rng = random.Random(20260924)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        tokens = [t for t in lex(text) if t.kind != "eof"]
        for _ in range(12):
            token = rng.choice(tokens)
            replacement = rng.choice(["", ";", "}", "{", "let", "=", "x", "if", "(", "&mut", "else"])
            yield f"{path}:mutation", text[:token.span.start] + replacement + text[token.span.end:]


class DiagnosticsTests(unittest.TestCase):
    def test_first_error_matches_strict_analysis(self):
        for name, source in sources():
            with self.subTest(case=name):
                analysis, errors = check_source(source)
                first = strict_first(source)
                if first is None:
                    self.assertEqual([], errors)
                    self.assertIsNotNone(analysis)
                else:
                    self.assertIsNone(analysis)
                    self.assertEqual(first, (errors[0].code, errors[0].message, errors[0].span))
                    self.assertLessEqual(len(errors), MAX_DIAGNOSTICS)

    def test_independent_errors_are_all_reported(self):
        _, errors = check_source(MULTI.read_text(encoding="utf-8"))
        self.assertEqual({"E0002", "E0304", "E0102", "E0301"}, {error.code for error in errors})
        self.assertGreaterEqual(len(errors), 7)

    def test_one_error_is_reported_once_without_cascades(self):
        for source in ("fn main() -> i32 { let x = 1; let x = 2; return x; }",
                       "fn f(a: i32) -> i32 { return a }\nfn main() -> i32 { return f(1); }",
                       "fn main() -> i32 { return missing; }"):
            with self.subTest(source=source):
                self.assertEqual(1, len(check_source(source)[1]))

    def test_declaration_errors_stop_before_semantic_checks(self):
        source = "fn broken(a: ) -> i32 { return 0; }\nfn main() -> i32 { return broken(1); }"
        _, errors = check_source(source)
        self.assertEqual(["E0002"], [error.code for error in errors])

    def test_cli_check_reports_every_error(self):
        result = subprocess.run([sys.executable, "-m", "talven", "check", str(MULTI), "--json"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(1, result.returncode)
        diagnostics = json.loads(result.stdout)["diagnostics"]
        self.assertGreaterEqual(len(diagnostics), 7)
        text = subprocess.run([sys.executable, "-m", "talven", "check", str(MULTI)],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(len(diagnostics), len(text.stderr.strip().splitlines()))

    def test_compact_context_has_facts_without_machine_metadata(self):
        context = json.loads(agent_context(analyze(Path("experiments/corpora/hard-v1/reborrow.tal").read_text())))
        self.assertEqual({"schema", "functions", "records"}, set(context))
        bump = next(fn for fn in context["functions"] if fn["signature"].startswith("fn bump_n"))
        self.assertEqual("borrow-exclusive", bump["passing"]["c"])
        encoded = json.dumps(context)
        for noise in ("cache_key", "compiler_hash", "bootstrap_runtime", "source_hash", "rules"):
            self.assertNotIn(noise, encoded)


if __name__ == "__main__":
    unittest.main()
