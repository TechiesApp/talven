import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from talven.backend import emit_c
from talven.context import source_hash
from talven.frontend import CompileError, Span, analyze
from talven.preprocessed_units import FLAGS, run_bounded
from talven.unit_build import OBJECT_FLAGS, UnitBuildSession

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ('fn value() -> i32 { return 7; } '
          'fn keep(x: i32) -> i32 { return x + 1; } '
          'fn main() -> i32 { return keep(value()) - 8; }')


def execute(path):
    result = subprocess.run([str(path)], capture_output=True, timeout=5)
    return result.returncode, result.stdout, result.stderr


def ordinary_result(source, console=False):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        cfile, program = directory / 'program.c', directory / 'program'
        cfile.write_text(emit_c(analyze(source), console=console))
        subprocess.run(['cc', *FLAGS, '-Werror', str(cfile), '-o', str(program)],
                       capture_output=True, check=True, timeout=30)
        return execute(program)


class UnitBuildTests(unittest.TestCase):
    def test_acknowledgement_limits_and_closed_session(self):
        for selected in (False, None, 1, 'yes'):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                UnitBuildSession(stable_toolchain=selected)
        for timeout in (0, 61, float('nan'), float('inf'), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                UnitBuildSession(stable_toolchain=True, timeout=timeout)
        session = UnitBuildSession(stable_toolchain=True)
        root = session._root
        session.close()
        session.close()
        self.assertFalse(root.exists())
        with self.assertRaises(ValueError):
            session.build(SOURCE)

    def test_body_edit_reuses_unchanged_objects_and_current_link_matches_full_build(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            first = session.build(SOURCE)
            first_path = first.executable
            self.assertEqual(['fn:value', 'fn:keep', 'fn:main', 'entry'], first.receipt['compiled'])
            self.assertEqual([], first.receipt['reused'])
            changed = SOURCE.replace('return 7;', 'return 9;')
            second = session.build(changed)
            self.assertFalse(first_path.exists())
            self.assertEqual(['fn:value'], second.receipt['compiled'])
            self.assertEqual(['fn:keep', 'fn:main', 'entry'], second.receipt['reused'])
            self.assertEqual(source_hash(changed), second.receipt['source_hash'])
            self.assertEqual((2, b'', b''), execute(second.executable))
            self.assertEqual(ordinary_result(changed), execute(second.executable))
            third = session.build(changed + ' // current comment\n')
            self.assertEqual([], third.receipt['compiled'])
            self.assertEqual(['fn:value', 'fn:keep', 'fn:main', 'entry'], third.receipt['reused'])
            self.assertEqual(source_hash(changed + ' // current comment\n'), third.receipt['source_hash'])
            self.assertEqual(1, len(list(session._root.iterdir())))
        self.assertFalse(third.executable.exists())

    def test_global_contract_and_environment_changes_conservatively_recompile(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            session.build(SOURCE)
            changed = SOURCE.replace('keep(x: i32)', 'keep(amount: i32)').replace('return x + 1;', 'return amount + 1;')
            result = session.build(changed)
            self.assertEqual([], result.receipt['reused'])
            self.assertEqual(ordinary_result(changed), execute(result.executable))
            with patch.dict(os.environ, {'TALVEN_UNIT_BUILD_TEST': 'synthetic-new-environment'}):
                result = session.build(changed)
            self.assertEqual([], result.receipt['reused'])
            self.assertEqual(4, len(result.receipt['compiled']))

    def test_invalid_edits_leave_successful_objects_available_for_repair(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            successful = session.build(SOURCE)
            with patch('talven.preprocessed_units.run_bounded', side_effect=AssertionError('no invalid-source tools')):
                with self.assertRaises(CompileError):
                    session.build(SOURCE.replace('return 7;', 'return false;'))
            self.assertEqual((0, b'', b''), execute(successful.executable))
            self.assertEqual(1, len(list(session._root.iterdir())))
            repaired = session.build(SOURCE)
            self.assertEqual([], repaired.receipt['compiled'])
            self.assertEqual(4, len(repaired.receipt['reused']))

    def test_missing_corrupt_symlink_and_nonregular_objects_are_recompiled(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            session.build(SOURCE)
            for damage in ('corrupt', 'missing', 'symlink', 'fifo'):
                path = session._cache['fn:keep'][1]
                if damage == 'corrupt':
                    path.write_bytes(b'corrupt')
                else:
                    path.unlink()
                    if damage == 'symlink':
                        path.symlink_to(session._cache['fn:value'][1])
                    elif damage == 'fifo':
                        os.mkfifo(path)
                with self.subTest(damage=damage):
                    result = session.build(SOURCE)
                    self.assertEqual(['fn:keep'], result.receipt['compiled'])
                    self.assertEqual((0, b'', b''), execute(result.executable))

    def test_compile_link_failure_and_artifact_limits_never_promote_partial_cache(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            successful = session.build(SOURCE)
            changed = SOURCE.replace('return 7;', 'return 9;')
            for stage in ('compile', 'link'):
                def failing(command, *args, **kwargs):
                    if ('-c' in command) == (stage == 'compile'):
                        raise CompileError('E0402', 'test tool failure', Span(0, 0))
                    return run_bounded(command, *args, **kwargs)
                with self.subTest(stage=stage), patch('talven.unit_build.run_bounded', side_effect=failing):
                    with self.assertRaises(CompileError):
                        session.build(changed)
                self.assertEqual((0, b'', b''), execute(successful.executable))
                self.assertEqual(1, len(list(session._root.iterdir())))
            with patch('talven.unit_build.MAX_OBJECT_BYTES', 1), self.assertRaises(CompileError):
                session.build(changed)
            with patch('talven.unit_build.MAX_ARTIFACT_BYTES', 1), self.assertRaises(CompileError):
                session.build(changed)
            result = session.build(SOURCE)
            self.assertEqual([], result.receipt['compiled'])

    def test_linker_object_mutation_and_final_compiler_drift_reject_publication(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            successful = session.build(SOURCE)
            def mutating(command, *args, **kwargs):
                result = run_bounded(command, *args, **kwargs)
                if '-c' not in command:
                    next(Path(value) for value in command if value.endswith('.o')).write_bytes(b'changed after link')
                return result
            with patch('talven.unit_build.run_bounded', side_effect=mutating), self.assertRaises(CompileError):
                session.build(SOURCE)
            with patch('talven.unit_build.executable_hash', return_value='changed'), self.assertRaises(CompileError) as caught:
                session.build(SOURCE)
            self.assertEqual('E0501', caught.exception.code)
            self.assertEqual((0, b'', b''), execute(successful.executable))
            with patch('talven.unit_build.compiler_hash', return_value='changed'), self.assertRaises(CompileError):
                session.build(SOURCE)
            self.assertEqual(1, len(list(session._root.iterdir())))
            self.assertEqual([], session.build(SOURCE).receipt['compiled'])

    def test_current_exact_static_output_after_reused_callers(self):
        source = ('fn text() -> str { return "hé🙂\\0\\n"; } fn relay(s: str) -> str { return s; } '
                  'fn main() -> i32 { return print(relay(text())); }')
        with UnitBuildSession(stable_toolchain=True, console=True) as session:
            session.build(source)
            changed = source.replace('hé🙂', 'new🙂')
            result = session.build(changed)
            self.assertEqual(['fn:text'], result.receipt['compiled'])
            self.assertEqual((0, 'new🙂\0\n'.encode(), b''), execute(result.executable))
            self.assertEqual(ordinary_result(changed, True), execute(result.executable))

    def test_borrowing_stores_and_checked_traps_agree_with_fresh_native_build(self):
        with UnitBuildSession(stable_toolchain=True) as session:
            for path in ('examples/borrowing.tal', 'tests/fixtures/borrowing-order.tal',
                         'tests/fixtures/borrowing-reborrow.tal', 'examples/scalars.tal'):
                source = (ROOT / path).read_text()
                session.build(source)
                result = session.build(source + '\n// reused current source\n')
                self.assertEqual([], result.receipt['compiled'])
                self.assertEqual(ordinary_result(source), execute(result.executable))
            trap = 'fn overflow(x: i32) -> i32 { return x + 1; } fn main() -> i32 { return overflow(2147483647); }'
            session.build(trap)
            result = session.build(trap + '\n')
            self.assertEqual(-signal.SIGABRT, execute(result.executable)[0])
            self.assertEqual(ordinary_result(trap)[0], execute(result.executable)[0])

    def test_reused_borrow_objects_preserve_sanitizer_behavior_at_o0_and_o2(self):
        for optimization in ('-O0', '-O2'):
            flags = tuple(optimization if flag == '-O2' else flag for flag in OBJECT_FLAGS)
            flags += ('-fsanitize=address,undefined', '-fno-sanitize-recover=all')
            with patch('talven.unit_build.OBJECT_FLAGS', flags), UnitBuildSession(stable_toolchain=True) as session:
                for path in ('examples/borrowing.tal', 'tests/fixtures/borrowing-order.tal',
                             'tests/fixtures/borrowing-reborrow.tal'):
                    with self.subTest(optimization=optimization, path=path):
                        source = (ROOT / path).read_text()
                        session.build(source)
                        result = session.build(source + '\n// reused sanitizer objects\n')
                        self.assertEqual([], result.receipt['compiled'])
                        self.assertEqual((0, b'', b''), execute(result.executable))
