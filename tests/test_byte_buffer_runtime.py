import importlib.util
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('byte_buffer_gate', ROOT / 'scripts/check-byte-buffer-runtime.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ByteBufferRuntimeTests(unittest.TestCase):
    def test_independent_ledger_faults_traps_and_dependencies(self):
        report = gate.verify()
        self.assertTrue(report['ok'] and report['complete'] and report['passed'])
        self.assertEqual('talven.byte-buffer-runtime-check.v1', report['schema'])
        self.assertEqual('c11-supplied-byte-buffer-v1', report['profile'])
        self.assertEqual(12, report['positive_executions'])
        self.assertEqual(144, report['negative_trap_executions'])
        self.assertEqual(set(gate.SOURCES), {entry['path'] for entry in report['inputs']})
        for capacity in (1, 32, 4096):
            layouts = [row['layout'] for row in report['executions'] if row['layout']['capacity'] == capacity]
            self.assertEqual(4, len(layouts))
            self.assertTrue(all(row == layouts[0] for row in layouts))
        for artifact in report['artifacts']:
            self.assertEqual(artifact['initial'], artifact['final'])
        for tool in report['tools'].values():
            self.assertEqual(tool['initial'], tool['final'])
        self.assertEqual(42, report['unknown_probe']['returncode'])
        self.assertEqual('C-runtime-only; no Talven lifetime checking', report['validation'])

    def compile_driver(self, directory, header):
        for relative in (gate.SOURCES[0], gate.SOURCES[2]):
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        target = directory / gate.SOURCES[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(header)
        binary = directory / 'check'
        command = ['cc', *gate.FLAGS, '-O0', '-DCAPACITY=1', str(directory / gate.SOURCES[2]), '-o', str(binary)]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, compiled.returncode, compiled.stderr)
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)

    def test_behavioral_mutations_are_rejected_by_compiled_independent_oracle(self):
        source = (ROOT / gate.SOURCES[1]).read_text()
        mutations = {
            'missing-push-write': ('region->storage[buffer->length] = (uint8_t)value;', '(void)region;'),
            'missing-length-increment': ('buffer->length += 1;', 'buffer->length += 0;'),
            'wrong-pop-value': ('int32_t value = region->storage[buffer->length - 1];',
                                'int32_t value = region->storage[buffer->length - 1] ^ 1;'),
            'invalid-byte-before-full': (
                'if (buffer->length == buffer->block.length) { return TV_BUFFER_FULL; }\n    if (value < 0 || value > 255) { return TV_BUFFER_INVALID_BYTE; }',
                'if (value < 0 || value > 255) { return TV_BUFFER_INVALID_BYTE; }\n    if (buffer->length == buffer->block.length) { return TV_BUFFER_FULL; }'),
        }
        with tempfile.TemporaryDirectory(prefix='talven-buffer-mutations-') as temp:
            result = self.compile_driver(Path(temp) / 'baseline', source)
            self.assertEqual(0, result.returncode, result.stderr)
            for name, (old, new) in mutations.items():
                with self.subTest(mutation=name):
                    self.assertEqual(1, source.count(old))
                    result = self.compile_driver(Path(temp) / name, source.replace(old, new))
                    self.assertEqual(41, result.returncode, result.stderr)
                    self.assertIn('oracle:', result.stderr)

    def test_strict_layout_rejects_wrong_shape_bool_float_duplicates(self):
        valid = {'capacity': 1, 'descriptor_bytes': 48, 'block_bytes': 32, 'buffer_bytes': 40,
                 'allocation_bytes': 48, 'pop_result_bytes': 8}
        self.assertEqual(valid, gate.layout(json.dumps(valid), 1))
        for value in (True, 1.0, 0, -1, '1', None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                gate.layout(json.dumps(dict(valid, capacity=value)), 1)
        for output in ('[]', '{}', json.dumps(dict(valid, unexpected=1)),
                       json.dumps(valid)[:-1] + ',"capacity":1}', json.dumps(valid).replace('48', 'NaN', 1)):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                gate.layout(output, 1)

    def test_nm_accepts_only_exact_known_gnu_and_macho_undefined_rows(self):
        self.assertEqual(['GLOBAL_OFFSET_TABLE_', 'abort', 'stack_chk_fail'],
                         gate.undefined_symbols('                 U abort\n U __stack_chk_fail\n U _GLOBAL_OFFSET_TABLE_\n', 'Linux'))
        self.assertEqual(['abort', 'bzero', 'chkstk_darwin', 'stack_chk_fail'],
                         gate.undefined_symbols('_abort\n_bzero\n___stack_chk_fail\n___chkstk_darwin\n', 'Darwin'))
        for output, system in ((' U malloc\n', 'Linux'), (' U tv_region_test_fault\n', 'Linux'),
                               ('abort\n', 'Linux'), (' T abort\n', 'Linux'), ('__abort\n', 'Darwin'),
                               ('_malloc\n', 'Darwin'), ('archive.o:\n U abort\n', 'Linux')):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                gate.undefined_symbols(output, system)

    def test_nonzero_oracle_and_sanitizer_failures_never_count_as_contract_traps(self):
        for returncode, stderr, stdout in ((41, 'oracle:1\n', ''), (42, '', ''),
                                          (-signal.SIGABRT, 'oracle:1\n', ''),
                                          (-signal.SIGABRT, 'AddressSanitizer: bad\n', ''),
                                          (-signal.SIGABRT, 'runtime error: bad\n', ''),
                                          (-signal.SIGABRT, '', 'unexpected')):
            with self.subTest(returncode=returncode, stderr=stderr), self.assertRaises(RuntimeError):
                gate.accept_trap({'returncode': returncode, 'stderr': stderr, 'stdout': stdout}, 'test')
        gate.accept_trap({'returncode': -signal.SIGABRT, 'stderr': '', 'stdout': ''}, 'test')

    def test_gate_rejects_input_mutation_during_real_tool_run(self):
        actual_run = subprocess.run
        with tempfile.TemporaryDirectory(prefix='talven-buffer-stability-') as temp:
            root = Path(temp)
            for name in gate.SOURCES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            def mutate(command, **kwargs):
                result = actual_run(command, **kwargs)
                target = root / gate.SOURCES[1]
                target.write_bytes(target.read_bytes() + b'\n/* changed during gate */\n')
                return result
            with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=mutate):
                with self.assertRaisesRegex(RuntimeError, 'Observed gate input change'):
                    gate.verify()

    def test_gate_rejects_compiled_artifact_mutation_during_real_execution(self):
        actual_run = subprocess.run
        def mutate(command, **kwargs):
            result = actual_run(command, **kwargs)
            binary = Path(command[0])
            if len(command) == 1 and binary.name.startswith('check-'):
                # Linux can retain the executable inode after wait returns.
                replacement = binary.with_suffix('.replacement')
                replacement.write_bytes(binary.read_bytes() + b'changed artifact')
                replacement.chmod(binary.stat().st_mode)
                replacement.replace(binary)
            return result
        with patch.object(gate.subprocess, 'run', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'Observed compiled artifact change'):
                gate.verify()

    def test_gate_rejects_tool_mutation_before_first_use(self):
        actual_run = subprocess.run
        actual_which = shutil.which
        with tempfile.TemporaryDirectory(prefix='talven-buffer-tool-stability-') as temp:
            tool = Path(temp) / 'uname'
            shutil.copyfile(actual_which('uname'), tool)
            tool.chmod(0o755)
            def which(name):
                return str(tool) if name == 'uname' else actual_which(name)
            def mutate(command, **kwargs):
                result = actual_run(command, **kwargs)
                tool.write_bytes(tool.read_bytes() + b'changed tool')
                return result
            with patch.object(gate.shutil, 'which', side_effect=which), patch.object(gate.subprocess, 'run', side_effect=mutate):
                with self.assertRaisesRegex(RuntimeError, 'Tool executable changed before use: uname'):
                    gate.verify()

    def test_stability_checks_compare_actual_bytes_and_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input'
            path.write_bytes(b'original')
            identity = gate.fingerprint(path)
            gate.check_bytes(path, b'original')
            gate.check_artifacts({path: identity})
            path.write_bytes(b'mutation')
            with self.assertRaisesRegex(RuntimeError, 'input change'):
                gate.check_bytes(path, b'original')
            with self.assertRaisesRegex(RuntimeError, 'artifact change'):
                gate.check_artifacts({path: identity})

    def test_out_refuses_existing_file_before_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'receipt.json'
            output.write_text('preserved')
            with patch.object(gate.sys, 'argv', ['check-byte-buffer-runtime.py', '--out', str(output)]), patch.object(gate, 'verify') as verify:
                with self.assertRaises(SystemExit):
                    gate.main()
                verify.assert_not_called()
            self.assertEqual('preserved', output.read_text())


if __name__ == '__main__':
    unittest.main()
