import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from talven.frontend import CompileError
from talven.test_runner import MARKER, MAX_OUTPUT, decode_result, load_manifest, run_tests

ROOT = Path(__file__).resolve().parents[1]


def manifest(cases):
    return json.dumps({'schema': 'talven.test-manifest.v1', 'cases': cases})


class ManifestTests(unittest.TestCase):
    def test_valid_defaults_and_explicit_diagnostic(self):
        cases = load_manifest(manifest([{'id': 'run', 'source': 'nested/a.tal'},
                                        {'id': 'bad', 'source': 'bad.tal', 'diagnostic': 'E0201'}]))
        self.assertEqual((False, 0, b'', b'', None),
                         (cases[0].console, cases[0].result, cases[0].stdout, cases[0].stderr, cases[0].diagnostic))
        self.assertEqual('E0201', cases[1].diagnostic)

    def test_rejects_ambiguous_json_and_unknown_schema_fields(self):
        for source in ('{}', '[]', '{', '{"schema":"x","schema":"x","cases":[]}',
                       '{"schema":"talven.test-manifest.v1","cases":[NaN]}',
                       '{"schema":"talven.test-manifest.v1","cases":[Infinity]}',
                       manifest([]), manifest([{'id': 'a', 'source': 'a.tal'}] * 2),
                       manifest([{'id': 'a', 'source': 'a.tal', 'extra': 1}]),
                       manifest([{'id': str(i), 'source': 'a.tal'} for i in range(129)])):
            with self.subTest(source=source[:100]), self.assertRaises(CompileError) as caught:
                load_manifest(source)
            self.assertEqual('E0801', caught.exception.code)

    def test_rejects_invalid_paths_types_ranges_and_output(self):
        changes = [('source', x) for x in ('/a.tal', '../a.tal', 'x/../a.tal', 'a.c', '', 'a\0.tal', '\ud800.tal', 'x'*1024+'.tal')]
        changes += [('result', x) for x in (True, 1.5, -(2**31)-1, 2**31)]
        changes += [('console', 1), ('id', 'not valid'), ('stdout', 3), ('stdout', '\ud800'),
                    ('stderr', 'x'*(MAX_OUTPUT+1)), ('diagnostic', None), ('diagnostic', 'Ebad')]
        for key, value in changes:
            with self.subTest(key=key, value=str(value)[:60]), self.assertRaises(CompileError) as caught:
                load_manifest(manifest([{'id': 'a', 'source': 'a.tal', key: value}]))
            self.assertEqual('E0801', caught.exception.code)
        for key in ('result', 'stdout', 'stderr'):
            with self.subTest(key=key), self.assertRaises(CompileError):
                load_manifest(manifest([{'id': 'a', 'source': 'a.tal', 'diagnostic': 'E0201', key: 0}]))

    def test_protocol_uses_last_marker_and_validates_canonical_i32(self):
        self.assertEqual((-2147483648, b'prefix'+MARKER+b'0\n'),
                         decode_result(b'prefix'+MARKER+b'0\n'+MARKER+b'-2147483648\n'))
        for value in (b'', b'01\n', b'-0\n', b'+1\n', b'2147483648\n', b'-2147483649\n', b'0\nextra', b'0'):
            with self.subTest(value=value), self.assertRaises(CompileError) as caught:
                decode_result(MARKER+value)
            self.assertEqual('E0802', caught.exception.code)


class TestRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_cases(self, cases, **options):
        path = self.root/'tests.json'
        path.write_text(manifest(cases))
        return run_tests(path, **options)

    def source(self, name, text):
        (self.root/name).write_text(text)
        return name

    def test_full_signed_results_and_no_os_exit_wrapping(self):
        cases = []
        for i, value in enumerate((0, 256, -1, 2147483647, -2147483648)):
            name = self.source(f'{i}.tal', f'fn main() -> i32 {{ return {value}; }}')
            cases.append({'id': str(i), 'source': name, 'result': value})
        cases.append({'id': 'wrong-zero', 'source': '1.tal'})
        report = self.run_cases(cases)
        self.assertTrue(report['complete'])
        self.assertFalse(report['ok'])
        self.assertEqual({'passed': 5, 'failed': 1}, report['summary'])
        self.assertEqual(256, report['cases'][-1]['runtime']['result'])
        self.assertFalse(report['cases'][-1]['runtime']['result_matches'])
        self.assertTrue(report['driver']['target']['bytes'])
        self.assertEqual([f'{i}.tal' for i in range(5)]+['tests.json'], sorted(p.name for p in self.root.iterdir()))

    def test_exact_unicode_nul_and_marker_output(self):
        output = 'hé\0'+MARKER.decode()+'7\n'
        name = self.source('text.tal', 'fn main() -> i32 { return print("hé\\0\\0talven.test.i32:7\\n"); }')
        report = self.run_cases([{'id': 'exact', 'source': name, 'console': True, 'stdout': output},
                                 {'id': 'different', 'source': name, 'console': True, 'stdout': 'hé'}])
        self.assertEqual({'passed': 1, 'failed': 1}, report['summary'])
        stream = report['cases'][0]['runtime']['stdout']
        self.assertEqual(hashlib.sha256(output.encode()).hexdigest(), stream['sha256'])
        self.assertEqual(output, stream['preview'])

    def test_example_manifest_has_current_native_and_diagnostic_acceptance(self):
        report = run_tests(ROOT/'examples/tests.json')
        self.assertTrue(report['ok'], report)
        self.assertEqual({'passed': 7, 'failed': 0}, report['summary'])

    def test_diagnostics_never_invoke_missing_compiler_and_wrong_expectations_fail(self):
        name = self.source('bad.tal', 'fn main() -> i32 { return true; }')
        good = self.source('good.tal', 'fn main() -> i32 { return 0; }')
        with patch('talven.test_runner.BoundedCommand', side_effect=AssertionError('no native tools')):
            report = self.run_cases([{'id': 'expected', 'source': name, 'diagnostic': 'E0201'},
                                     {'id': 'wrong', 'source': name, 'diagnostic': 'E0402'},
                                     {'id': 'absent', 'source': good, 'diagnostic': 'E0201'},
                                     {'id': 'io', 'source': 'missing.tal', 'diagnostic': 'E0901'}], cc='missing')
        self.assertEqual({'passed': 1, 'failed': 3}, report['summary'])
        self.assertIsNone(report['driver'])
        self.assertEqual('input', report['cases'][-1]['phase'])

    def test_console_and_entry_errors_remain_frontend_diagnostics(self):
        text = self.source('text.tal', 'fn main() -> i32 { return print("text"); }')
        entry = self.source('entry.tal', 'fn main(value: i32) -> i32 { return value; }')
        report = self.run_cases([{'id': 'console', 'source': text, 'diagnostic': 'E0404'},
                                 {'id': 'entry', 'source': entry, 'diagnostic': 'E0401'}], cc='missing')
        self.assertTrue(report['ok'], report)

    def test_regular_bounded_inputs_and_resolved_source_paths(self):
        outside = self.root.parent/(self.root.name+'-outside.tal')
        outside.write_text('fn main() -> i32 { return 0; }')
        self.addCleanup(outside.unlink)
        (self.root/'escape.tal').symlink_to(outside)
        os.mkfifo(self.root/'fifo.tal')
        (self.root/'large.tal').write_bytes(b'x'*(262144+1))
        started = time.monotonic()
        report = self.run_cases([{'id': 'escape', 'source': 'escape.tal'},
                                 {'id': 'fifo', 'source': 'fifo.tal'}, {'id': 'large', 'source': 'large.tal'}])
        self.assertLess(time.monotonic()-started, 3)
        self.assertEqual(['E0801', 'E0901', 'E0005'], [c['diagnostic']['code'] for c in report['cases']])
        os.mkfifo(self.root/'manifest-fifo')
        self.assertFalse(run_tests(self.root/'manifest-fifo')['complete'])

    def test_missing_and_failed_compilers_are_toolchain_failures(self):
        name = self.source('good.tal', 'fn main() -> i32 { return 0; }')
        cases = [{'id': 'run', 'source': name}]
        self.assertEqual('E0901', self.run_cases(cases, cc='talven-nonexistent-test-cc')['cases'][0]['diagnostic']['code'])
        compiler = self.root/'compiler'
        compiler.write_text(f'#!{sys.executable}\nimport sys\nsys.stderr.write("synthetic failure")\nsys.exit(4)\n')
        compiler.chmod(0o700)
        row = self.run_cases(cases, cc=str(compiler))['cases'][0]
        self.assertEqual('toolchain', row['phase'])
        self.assertEqual('E0402', row['diagnostic']['code'])
        self.assertEqual(4, row['failed_command']['returncode'])
        self.assertEqual('synthetic failure', row['failed_command']['stderr']['preview'])
        compiler.write_text(f'#!{sys.executable}\n')
        self.assertEqual('E0901', self.run_cases(cases, cc=str(compiler))['cases'][0]['diagnostic']['code'])

    def test_runtime_trap_is_failure_even_with_expected_zero(self):
        name = self.source('trap.tal', 'fn main() -> i32 { return 2147483647 + 1; }')
        row = self.run_cases([{'id': 'trap', 'source': name}])['cases'][0]
        self.assertFalse(row['ok'])
        self.assertEqual('run', row['phase'])
        self.assertEqual('E0402', row['diagnostic']['code'])
        self.assertNotEqual(0, row['failed_command']['returncode'])

    def test_malformed_protocol_timeout_and_output_overflow_fail(self):
        name = self.source('good.tal', 'fn main() -> i32 { return 0; }')
        drivers = [(b'int main(void) { return 0; }', 'E0802'),
                   (b'int main(void) { for (;;) {} }', 'E0402'),
                   (b'#include <stdio.h>\nint main(void) { for (int i=0;i<100000;i++) putchar(120); return 0; }', 'E0402')]
        for driver, expected in drivers:
            with self.subTest(driver=driver), patch('talven.test_runner.DRIVER', driver):
                row = self.run_cases([{'id': 'run', 'source': name}], timeout=2)['cases'][0]
            self.assertFalse(row['ok'])
            self.assertEqual('run', row['phase'])
            self.assertEqual(expected, row['diagnostic']['code'])

    def test_compiler_drift_rejects_result_before_execution(self):
        name = self.source('good.tal', 'fn main() -> i32 { return 0; }')
        with patch('talven.test_runner.compiler_hash', side_effect=['a'*64, 'b'*64, 'b'*64]):
            report = self.run_cases([{'id': 'run', 'source': name}])
        self.assertFalse(report['complete'])
        self.assertFalse(report['ok'])
        self.assertEqual('E0501', report['diagnostic']['code'])
        self.assertIsNone(report['cases'][0]['runtime'])

    def test_missing_link_artifact_is_never_executed(self):
        name = self.source('good.tal', 'fn main() -> i32 { return 0; }')
        from talven.unit_build import artifact_bytes
        def missing_program(path):
            if path.name == 'program':
                path.unlink()
            return artifact_bytes(path)
        with patch('talven.test_runner.artifact_bytes', side_effect=missing_program):
            row = self.run_cases([{'id': 'run', 'source': name}])['cases'][0]
        self.assertFalse(row['ok'])
        self.assertEqual('link', row['phase'])
        self.assertIsNone(row['runtime'])

    def test_stderr_mismatch_is_not_hidden_by_correct_result(self):
        name = self.source('good.tal', 'fn main() -> i32 { return 0; }')
        from talven.test_runner import DRIVER
        driver = DRIVER.replace(b'    int32_t result', b'    fputs("unexpected", stderr);\n    int32_t result')
        with patch('talven.test_runner.DRIVER', driver):
            row = self.run_cases([{'id': 'run', 'source': name}])['cases'][0]
        self.assertFalse(row['ok'])
        self.assertTrue(row['runtime']['result_matches'])
        self.assertFalse(row['runtime']['stderr_matches'])
        self.assertEqual('unexpected', row['runtime']['stderr']['preview'])

    def test_manifest_io_and_size_fail_before_cases(self):
        path = self.root/'tests.json'
        for data, expected in ((b'\xff', 'E0901'), (b'x'*(262144+1), 'E0005'), (b'{', 'E0801')):
            path.write_bytes(data)
            report = run_tests(path)
            self.assertFalse(report['complete'])
            self.assertFalse(report['ok'])
            self.assertEqual([], report['cases'])
            self.assertEqual(expected, report['diagnostic']['code'])

    def test_cli_exit_json_and_human_output(self):
        name = self.source('good.tal', 'fn main() -> i32 { return 256; }')
        path = self.root/'tests.json'
        path.write_text(manifest([{'id': 'value', 'source': name, 'result': 256}]))
        command = [sys.executable, '-m', 'talven', 'test', str(path)]
        result = subprocess.run([*command, '--json'], capture_output=True, timeout=30, cwd=ROOT)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        path.write_text(manifest([{'id': 'value', 'source': name}]))
        result = subprocess.run(command, capture_output=True, timeout=30, cwd=ROOT)
        self.assertEqual(1, result.returncode)
        self.assertIn(b'FAIL value', result.stdout)
        self.assertIn(b'0 passed, 1 failed', result.stdout)
        for timeout in ('0', '61', 'nan', 'inf'):
            result = subprocess.run([*command, '--timeout', timeout], capture_output=True, timeout=5, cwd=ROOT)
            self.assertEqual(2, result.returncode)

    def test_timeout_api_rejects_nonfinite_and_bool(self):
        for timeout in (True, 0, 61, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                run_tests(self.root/'unused.json', timeout=timeout)
