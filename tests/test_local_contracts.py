import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from talven.__main__ import main
from talven.backend import emit_c_units
from talven.frontend import CompileError, analyze
from talven.preprocessed_units import prepare_c_units
from talven.unit_build import OBJECT_FLAGS, UnitBuildSession
from test_c_units import execute_units

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ('fn leaf(x: i32) -> i32 { return x + 1; } '
          'fn relay(x: i32) -> i32 { return leaf(x); } '
          'fn unrelated(y: i32) -> i32 { return y; } '
          'fn main() -> i32 { return relay(1) - 2; }\n')
RENAMED = SOURCE.replace('leaf(x: i32)', 'leaf(input: i32)').replace('return x + 1;', 'return input + 1;')
TYPED = ('fn leaf(flag: bool) -> i32 { if (flag) { return 1; } return 0; } '
         'fn relay(flag: bool) -> i32 { return leaf(flag); } '
         'fn unrelated(y: i32) -> i32 { return y; } '
         'fn main() -> i32 { return relay(true) - 1; }\n')


def frozen_execute(receipt):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        objects = []
        for index, unit in enumerate(receipt['units']):
            path, obj = directory / f'{index}.i', directory / f'{index}.o'
            path.write_text(unit['c'])
            subprocess.run(['cc', *OBJECT_FLAGS, '-x', 'cpp-output', '-c', str(path), '-o', str(obj)],
                           check=True, capture_output=True, timeout=30)
            objects.append(str(obj))
        program = directory / 'program'
        subprocess.run(['cc', *OBJECT_FLAGS, *objects, '-o', str(program)], check=True, capture_output=True, timeout=30)
        return subprocess.run([str(program)], capture_output=True, timeout=5)


