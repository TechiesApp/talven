import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from talven.__main__ import main
from talven.context import source_hash
from talven.frontend import CompileError
from talven.preprocessed_units import FLAGS, prepare_c_units, run_bounded, split_preprocessed

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'fn add(x: i32) -> i32 { return x + 1; } fn keep(x: i32) -> i32 { return x * 2; } fn main() -> i32 { return keep(add(2)) - 6; }'


def execute_prepared(receipt, *, optimization='-O2', sanitizer=False):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        flags = [*FLAGS, '-Werror', '-fno-lto']
        flags[1] = optimization
        if sanitizer:
            flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        objects = []
        for index, unit in enumerate(receipt['units']):
            path, obj = directory / f'{index}.i', directory / f'{index}.o'
            path.write_text(unit['c'])
            subprocess.run(['cc', *flags, '-x', 'cpp-output', '-c', str(path), '-o', str(obj)],
                           check=True, capture_output=True, timeout=30)
            objects.append(str(obj))
        program = directory / 'program'
        subprocess.run(['cc', *flags, *objects, '-o', str(program)], check=True, capture_output=True, timeout=30)
        return subprocess.run([str(program)], capture_output=True, timeout=5)


class PreprocessedUnitTests(unittest.TestCase):
    def test_split_normalizes_only_own_positions_and_preserves_system_header_flags(self):
        output = ('# 123 "/system/header.h" 1 3 4\n'
                  'typedef int example;\n# 88 "<stdin>" 2\nextern int tv_unit_header_boundary;\n'
                  '# 100 "<stdin>"\nint example_function(void) { return 7; }\nextern int tv_unit_boundary_0;\n')
        unit = split_preprocessed(output, ['fn:example_function'])['fn:example_function']
        self.assertIn('# 123 "/system/header.h" 1 3 4', unit)
        self.assertIn('# 1 "<stdin>" 2', unit)
        self.assertNotIn('# 100', unit)
        self.assertNotIn('tv_unit_boundary', unit)
        self.assertEqual(unit, split_preprocessed(output.replace('100 "<stdin>"', '200 "<stdin>"'), ['fn:example_function'])['fn:example_function'])

    def test_split_rejects_missing_repeated_unordered_empty_or_trailing_content(self):
        valid = 'typedef int example;\nextern int tv_unit_header_boundary;\nint fn(void) { return 0; }\nextern int tv_unit_boundary_0;\n'
        broken = [valid.replace('extern int tv_unit_header_boundary;\n', ''),
                  valid.replace('boundary_0', 'boundary_1'), valid + 'int unexpected;\n',
                  valid.replace('int fn(void) { return 0; }\n', '# 90 "<stdin>"\n'),
                  valid.replace('typedef int example;\n', ''),
                  valid.replace('int fn(void)', 'extern int tv_unit_header_boundary;\nint fn(void)'),
                  valid.replace('extern int tv_unit_boundary_0;\n', '')]
        for output in broken:
            with self.subTest(output=output), self.assertRaises(CompileError):
                split_preprocessed(output, ['fn:fn'])
        for identities in ([], ['entry', 'entry'], ['unknown'], [None], [['unhashable']]):
            with self.subTest(identities=identities), self.assertRaises(CompileError):
                split_preprocessed(valid, identities)
        with patch('talven.preprocessed_units.MAX_PREPARED_BYTES', 10), self.assertRaises(CompileError):
            split_preprocessed(valid, ['fn:fn'])

    def test_current_preprocessing_has_stable_unrelated_units_and_complete_identities(self):
        original = prepare_c_units(SOURCE)
        changed = prepare_c_units(SOURCE.replace('return x + 1;', 'let y = x + 2; return y + 1;'))
        first = {u['id']: u for u in original['units']}
        second = {u['id']: u for u in changed['units']}
        self.assertNotEqual(first['fn:add']['c_hash'], second['fn:add']['c_hash'])
        for identity in ('fn:keep', 'fn:main', 'entry'):
            self.assertEqual(first[identity]['c'], second[identity]['c'])
        self.assertEqual(source_hash(SOURCE), original['source_hash'])
        self.assertTrue(all(u['c_hash'] == source_hash(u['c']) for u in original['units']))
        self.assertEqual(64, len(original['raw_preprocessed_hash']))
        self.assertEqual(64, len(original['compiler']['executable_hash']))
        self.assertEqual(list(FLAGS), original['compiler']['flags'])
        result = execute_prepared(original)
        self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))

    def test_invalid_source_does_not_launch_tools_and_input_drift_rejects_the_receipt(self):
        with patch('talven.preprocessed_units.run_bounded', side_effect=AssertionError('no tool before checking')):
            with self.assertRaises(CompileError) as caught:
                prepare_c_units('fn main() -> i32 { return false; }')
            self.assertEqual('E0201', caught.exception.code)
        with patch('talven.preprocessed_units.compiler_hash', side_effect=['old', 'changed']):
            with self.assertRaises(CompileError) as caught:
                prepare_c_units(SOURCE)
            self.assertEqual('E0501', caught.exception.code)
        for timeout in (0, 61, float('nan'), float('inf'), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                prepare_c_units(SOURCE, timeout=timeout)

    def test_environment_values_are_hashed_not_retained(self):
        with patch.dict(os.environ, {'TALVEN_TEST_PRIVATE_VALUE': 'synthetic-do-not-retain'}):
            receipt = prepare_c_units(SOURCE)
        text = json.dumps(receipt)
        self.assertNotIn('synthetic-do-not-retain', text)
        self.assertNotIn('TALVEN_TEST_PRIVATE_VALUE', text)
        self.assertEqual(64, len(receipt['compiler']['environment_hash']))

    def test_bounded_process_limits_failure_and_timeout_cleanup(self):
        command = [sys.executable, '-c', 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())']
        self.assertEqual(b'input', run_bounded(command, b'input', dict(os.environ), 5, 10))
        for script, timeout, limit in [('import sys; print("x" * 200)', 5, 10),
                                       ('import sys; sys.stderr.write("x" * 70000)', 5, 100),
                                       ('import time; time.sleep(5)', 0.05, 100),
                                       ('import sys; sys.stderr.write("failure"); sys.exit(1)', 5, 100)]:
            with self.subTest(script=script), self.assertRaises(CompileError):
                run_bounded([sys.executable, '-c', script], b'', dict(os.environ), timeout, limit)

    def test_cli_prepares_checked_source_without_writing_source_or_running_program(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.tal'
            path.write_text('fn main() -> i32 { return 0; }')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, main(['prepare-c-units', str(path)]))
            receipt = json.loads(output.getvalue())
            self.assertEqual('talven.preprocessed-units.v1', receipt['schema'])
            self.assertEqual(['fn:main', 'entry'], [u['id'] for u in receipt['units']])
            self.assertEqual('fn main() -> i32 { return 0; }', path.read_text())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch('talven.preprocessed_units.MAX_PREPARED_BYTES', 100):
                self.assertEqual(1, main(['prepare-c-units', str(path)]))
            self.assertFalse(json.loads(output.getvalue())['ok'])

    def test_frozen_preprocessing_preserves_exact_static_text_across_function_objects(self):
        source = 'fn text() -> str { return "hé🙂\\0\\n"; } fn relay(s: str) -> str { return s; } fn main() -> i32 { return print(relay(text())); }'
        result = execute_prepared(prepare_c_units(source, console=True), sanitizer=True)
        self.assertEqual((0, 'hé🙂\0\n'.encode(), b''), (result.returncode, result.stdout, result.stderr))

    def test_frozen_preprocessing_preserves_borrowing_under_both_sanitizer_optimizations(self):
        for path in ('examples/borrowing.tal', 'tests/fixtures/borrowing-order.tal', 'tests/fixtures/borrowing-reborrow.tal'):
            prepared = prepare_c_units((ROOT / path).read_text())
            for optimization in ('-O0', '-O2'):
                with self.subTest(path=path, optimization=optimization):
                    result = execute_prepared(prepared, optimization=optimization, sanitizer=True)
                    self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))
