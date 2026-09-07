import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from talven.backend import emit_c
from talven.frontend import CompileError, analyze


@unittest.skipUnless(shutil.which("cc"), "Native conformance requires a C11 compiler named cc")
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "win32":
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def compile_run(self, source, optimization="-O2", sanitizer=False):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfile, executable = directory / "program.c", directory / "program"
            cfile.write_text(emit_c(analyze(source)))
            flags = ["-fsanitize=undefined", "-fno-sanitize-recover=all"] if sanitizer else []
            compiled = subprocess.run(["cc", "-std=c11", optimization, "-Wall", "-Wextra", "-Werror",
                                       "-pedantic-errors", *flags, str(cfile), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            return subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)

    def test_vector_example_runs(self):
        self.assertEqual(0, self.compile_run(Path("examples/vectors.tal").read_text()).returncode)

    def test_borrowing_example_and_side_effect_order_with_ubsan(self):
        paths = [Path("examples/borrowing.tal"), *sorted(Path("tests/fixtures").glob("borrowing-*.tal"))]
        self.assertEqual(3, len(paths))
        for path in paths:
            for optimization in ("-O0", "-O2"):
                with self.subTest(path=path, optimization=optimization):
                    result = self.compile_run(path.read_text(), optimization, sanitizer=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("", result.stderr)

    def test_c_keywords_are_mangled_without_injecting_c(self):
        source = "fn switch(auto: i32) -> i32 { let const = auto; return const; } fn main() -> i32 { return switch(0); }"
        self.assertEqual(0, self.compile_run(source).returncode)

    def test_arithmetic_matches_reference_with_undefined_behavior_checks(self):
        rng = random.Random(127)
        statements = []
        for _ in range(80):
            a, b = rng.randrange(-1000, 1001), rng.choice([v for v in range(-50, 51) if v])
            op = rng.choice(["+", "-", "*", "/", "%"])
            expected = {"+": a + b, "-": a - b, "*": a * b,
                        "/": int(a / b), "%": a - int(a / b) * b}[op]
            statements.append(f"if (({a} {op} {b}) != {expected}) {{ return 1; }}")
        result = self.compile_run("fn main() -> i32 {" + "\n".join(statements) + "return 0; }", sanitizer=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_overflow_and_division_trap_at_both_optimization_levels(self):
        expressions = ["2147483647 + 1", "-2147483648 - 1", "50000 * 50000",
                       "-(-2147483648)", "1 / 0", "1 % 0", "-2147483648 / -1", "-2147483648 % -1"]
        for optimization in ("-O0", "-O2"):
            for expr in expressions:
                with self.subTest(expr=expr, optimization=optimization):
                    result = self.compile_run(f"fn main() -> i32 {{ return {expr}; }}", optimization, sanitizer=True)
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotIn("runtime error:", result.stderr)

    def test_short_circuit_skips_trapping_calls(self):
        program = """
            fn bomb() -> bool { return (1 / 0) == 0; }
            fn main() -> i32 {
                if (false && bomb()) { return 1; }
                if (true || bomb()) { return 0; }
                return 2;
            }
        """
        self.assertEqual(0, self.compile_run(program, sanitizer=True).returncode)

    def test_nested_calls_records_and_minimum_integer(self):
        source = """
            struct Pair { first: i32, second: i32 }
            fn make(x: i32) -> Pair { return Pair { second: 7, first: x }; }
            fn sum(p: Pair) -> i32 { return p.first + p.second; }
            fn main() -> i32 {
                let minimum = -2147483648;
                if (sum(make(5)) == 12 && minimum < 0) { return 0; }
                return 1;
            }
        """
        self.assertEqual(0, self.compile_run(source, sanitizer=True).returncode)

    def test_leading_zero_literal_and_precedence(self):
        source = "fn main() -> i32 { if (" + "0" * 5000 + "1 + 2 * 3 == 7) { return 0; } return 1; }"
        self.assertEqual(0, self.compile_run(source).returncode)

    def test_freestanding_object_exposes_only_trap_dependency_for_example(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfile, obj = directory / "kernel.c", directory / "kernel.o"
            generated = emit_c(analyze(Path("examples/vectors.tal").read_text()), freestanding=True)
            self.assertNotIn("#include <stdlib.h>", generated)
            self.assertNotIn("int main(void)", generated)
            cfile.write_text(generated)
            result = subprocess.run(["cc", "-std=c11", "-O2", "-ffreestanding", "-fno-builtin", "-c", str(cfile), "-o", str(obj)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            if shutil.which("nm"):
                symbols = subprocess.check_output(["nm", "-u", str(obj)], text=True)
                self.assertEqual({"talven_trap"}, {line.split()[-1] for line in symbols.splitlines()})


class CommandTests(unittest.TestCase):
    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "talven", *map(str, args)], capture_output=True, text=True, timeout=30)

    def test_check_and_context_work_without_c_compiler(self):
        checked = self.command("check", "examples/vectors.tal", "--json")
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["ok"])
        invalid = self.command("check", "examples/invalid/moved.tal", "--json")
        self.assertEqual(1, invalid.returncode)
        self.assertEqual("E0301", json.loads(invalid.stdout)["diagnostics"][0]["code"])
        result = self.command("context", "examples/vectors.tal", "--symbol", "dot")
        self.assertEqual("talven.context.v2", json.loads(result.stdout)["schema"])

    def test_failed_build_preserves_existing_output_and_no_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.write_text("keep existing artifact")
            result = self.command("build", "examples/vectors.tal", "-o", output, "--cc", "missing-compiler; touch marker")
            self.assertEqual(1, result.returncode)
            self.assertEqual("keep existing artifact", output.read_text())
            self.assertFalse((Path.cwd() / "marker").exists())

    def test_output_cannot_overwrite_source(self):
        result = self.command("emit-c", "examples/vectors.tal", "-o", "examples/vectors.tal")
        self.assertEqual(1, result.returncode)
        self.assertIn("E0403", result.stderr)

    def test_output_hard_link_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, alias = Path(temporary) / "source.tal", Path(temporary) / "alias.c"
            text = "fn main() -> i32 { return 0; }"
            source.write_text(text)
            os.link(source, alias)
            result = self.command("emit-c", source, "-o", alias)
            self.assertEqual(1, result.returncode)
            self.assertIn("E0403", result.stderr)
            self.assertEqual(text, source.read_text())

    def test_entry_contract(self):
        for source in ("", "fn main(x: i32) -> i32 { return x; }", "fn main() -> bool { return true; }"):
            with self.subTest(source=source), self.assertRaises(CompileError) as caught:
                emit_c(analyze(source))
            self.assertEqual("E0401", caught.exception.code)
        emit_c(analyze("fn add(a: i32, b: i32) -> i32 { return a + b; }"), freestanding=True)
