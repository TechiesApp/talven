import contextlib
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from talven.__main__ import main
from talven.backend import emit_c_units
from talven.context import compiler_hash, source_hash
from talven.frontend import CompileError, analyze

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic-errors', '-fno-lto']


def execute_units(source, *, console=False, optimization='-O2', sanitizer=False, driver=None, local_contracts=False):
    units = emit_c_units(analyze(source), console=console, local_contracts=local_contracts)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        objects = []
        flags = [*FLAGS, optimization]
        if sanitizer:
            flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        for index, (identity, code) in enumerate(units.items()):
            cfile, obj = directory / f'{index}.c', directory / f'{index}.o'
            cfile.write_text(code)
            options = ['-Dmain=talven_units_entry'] if driver and identity == 'entry' else []
            subprocess.run(['cc', *flags, *options, '-c', str(cfile), '-o', str(obj)],
                           check=True, capture_output=True, timeout=30)
            objects.append(str(obj))
        if driver:
            cfile = directory / 'driver.c'
            cfile.write_text(driver)
            objects.append(str(cfile))
        executable = directory / 'program'
        subprocess.run(['cc', *flags, *objects, '-o', str(executable)],
                       check=True, capture_output=True, timeout=30)
        return subprocess.run([str(executable)], capture_output=True, timeout=5)


