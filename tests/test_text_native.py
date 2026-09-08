import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from talven.backend import emit_c
from talven.frontend import CompileError, analyze


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cc") and os.name == "posix", "Native text tests require a POSIX host and cc")
class NativeTextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def generated(self, source, **options):
        try:
            analysis = analyze(source)
        except CompileError as error:
            self.fail(f"Valid native text fixture rejected: {error.code}: {error.message}")
        return emit_c(analysis, **options)

    def compile(self, generated, flags=()):
        source, executable = self.directory / "program.c", self.directory / "program"
        source.write_text(generated, encoding="utf-8")
        result = subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic-errors",
                                 *flags, str(source), "-o", str(executable)], capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr.decode())
        return executable

    def run_source(self, source, *, flags=(), env=None):
        executable = self.compile(self.generated(source, console=True), flags)
        return subprocess.run([str(executable)], capture_output=True, timeout=5, env=env)

    def test_literal_bytes_are_exact_and_never_used_as_a_format_string(self):
        cases = (
            ('"Hello, world!\\n"', b"Hello, world!\n"),
            ('""', b""),
            ('"A\\0B\\t\\r\\n\\\"\\\\"', b'A\0B\t\r\n"\\'),
            ('"你好 😀 café"', b'\xe4\xbd\xa0\xe5\xa5\xbd \xf0\x9f\x98\x80 caf\xc3\xa9'),
            ('"%s %n // ??/ ; {}"', b"%s %n // ??/ ; {}"),
        )
        for literal, expected in cases:
            with self.subTest(literal=literal):
                result = self.run_source('fn main() -> i32 { return print(' + literal + '); }')
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout)
                self.assertEqual(b"", result.stderr)

    def test_large_literal_crosses_write_chunks_without_truncation(self):
        result = self.run_source('fn main() -> i32 { return print("' + 'abc' * 12000 + '"); }')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"abc" * 12000, result.stdout)

    def test_calls_keep_source_order_and_short_circuit_effects(self):
        result = self.run_source('''fn pair(a: i32, b: i32) -> i32 { return a + b; }
fn main() -> i32 {
    false && (print("wrong") == 0);
    true || (print("wrong") == 0);
    return pair(print("first"), print("second"));
}''')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"firstsecond", result.stdout)

    def test_literal_outlives_its_returning_function_and_copies(self):
        result = self.run_source('''fn identity(s: str) -> str { return s; }
fn message() -> str { let s = "alive"; identity(s); return s; }
fn main() -> i32 { let a = message(); let b = a; print(a); return print(b); }''')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"alivealive", result.stdout)

    def controlled_write(self, body, source='fn main() -> i32 { return print("abcdef"); }'):
        generated = self.generated(source, console=True)
        # Control only the OS write boundary. The real emitted loop must
        # preserve bytes, retry interruptions, and propagate failures.
        code = '#define write fixture_write\n' + generated + '\n#undef write\n'
        code += 'extern ssize_t write(int, const void *, size_t);\n'
        code += 'ssize_t fixture_write(int fd, const void *data, size_t count) {\n' + body + '\n}\n'
        executable = self.compile(code)
        return subprocess.run([str(executable)], capture_output=True, timeout=5)

    def test_partial_writes_and_interruption_preserve_all_bytes(self):
        result = self.controlled_write('''static int calls;
    if (++calls == 1 || calls == 3) { errno = EINTR; return -1; }
    return write(fd, data, count > 2 ? 2 : count);''')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"abcdef", result.stdout)

    def test_error_after_partial_write_is_not_success_or_rollback(self):
        result = self.controlled_write('''static int calls;
    if (++calls == 1) { return write(fd, data, count > 2 ? 2 : count); }
    errno = EIO; return -1;''')
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(b"ab", result.stdout)

    def test_zero_progress_and_would_block_fail_without_spinning(self):
        for reply in ('return 0;', 'errno = EAGAIN; return -1;'):
            with self.subTest(reply=reply):
                result = self.controlled_write('(void)fd; (void)data; (void)count; ' + reply)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertEqual(b"", result.stdout)

    def test_empty_text_succeeds_without_touching_the_output_descriptor(self):
        result = self.controlled_write('(void)fd; (void)data; (void)count; _Exit(99);',
                                       'fn main() -> i32 { return print(""); }')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"", result.stdout)

    def test_closed_output_reports_failure(self):
        executable = self.compile(self.generated('fn main() -> i32 { return print("x"); }', console=True))
        with open(os.devnull, "rb") as read_only:
            result = subprocess.run([str(executable)], stdout=read_only, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(1, result.returncode, result.stderr)

    def test_broken_pipe_keeps_the_host_signal_behavior(self):
        executable = self.compile(self.generated('fn main() -> i32 { return print("x"); }', console=True))
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        with os.fdopen(write_fd, "wb") as pipe:
            result = subprocess.run([str(executable)], stdout=pipe, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(-signal.SIGPIPE, result.returncode, result.stderr)

    def test_output_object_has_no_allocator_or_stdio_dependency(self):
        for enabled, source in ((True, 'fn main() -> i32 { return print("x"); }'),
                                (True, 'fn main() -> i32 { let s = "x"; return 0; }'),
                                (False, 'fn main() -> i32 { let s = "x"; return 0; }')):
            with self.subTest(enabled=enabled, source=source):
                cfile, obj = self.directory / "deps.c", self.directory / "deps.o"
                cfile.write_text(self.generated(source, console=enabled))
                built = subprocess.run(["cc", "-std=c11", "-O2", "-fno-stack-protector", "-c", str(cfile), "-o", str(obj)],
                                       capture_output=True, timeout=30)
                self.assertEqual(0, built.returncode, built.stderr)
                inspected = subprocess.run(["nm", "-u", str(obj)], capture_output=True, timeout=5)
                self.assertEqual(0, inspected.returncode, inspected.stderr)
                symbols = {line.split()[-1].lstrip(b"_") for line in inspected.stdout.splitlines() if line.strip()}
                self.assertEqual({b"write"} if "print" in source else set(), symbols - {b"errno_location", b"error"})

    def test_freestanding_text_needs_neither_console_nor_allocator_symbols(self):
        generated = self.generated('fn identity(s: str) -> str { return s; } '
                                   'fn message() -> str { return identity("A\\0B"); }', freestanding=True)
        source, obj = self.directory / "text.c", self.directory / "text.o"
        source.write_text(generated)
        result = subprocess.run(["cc", "-std=c11", "-O2", "-ffreestanding", "-fno-stack-protector",
                                 "-c", str(source), "-o", str(obj)], capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        symbols = subprocess.run(["nm", "-u", str(obj)], capture_output=True, timeout=5)
        self.assertEqual(0, symbols.returncode, symbols.stderr)
        self.assertEqual(b"", symbols.stdout.strip())

    def test_cli_opt_in_and_checked_in_hello_example(self):
        source = ROOT / "examples/hello.tal"
        self.assertTrue(source.is_file(), "The runnable Hello World example is missing")
        executable = self.directory / "hello"
        executable.write_bytes(b"previous artifact")
        command = [sys.executable, "-m", "talven", "build", str(source), "-o", str(executable)]
        rejected = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(1, rejected.returncode, rejected.stderr)
        self.assertIn(b"E0404", rejected.stderr)
        self.assertEqual(b"previous artifact", executable.read_bytes())
        built = subprocess.run([*command, "--console"], cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(0, built.returncode, built.stderr)
        result = subprocess.run([str(executable)], capture_output=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"Hello, world!\n", result.stdout)
        self.assertEqual(b"", result.stderr)
        emitted = subprocess.run([sys.executable, "-m", "talven", "emit-c", str(source), "--console"],
                                 cwd=ROOT, capture_output=True, timeout=5)
        self.assertEqual(0, emitted.returncode, emitted.stderr)
        emitted_executable = self.compile(emitted.stdout.decode())
        emitted_result = subprocess.run([str(emitted_executable)], capture_output=True, timeout=5)
        self.assertEqual(0, emitted_result.returncode, emitted_result.stderr)
        self.assertEqual(b"Hello, world!\n", emitted_result.stdout)

    @unittest.skipUnless(platform.system() == "Linux", "Sanitizer flags target declared Linux hosts")
    def test_static_lifetime_and_nul_output_with_address_and_undefined_sanitizers(self):
        result = self.run_source('''fn message() -> str { return "A\\0B"; }
fn main() -> i32 { let s = message(); print(s); return print(s); }''',
                                 flags=("-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-inline", "-fno-pie", "-no-pie"),
                                 env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:detect_stack_use_after_return=1:halt_on_error=1",
                                      "UBSAN_OPTIONS": "halt_on_error=1"})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"A\0BA\0B", result.stdout)
        self.assertEqual(b"", result.stderr)


if __name__ == "__main__":
    unittest.main()
