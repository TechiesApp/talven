"""Independent finite native acceptance and differential checks. No provider calls."""
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from talven.frontend import CompileError, analyze
from talven.backend import emit_c

BINARY = Path(os.environ.get("TALVEN_NATIVE", ROOT / "experiments/native-compiler/target/release/talven-native")).resolve()


class NativePrototypeTests(unittest.TestCase):
    def command(self, source, command="check", console=False):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            path.write_bytes(source.encode() if isinstance(source, str) else source)
            args = [str(BINARY), command, str(path)]
            if console:
                args.append("--console")
            if command == "check":
                args.append("--json")
            return subprocess.run(args, capture_output=True, timeout=10)

    def run_native(self, source, *, console=False, sanitizer=False):
        result = self.command(source, "emit-c", console)
        self.assertEqual(0, result.returncode, result.stderr)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfile, executable = directory / "program.c", directory / "program"
            cfile.write_bytes(result.stdout)
            flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitizer else []
            built = subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                                    "-pedantic-errors", *flags, str(cfile), "-o", str(executable)],
                                   capture_output=True, timeout=30)
            self.assertEqual(0, built.returncode, built.stderr)
            return subprocess.run([str(executable)], capture_output=True, timeout=5)

    def test_native_greeting_and_static_utf8_lifetimes(self):
        source = 'fn text() -> str { return "hé🙂\\0\\n"; } fn relay(s: str) -> str { return s; } fn main() -> i32 { let s = relay(text()); return print(s); }'
        result = self.run_native(source, console=True, sanitizer=True)
        self.assertEqual((0, "hé🙂\0\n".encode(), b""), (result.returncode, result.stdout, result.stderr))
        hello = self.run_native((ROOT / "examples/hello.tal").read_text(), console=True)
        self.assertEqual((0, b"Hello, world!\n", b""), (hello.returncode, hello.stdout, hello.stderr))

    def test_source_order_and_short_circuit(self):
        source = '''fn mark(s: str) -> i32 { return print(s); }
fn add(a: i32, b: i32) -> i32 { return a + b; }
fn bomb() -> bool { return (1 / 0) == 0; }
fn main() -> i32 {
    if (false && bomb()) { return 9; }
    if (true || bomb()) { return add(mark("a"), mark("b")) + mark("c"); }
    return 8;
}'''
        result = self.run_native(source, console=True, sanitizer=True)
        self.assertEqual((0, b"abc", b""), (result.returncode, result.stdout, result.stderr))

    def test_arithmetic_independent_expected_values(self):
        rng = random.Random(812)
        statements = []
        for _ in range(70):
            a, b = rng.randrange(-500, 500), rng.choice([n for n in range(-15, 16) if n])
            op = rng.choice(["+", "-", "*", "/", "%"])
            value = {"+": a+b, "-": a-b, "*": a*b, "/": int(a/b), "%": a-int(a/b)*b}[op]
            statements.append(f"if (({a} {op} {b}) != {value}) {{ return 1; }}")
        source = "fn main() -> i32 {" + "".join(statements) + "return 0; }"
        self.assertEqual(0, self.run_native(source, sanitizer=True).returncode)

    def test_overflow_and_division_trap(self):
        for expr in ["2147483647 + 1", "-2147483648 - 1", "50000 * 50000", "-(-2147483648)",
                     "1 / 0", "1 % 0", "-2147483648 / -1", "-2147483648 % -1"]:
            with self.subTest(expr=expr):
                result = self.run_native(f"fn main() -> i32 {{ return {expr}; }}", sanitizer=True)
                self.assertLess(result.returncode, 0)
                self.assertNotIn(b"runtime error", result.stderr)

    def test_supported_acceptance_agrees_with_reference(self):
        sources = ["", "fn f(x: i32) -> i32 { return x; }",
                   "fn f() -> str { let x: str = \"\"; return x; }",
                   "fn switch(auto: i32) -> i32 { let const = auto; return const; }",
                   "fn main() -> i32 { return later(4); } fn later(x: i32,) -> i32 { if (x == 0) { return 0; } else { return later(x - 1); } }",
                   "fn main() -> i32 { return -0000002147483648; }"]
        for source in sources:
            analyze(source)
            result = self.command(source)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])
            self.assertEqual("native-scalar-text-v1", json.loads(result.stdout)["profile"])

    def test_supported_rejections_agree_with_reference_codes(self):
        sources = ['fn main() -> i32 { return false; }', 'fn f() -> i32 { let x = 0; }',
                   'fn f() -> i32 { return 0; return 1; }', 'fn f(x: i32) -> i32 { let x = 2; return x; }',
                   'fn f() -> i32 { return absent; }', 'fn f() -> i32 { return nope(); }',
                   'fn f() -> i32 { return 2147483648; }', 'fn f() -> i32 { return 0; } fn f() -> i32 { return 1; }',
                   'fn f() -> bool { return "a" == "b"; }', 'fn f() -> i32 { return print(3); }',
                   'fn f() -> i32 { return print(); }', 'fn f() -> i32 { if (1) { return 0; } return 1; }',
                   'fn f() -> str { return "bad\\x"; }', 'fn print() -> i32 { return 0; }',
                   'fn f() -> i32 { return (1; }', 'fn f() -> i32 { return @; }']
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(CompileError) as caught:
                    analyze(source)
                result = self.command(source)
                self.assertEqual(1, result.returncode, result.stderr)
                diagnostic = json.loads(result.stdout)["diagnostics"][0]
                self.assertEqual(caught.exception.code, diagnostic["code"])

    def test_unsupported_records_and_borrowing_never_fall_back(self):
        for source in ["struct A { x: i32 }", "fn f(x: &A) -> i32 { return 0; }",
                       "fn f() -> i32 { let mut x = 0; return x; }"]:
            result = self.command(source)
            self.assertEqual(1, result.returncode)
            self.assertEqual("E0801", json.loads(result.stdout)["diagnostics"][0]["code"])

    def test_entry_console_and_no_implicit_output(self):
        hello = (ROOT / "examples/hello.tal").read_text()
        self.assertEqual(0, self.command(hello).returncode)
        self.assertIn(b"E0404", self.command(hello, "emit-c").stderr)
        for source in ["", "fn main() -> bool { return true; }", "fn main(x: i32) -> i32 { return x; }"]:
            self.assertIn(b"E0401", self.command(source, "emit-c").stderr)
        quiet = self.command("fn main() -> i32 { return 0; }", "emit-c", console=True)
        self.assertNotIn(b"unistd", quiet.stdout)
        self.assertNotIn(b"tv_console_print", quiet.stdout)

    def test_limits_and_invalid_utf8_report_without_crashing(self):
        for source in [b"\xff", b" " * (256 * 1024 + 1),
                       "fn f() -> i32 { return " + "("*300 + "1" + ")"*300 + "; }",
                       "fn f() -> i32 { return " + "+".join(["1"] * 10000) + "; }"]:
            result = self.command(source)
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])

    def test_nonregular_and_non_utf8_paths_do_not_hang_or_panic(self):
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "pipe.tal"
            os.mkfifo(fifo)
            alias = Path(temporary) / "alias.tal"
            alias.symlink_to(fifo)
            for path in (fifo, alias):
                result = subprocess.run([str(BINARY), "check", str(path), "--json"], capture_output=True, timeout=3)
                self.assertEqual(1, result.returncode)
                self.assertEqual("E0901", json.loads(result.stdout)["diagnostics"][0]["code"])
            path = os.fsencode(temporary) + b"/source-\xff.tal"
            if sys.platform.startswith("linux"):
                with open(path, "wb") as stream:
                    stream.write(b"fn main() -> i32 { return 0; }")
            result = subprocess.run([os.fsencode(BINARY), b"check", path, b"--json"], capture_output=True, timeout=3)
            # macOS filesystems reject this spelling, but the CLI must still diagnose it.
            self.assertEqual(0 if sys.platform.startswith("linux") else 1, result.returncode, result.stderr)
            self.assertEqual(sys.platform.startswith("linux"), json.loads(result.stdout)["ok"])

    def test_utf16_diagnostic_range_and_json_escaping(self):
        source = '// 🙂\nfn f() -> i32 { "🙂"; return missing; }'
        with self.assertRaises(CompileError) as caught:
            analyze(source)
        result = self.command(source)
        self.assertEqual(caught.exception.diagnostic(source)["range"], json.loads(result.stdout)["diagnostics"][0]["range"])


if __name__ == "__main__":
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if not BINARY.is_file():
        raise SystemExit(f"Build the native compiler first: {BINARY}")
    unittest.main(verbosity=2)
