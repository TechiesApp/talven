"""Independent native parsing/checking, exact C and sanitized outcome drivers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from talven.backend import emit_c
from talven.formatter import format_source
from talven.frontend import CompileError
from talven.outcomes import analyze_outcomes
from tests.test_outcomes import DRIVER, INVALID, VALID, compile_driver

BINARY = Path(os.environ.get('TALVEN_NATIVE', ROOT / 'experiments/native-compiler/target/release/talven-native')).resolve()


class NativeOutcomeTests(unittest.TestCase):
    def command(self, operation, source, directory, *options):
        path = directory / 'source.tal'
        path.write_text(source)
        return subprocess.run([str(BINARY), operation, str(path), '--outcomes', *options], capture_output=True, timeout=10)

    def test_diagnostics_match_reference_codes_messages_utf16_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for label, source, _ in INVALID:
                source = '// 😀 inert prefix\n' + source
                with self.subTest(label=label):
                    try:
                        analyze_outcomes(source)
                    except CompileError as error:
                        expected = error.diagnostic(source)
                    result = self.command('check', source, directory, '--json')
                    self.assertEqual(1, result.returncode, result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertEqual('m2-concrete-outcomes-v1', receipt['profile'])
                    actual = receipt['diagnostics'][0]
                    for key in ('code', 'message', 'range'):
                        self.assertEqual(expected[key], actual[key], (label, key))

    def test_successful_ownership_join_and_exact_c_and_formatter(self):
        example = (ROOT / 'examples/outcomes/decision.tal').read_text()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for source in [*VALID, example]:
                if source != example:
                    source += ' fn main()->i32{return 0;}'
                checked = self.command('check', source, directory, '--json')
                self.assertEqual(0, checked.returncode, checked.stdout)
                generated = self.command('emit-c', source, directory)
                self.assertEqual((0, b''), (generated.returncode, generated.stderr))
                self.assertEqual(emit_c(analyze_outcomes(source)).encode(), generated.stdout)
                formatted = self.command('fmt', source, directory)
                self.assertEqual((0, b''), (formatted.returncode, formatted.stderr))
                self.assertEqual(format_source(source, outcomes=True).encode(), formatted.stdout)

    def test_native_variant_execution_and_invalid_tag_with_sanitizers(self):
        example = (ROOT / 'examples/outcomes/decision.tal').read_text()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            generated = self.command('emit-c', example, directory).stdout.decode()
            # A dedicated foreign C caller checks the match boundary itself;
            # it never extracts the invalid outcome's inactive union member.
            source = 'outcome R{A(i32),B} fn handle(r:R)->i32{match(r){R::A(x){return x;}R::B{return 0;}}} fn main()->i32{return 0;}'
            guard = self.command('emit-c', source, directory).stdout.decode()
            invalid = '#define main talven_example_main\n#include "generated.c"\n#undef main\nint main(void){struct tv_s_R r={.tv_tag=99};return tv_f_handle(r);}\n'
            for optimization in ('-O0', '-O2'):
                result = compile_driver(generated, DRIVER, directory, optimization)
                self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))
                result = compile_driver(guard, invalid, directory, optimization)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn(b'runtime error:', result.stderr)
                self.assertNotIn(b'ERROR: AddressSanitizer', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