class LocalContractTests(unittest.TestCase):
    def test_selected_prototypes_and_parameter_rename_leave_callers_eligible(self):
        analysis = analyze(SOURCE)
        legacy = emit_c_units(analysis)
        self.assertEqual(legacy, emit_c_units(analysis, local_contracts=False))
        before = emit_c_units(analysis, local_contracts=True)
        after = emit_c_units(analyze(RENAMED), local_contracts=True)
        declarations = [line for line in before['fn:relay'].splitlines() if line.startswith('int32_t tv_f_') and line.endswith(';')]
        self.assertEqual(['int32_t tv_f_leaf(int32_t);', 'int32_t tv_f_relay(int32_t);'], declarations)
        self.assertIn('int32_t tv_f_relay(int32_t tv_v_x) {', before['fn:relay'])
        self.assertEqual(['fn:leaf'], [name for name in before if before[name] != after[name]])
        global_after = emit_c_units(analyze(RENAMED))
        self.assertTrue(all(legacy[name] != global_after[name] for name in legacy))
        self.assertEqual(0, execute_units(RENAMED, local_contracts=True).returncode)

    def test_direct_signature_dependencies_and_declaration_insertion_reordering(self):
        before = emit_c_units(analyze(SOURCE), local_contracts=True)
        typed = emit_c_units(analyze(TYPED), local_contracts=True)
        self.assertEqual(['fn:leaf', 'fn:relay', 'fn:main'], [name for name in before if before[name] != typed[name]])
        inserted = 'fn added(value: i32) -> i32 { return value * 3; }\n' + SOURCE
        added = emit_c_units(analyze(inserted), local_contracts=True)
        self.assertTrue(all(before[name] == added[name] for name in before))
        functions = SOURCE.strip().split(' fn ')
        reordered = 'fn ' + ' fn '.join([functions[2], functions[0].removeprefix('fn '), functions[1], functions[3]])
        self.assertEqual(before, {name: code for name, code in emit_c_units(analyze(reordered), local_contracts=True).items()})
        self.assertEqual(0, execute_units(TYPED, local_contracts=True).returncode)

    def test_fresh_preparation_preserves_expanded_bytes_after_irrelevant_edits(self):
        before = prepare_c_units(SOURCE, local_contracts=True)
        renamed = prepare_c_units(RENAMED, local_contracts=True)
        inserted = prepare_c_units('fn added() -> i32 { return 7; }\n' + SOURCE, local_contracts=True)
        self.assertEqual('hosted-preprocessed-local-contracts-v1', before['profile'])
        original = {unit['id']: unit['c'] for unit in before['units']}
        changed = {unit['id']: unit['c'] for unit in renamed['units']}
        extra = {unit['id']: unit['c'] for unit in inserted['units']}
        self.assertEqual(['fn:leaf'], [name for name in original if original[name] != changed[name]])
        self.assertTrue(all(original[name] == extra[name] for name in original))
        for receipt in (before, renamed, inserted):
            result = frozen_execute(receipt)
            self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))
        self.assertEqual('hosted-preprocessed-units-v1', prepare_c_units(SOURCE)['profile'])

    def test_record_layouts_remain_global_and_recursion_forward_calls_execute(self):
        source = 'struct P { x: i32 } ' + SOURCE
        changed = source.replace('x: i32 }', 'x: i32, y: bool }')
        before = emit_c_units(analyze(source), local_contracts=True)
        after = emit_c_units(analyze(changed), local_contracts=True)
        self.assertTrue(all(before[name] != after[name] for name in before))
        recursion = ('fn even(n: i32) -> bool { if (n == 0) { return true; } return odd(n - 1); } '
                     'fn odd(n: i32) -> bool { if (n == 0) { return false; } return even(n - 1); } '
                     'fn main() -> i32 { if (even(8) && odd(7)) { return 0; } return 1; }')
        self.assertEqual(0, execute_units(recursion, local_contracts=True).returncode)
        self.assertEqual(0, frozen_execute(prepare_c_units(recursion, local_contracts=True)).returncode)

    def test_actual_reused_objects_reject_invalid_edits_repair_and_separate_profiles(self):
        with UnitBuildSession(stable_toolchain=True, local_contracts=True) as session:
            first = session.build(SOURCE)
            changed = session.build(RENAMED)
            self.assertEqual('hosted-object-local-contracts-v1', changed.receipt['profile'])
            self.assertEqual(['fn:leaf'], changed.receipt['compiled'])
            self.assertEqual(['fn:relay', 'fn:unrelated', 'fn:main', 'entry'], changed.receipt['reused'])
            # Independent C checks execute the actual cached objects, not a separately rebuilt subject.
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                driver = directory / 'oracle.c'
                driver.write_text('#include <stdint.h>\nextern int32_t tv_f_leaf(int32_t);\n'
                                  'extern int32_t tv_f_relay(int32_t);\nextern int32_t tv_f_main(void);\n'
                                  'int main(void) { if (tv_f_leaf(-1000) != -999 || tv_f_relay(0) != 1 '
                                  '|| tv_f_relay(1000000) != 1000001) return 1; return tv_f_main(); }\n')
                objects = [str(row[1]) for name, row in session._cache.items() if name != 'entry']
                program = directory / 'oracle'
                subprocess.run(['cc', *OBJECT_FLAGS, *objects, str(driver), '-o', str(program)],
                               check=True, capture_output=True, timeout=30)
                self.assertEqual(0, subprocess.run([str(program)], timeout=5).returncode)
            with patch('talven.preprocessed_units.run_bounded') as prepared_runner, \
                    patch('talven.unit_build.run_bounded') as object_runner, self.assertRaises(CompileError) as error:
                session.build(RENAMED.replace('return input + 1;', 'return false;'))
            self.assertEqual('E0201', error.exception.code)
            prepared_runner.assert_not_called()
            object_runner.assert_not_called()
            self.assertTrue(changed.executable.exists())
            repaired = session.build(RENAMED)
            self.assertEqual([], repaired.receipt['compiled'])
            session.local_contracts = False
            legacy = session.build(RENAMED)
            self.assertEqual('hosted-object-reuse-v1', legacy.receipt['profile'])
            self.assertEqual([], legacy.receipt['reused'])
            self.assertFalse(first.executable.exists())

    def test_local_borrow_units_preserve_sanitizer_results_at_both_optimizations(self):
        for fixture in ('examples/borrowing.tal', 'tests/fixtures/borrowing-reborrow.tal',
                        'tests/fixtures/borrowing-order.tal'):
            path = ROOT / fixture
            if not path.exists():
                self.fail('missing declared sanitizer fixture: ' + fixture)
            for optimization in ('-O0', '-O2'):
                with self.subTest(fixture=fixture, optimization=optimization):
                    result = execute_units(path.read_text(), local_contracts=True,
                                           optimization=optimization, sanitizer=True)
                    self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))

    def test_cli_profiles_and_invalid_boolean_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.tal'
            source.write_text(SOURCE)
            for command, profile in (('emit-c-units', 'hosted-c11-local-contracts-v1'),
                                     ('prepare-c-units', 'hosted-preprocessed-local-contracts-v1')):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(0, main([command, str(source), '--local-contracts']))
                self.assertEqual(profile, json.loads(output.getvalue())['profile'])
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(['dev', str(source), '--local-contracts'])
            self.assertEqual(2, error.exception.code)
        for call in (lambda: emit_c_units(analyze(SOURCE), local_contracts=1),
                     lambda: prepare_c_units(SOURCE, local_contracts='yes'),
                     lambda: UnitBuildSession(stable_toolchain=True, local_contracts=1)):
            with self.assertRaises(ValueError):
                call()

    def test_actual_reused_local_borrow_objects_preserve_both_sanitizer_optimizations(self):
        for optimization in ('-O0', '-O2'):
            flags = tuple(optimization if flag == '-O2' else flag for flag in OBJECT_FLAGS)
            flags += ('-fsanitize=address,undefined', '-fno-sanitize-recover=all')
            with patch('talven.unit_build.OBJECT_FLAGS', flags), \
                    UnitBuildSession(stable_toolchain=True, local_contracts=True) as session:
                for name in ('examples/borrowing.tal', 'tests/fixtures/borrowing-order.tal',
                             'tests/fixtures/borrowing-reborrow.tal'):
                    with self.subTest(optimization=optimization, fixture=name):
                        source = (ROOT / name).read_text()
                        session.build(source)
                        result = session.build(source + '\n// current reused local borrow objects\n')
                        self.assertEqual([], result.receipt['compiled'])
                        run = subprocess.run([str(result.executable)], capture_output=True, timeout=5)
                        self.assertEqual((0, b'', b''), (run.returncode, run.stdout, run.stderr))
