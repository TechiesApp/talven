"""Reference module resolution, independent native checking of flattened source.

The Rust executable does not resolve module graphs or accept raw module syntax.
Both lowerings must produce the same C for the resolved core-profile source.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from talven.backend import emit_c
from talven.project import analyze_project

BINARY = Path(os.environ.get('TALVEN_NATIVE', ROOT/'experiments/native-compiler/target/release/talven-native')).resolve()


class NativeProjectTests(unittest.TestCase):
    def emit(self, project, root, console=False):
        source = root/'flattened.tal'
        source.write_text(project.flattened)
        result = subprocess.run([str(BINARY), 'emit-c', str(source), *(['--console'] if console else [])],
                                capture_output=True, timeout=10)
        self.assertEqual((0,b''), (result.returncode,result.stderr), result.stdout)
        reference = emit_c(project.analysis, console=console).encode()
        self.assertEqual(reference, result.stdout)
        return reference, result.stdout

    def test_module_artifacts_match_for_records_borrows_aliases_and_static_text(self):
        cases = [{'main.tal': 'import "lib.tal" {message}; fn main()->i32{return print(message());}',
                  'lib.tal': 'pub fn message()->str{return "é😀\\0\\n";}'},
                 {p.name: p.read_text() for p in (ROOT/'examples/modules').glob('*.tal')},
                 {'main.tal': 'import "lib.tal" {P as Data, make as create}; fn main()->i32{let p=create(7);let moved=p;return moved.x-7;}',
                  'lib.tal': 'pub struct P{x:i32} pub fn make(x:i32)->P{return P{x:x};}'}]
        with tempfile.TemporaryDirectory() as temporary:
            for sources in cases:
                with self.subTest(sources=list(sources)):
                    self.emit(analyze_project('main.tal', sources), Path(temporary), console=True)

    def test_independent_native_oracle_with_sanitizers_at_both_optimizations(self):
        sources = {p.name: p.read_text() for p in (ROOT/'examples/modules').glob('*.tal')}
        project = analyze_project('main.tal', sources)
        symbol = 'tv_f_' + project.scopes['main.tal']['calculate']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for producer, generated in zip(('reference', 'native'), self.emit(project, root)):
                (root/'generated.c').write_bytes(generated)
                driver = root/'driver.c'
                driver.write_text('''#define main talven_example_main
#include "generated.c"
#undef main
int main(void) {
    int32_t inputs[] = {INT32_MIN, -1001, -1000, -1, 0, 1, 35, 1000, 1001, INT32_MAX};
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {
        int32_t bounded = inputs[i] < -1000 ? -1000 : inputs[i] > 1000 ? 1000 : inputs[i];
        int32_t expected = bounded * 2 + 12;
        if (SYMBOL(inputs[i]) != expected) return 1;
    }
    return 0;
}
'''.replace('SYMBOL', symbol))
                for optimization in ('-O0', '-O2'):
                    with self.subTest(producer=producer, optimization=optimization):
                        binary = root/'check'
                        subprocess.run(['cc', '-std=c11', optimization, '-Wall', '-Wextra', '-Werror',
                                        '-pedantic-errors', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                                        str(driver), '-o', str(binary)], check=True, capture_output=True, timeout=30)
                        result = subprocess.run([str(binary)], capture_output=True, timeout=5)
                        self.assertEqual((0,b'',b''), (result.returncode,result.stdout,result.stderr))

    def test_raw_module_syntax_is_not_claimed_as_native_resolver_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'module.tal'
            path.write_text('pub fn f()->i32{return 0;}')
            result = subprocess.run([str(BINARY), 'check', str(path), '--json'], capture_output=True, timeout=5)
            self.assertEqual(1, result.returncode)


if __name__ == '__main__':
    unittest.main(verbosity=2)