class CUnitTests(unittest.TestCase):
    def test_function_units_have_stable_temporaries_after_unrelated_body_and_trivia_edits(self):
        before = 'fn first(x: i32) -> i32 { return x + 1; } fn keep(x: i32) -> i32 { return x * 2; } fn main() -> i32 { return keep(first(2)) - 6; }'
        after = before.replace('return x + 1;', 'let y = x + 2; return y + 1;')
        original, changed = emit_c_units(analyze(before)), emit_c_units(analyze(after))
        self.assertNotEqual(original['fn:first'], changed['fn:first'])
        self.assertEqual(original['fn:keep'], changed['fn:keep'])
        self.assertEqual(original['fn:main'], changed['fn:main'])
        self.assertEqual(original, emit_c_units(analyze('// 😀 shifted\n' + before)))
        self.assertEqual(['fn:first', 'fn:keep', 'fn:main', 'entry'], list(original))

    def test_global_contract_changes_invalidate_unit_text_conservatively(self):
        source = 'struct P { x: i32 } fn read(p: &P) -> i32 { return p.x; } fn main() -> i32 { let p = P { x: 1 }; return read(&p) - 1; }'
        original = emit_c_units(analyze(source))
        renamed = emit_c_units(analyze(source.replace('read(p: &P)', 'read(input: &P)').replace('return p.x;', 'return input.x;')))
        changed = emit_c_units(analyze(source.replace('x: i32 }', 'x: i32, ok: bool }').replace('x: 1 }', 'x: 1, ok: true }')))
        for candidate in (renamed, changed):
            self.assertTrue(all(original[name] != candidate[name] for name in original))

    def test_console_helpers_are_local_and_entry_identity_cannot_collide(self):
        source = 'fn entry() -> i32 { return print("ok"); } fn quiet() -> i32 { return 0; } fn main() -> i32 { return entry(); }'
        units = emit_c_units(analyze(source), console=True)
        self.assertIn('static int32_t tv_console_print', units['fn:entry'])
        for identity in ('fn:quiet', 'fn:main', 'entry'):
            self.assertNotIn('tv_console_print', units[identity])
        for identity in units:
            self.assertNotIn('talven_trap', units[identity])
        executed = execute_units(source, console=True)
        self.assertEqual((0, b'ok', b''), (executed.returncode, executed.stdout, executed.stderr))

    def test_unit_emission_requires_hosted_entry_console_and_bounded_complete_output(self):
        for source, code in [('fn other() -> i32 { return 0; }', 'E0401'),
                             ('fn main() -> bool { return true; }', 'E0401'),
                             ('fn unused() -> i32 { return print("x"); } fn main() -> i32 { return 0; }', 'E0404')]:
            with self.subTest(source=source), self.assertRaises(CompileError) as caught:
                emit_c_units(analyze(source))
            self.assertEqual(code, caught.exception.code)
        source = 'fn other() -> i32 { return 1; } fn main() -> i32 { return other(); }'
        for name, value in [('MAX_C_UNITS', 1), ('MAX_C_UNIT_BYTES', 100)]:
            with self.subTest(limit=name), patch('talven.backend.' + name, value), self.assertRaises(CompileError) as caught:
                emit_c_units(analyze(source))
            self.assertEqual('E0005', caught.exception.code)

    def test_cli_emits_deterministic_current_source_and_code_identities_without_execution(self):
        source = 'fn main() -> i32 { return 0; }'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.tal'
            path.write_text(source)
            results = []
            with patch('subprocess.run', side_effect=AssertionError('emission must not execute')):
                for _ in range(2):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(0, main(['emit-c-units', str(path)]))
                    results.append(output.getvalue())
            self.assertEqual(results[0], results[1])
            receipt = json.loads(results[0])
            self.assertEqual('talven.c-units.v1', receipt['schema'])
            self.assertEqual('hosted-c11-units-v1', receipt['profile'])
            self.assertEqual(source_hash(source), receipt['source_hash'])
            self.assertEqual(compiler_hash(), receipt['compiler_hash'])
            self.assertEqual(['fn:main', 'entry'], [u['id'] for u in receipt['units']])
            self.assertTrue(all(u['c_hash'] == source_hash(u['c']) for u in receipt['units']))
            self.assertEqual(source, path.read_text())

    def test_cli_failure_has_no_partial_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.tal'
            for source in ['fn main() -> i32 { return false; }', 'fn main() -> i32 { return 0; }']:
                path.write_text(source)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), patch('talven.__main__.MAX_C_UNIT_BYTES', 100):
                    self.assertEqual(1, main(['emit-c-units', str(path)]))
                receipt = json.loads(output.getvalue())
                self.assertEqual('talven.diagnostics.v1', receipt['schema'])
                self.assertFalse(receipt['ok'])
                self.assertNotIn('units', receipt)

    def test_separate_objects_preserve_forward_calls_recursion_and_full_i32_results(self):
        source = 'fn main() -> i32 { return 0; } fn relay(x: i32) -> i32 { return later(x); } fn later(x: i32) -> i32 { if (x == 0) { return 70000; } return later(x - 1) + 1; }'
        driver = '#include <stdint.h>\nextern int32_t tv_f_relay(int32_t);\nint main(void) { return tv_f_relay(3) == 70003 && tv_f_relay(0) == 70000 ? 0 : 1; }\n'
        result = execute_units(source, driver=driver)
        self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))

    def test_separate_objects_preserve_utf8_nul_static_views_and_source_order(self):
        text = 'hé🙂\\0' * 5 + '\\n'
        source = f'fn text() -> str {{ return "{text}"; }} fn relay(s: str) -> str {{ return s; }} fn mark(s: str) -> i32 {{ return print(s); }} fn combine(a: i32, b: i32) -> i32 {{ return a + b; }} fn main() -> i32 {{ print(relay(text())); return combine(mark("a"), mark("b")); }}'
        result = execute_units(source, console=True, sanitizer=True)
        self.assertEqual((0, ('hé🙂\0' * 5 + '\nab').encode(), b''), (result.returncode, result.stdout, result.stderr))

    def test_separate_objects_preserve_record_results_and_mutable_scalars(self):
        source = ('struct P { x: i32, ok: bool } '
                  'fn make(x: i32) -> P { return P { x: x + 1, ok: true }; } '
                  'fn adjust(p: P) -> P { let mut q = p; q.x = q.x + 3; return q; } '
                  'fn result(p: P) -> i32 { if (p.ok) { return p.x; } return -1; } '
                  'fn main() -> i32 { let mut n = 10; let mut enabled = false; '
                  'n = n + 2; enabled = !enabled; '
                  'if (enabled) { return result(adjust(make(n))) - 16; } return 1; }')
        driver = ('#include <stdint.h>\n#include <stdbool.h>\n'
                  'struct tv_s_P { int32_t tv_m_x; bool tv_m_ok; };\n'
                  'extern struct tv_s_P tv_f_make(int32_t);\n'
                  'extern struct tv_s_P tv_f_adjust(struct tv_s_P);\n'
                  'extern int32_t tv_f_result(struct tv_s_P);\n'
                  'extern int32_t tv_f_main(void);\n'
                  'int main(void) { return tv_f_result(tv_f_adjust(tv_f_make(100000))) == 100004 '
                  '&& tv_f_result(tv_f_adjust(tv_f_make(-1000))) == -996 && tv_f_main() == 0 ? 0 : 1; }\n')
        result = execute_units(source, driver=driver, sanitizer=True)
        self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))

    def test_separate_objects_keep_overflow_division_traps_and_short_circuit(self):
        for expression in ('2147483647 + 1', '-2147483648 / -1', '1 / 0', '1 % 0'):
            with self.subTest(expression=expression):
                source = f'fn bomb() -> i32 {{ return {expression}; }} fn main() -> i32 {{ return bomb(); }}'
                result = execute_units(source, sanitizer=True)
                self.assertEqual(-signal.SIGABRT, result.returncode)
                self.assertNotIn(b'runtime error', result.stderr)
                self.assertNotIn(b'ERROR: AddressSanitizer', result.stderr)
        source = 'fn bomb() -> bool { return (1 / 0) == 0; } fn main() -> i32 { if (false && bomb()) { return 1; } if (true || bomb()) { return 0; } return 1; }'
        result = execute_units(source, sanitizer=True)
        self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))

    def test_separate_objects_preserve_borrow_reborrow_and_ordering_under_sanitizers(self):
        for path in ('examples/borrowing.tal', 'tests/fixtures/borrowing-order.tal', 'tests/fixtures/borrowing-reborrow.tal'):
            for optimization in ('-O0', '-O2'):
                with self.subTest(path=path, optimization=optimization):
                    result = execute_units((ROOT / path).read_text(), sanitizer=True, optimization=optimization)
                    self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))
