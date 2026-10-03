"""Independent resource source checking/emission and sanitized ledger acceptance."""
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
from talven.resources import analyze_resources
from tests.test_resources import INVALID, VALID, WORKLOAD, source_gate

BINARY = Path(os.environ.get('TALVEN_NATIVE', ROOT / 'experiments/native-compiler/target/release/talven-native')).resolve()


class NativeResourceTests(unittest.TestCase):
    def command(self, operation, source, directory, *options):
        path = directory / 'source.tal'
        path.write_text(source)
        return subprocess.run([str(BINARY), operation, str(path), '--resources', *options], capture_output=True, timeout=10)

    def test_diagnostics_match_original_source_codes_messages_and_utf16_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for label, source, _ in INVALID:
                source = '// 😀 inert prefix\n' + source
                with self.subTest(label=label):
                    try:
                        analyze_resources(source)
                    except CompileError as error:
                        expected = error.diagnostic(source)
                    result = self.command('check', source, directory, '--json')
                    self.assertEqual(1, result.returncode, result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertEqual('m2-supplied-blocks-v1', receipt['profile'])
                    for key in ('code', 'message', 'range'):
                        self.assertEqual(expected[key], receipt['diagnostics'][0][key], (label, key))

    def test_exact_formatter_c_and_successful_checked_resource_paths(self):
        long_capacity = 'fn f()->i32{region r(' + '0' * 5000 + '1){}return 0;}'
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for source in [*VALID, long_capacity, WORKLOAD]:
                if source != WORKLOAD:
                    source += 'fn main()->i32{return 0;}'
                checked = self.command('check', source, directory, '--json')
                self.assertEqual(0, checked.returncode, checked.stdout)
                emitted = self.command('emit-c', source, directory)
                self.assertEqual((0, b''), (emitted.returncode, emitted.stderr))
                self.assertEqual(emit_c(analyze_resources(source)).encode(), emitted.stdout)
                formatted = self.command('fmt', source, directory)
                self.assertEqual((0, b''), (formatted.returncode, formatted.stderr))
                self.assertEqual(format_source(source, resources=True).encode(), formatted.stdout)

    def producer_wrapper(self, directory, *, stale=False, mutate=False):
        wrapper = directory / 'producer'
        wrapper.write_text('#!' + sys.executable + '\n' +
            'import json, pathlib, subprocess, sys\n' +
            'result = subprocess.run(' + repr([str(BINARY)]) + ' + sys.argv[1:], capture_output=True)\n' +
            ('if sys.argv[1:] == ["--build-info"]:\n'
             '    info = json.loads(result.stdout)\n'
             '    info["source_files"]["../supplied-storage/runtime.h"] += "/* stale */"\n'
             '    result.stdout = json.dumps(info).encode()\n' if stale else '') +
            ('if sys.argv[1] == "emit-c":\n'
             '    with pathlib.Path(__file__).open("a") as stream: stream.write("# changed\\n")\n' if mutate else '') +
            'sys.stdout.buffer.write(result.stdout)\n'
            'sys.stderr.buffer.write(result.stderr)\n'
            'sys.exit(result.returncode)\n')
        wrapper.chmod(0o700)
        return wrapper

    def test_gate_rejects_stale_embedded_runtime_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            wrapper = self.producer_wrapper(Path(temporary), stale=True)
            with self.assertRaisesRegex(RuntimeError, 'embeds stale source: .*runtime.h'):
                source_gate(wrapper)

    def test_gate_rejects_producer_changed_during_emission(self):
        with tempfile.TemporaryDirectory() as temporary:
            wrapper = self.producer_wrapper(Path(temporary), mutate=True)
            with self.assertRaisesRegex(RuntimeError, 'producer changed during resource gate'):
                source_gate(wrapper)

    def test_independent_native_source_ledger_faults_and_dependency_gate(self):
        report = source_gate(BINARY)
        self.assertTrue(report['ok'])
        self.assertEqual(12, report['positive_executions'])
        self.assertEqual('native', report['producer'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
