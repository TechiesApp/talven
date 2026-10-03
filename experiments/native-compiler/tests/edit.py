"""Read-only native edit previews, reference contracts and independent acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from talven.context import compiler_hash
from talven.edit_validation import snapshot_source, validate_edit

BINARY = Path(os.environ.get('TALVEN_NATIVE', ROOT / 'experiments/native-compiler/target/release/talven-native')).resolve()
VALID = 'fn main() -> i32 { return 0; }\n'

class NativeEditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source, self.candidate = self.root / 'source.tal', self.root / 'candidate.tal'
        self.source.write_text(VALID)
        self.candidate.write_text(VALID)

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, operation, *flags, source=None):
        path = self.source if source is None else source
        result = subprocess.run([str(BINARY), 'edit', operation, str(path), *map(str, flags)], capture_output=True, timeout=5)
        self.assertEqual(b'', result.stderr, result.stdout)
        self.assertTrue(result.stdout.endswith(b'\n'))
        packet = json.loads(result.stdout)
        self.assertEqual(0 if packet['ok'] else 1, result.returncode)
        return packet, result.stdout

    def snapshot(self, **kwargs):
        return self.command('snapshot', **kwargs)[0]

    def preview(self, *flags, expected_source=None, expected_compiler=None, candidate=None):
        snapshot = self.snapshot()
        return self.command('validate', '--candidate', self.candidate if candidate is None else candidate,
                            '--expect-source-hash', snapshot['source_hash'] if expected_source is None else expected_source,
                            '--expect-compiler-hash', snapshot['compiler_hash'] if expected_compiler is None else expected_compiler,
                            *flags)

    def compare(self, before, after):
        self.source.write_bytes(before.encode())
        self.candidate.write_bytes(after.encode())
        metadata = [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (self.source, self.candidate)]
        native, _ = self.preview()
        reference = validate_edit(self.source, self.candidate, expected_source_hash=hashlib.sha256(before.encode()).hexdigest(), expected_compiler_hash=compiler_hash())
        for key in ('ok', 'validation', 'source_hash', 'candidate_hash', 'source_bytes', 'candidate_bytes', 'candidate_changed', 'changes'):
            self.assertEqual(reference[key], native[key], key)
        for key in ('base', 'candidate'):
            self.assertEqual(reference[key]['ok'], native[key]['ok'])
            errors = [{k:v for k,v in d.items() if k != 'source'} for d in native[key]['diagnostics']]
            expected = [{k:v for k,v in d.items() if k != 'source'} for d in reference[key]['diagnostics']]
            self.assertEqual(expected, errors)
        for p, (data, inode, mtime) in zip((self.source, self.candidate), metadata):
            self.assertEqual((data, inode, mtime), (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns))
        return native

    def test_snapshot_invalid_syntax_unicode_crlf_exact_byte_budget(self):
        source = '// 😀\r\nfn broken(\r\n'
        self.source.write_bytes(source.encode())
        packet, output = self.command('snapshot', '--include-source')
        self.assertTrue(packet['ok'])
        self.assertEqual('not-run', packet['validation'])
        self.assertEqual(source, packet['untrusted_source_text'])
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), packet['source_hash'])
        self.assertEqual(output, self.command('snapshot', '--include-source', '--max-bytes', len(output))[1])
        failed = self.command('snapshot', '--include-source', '--max-bytes', len(output)-1)[0]
        self.assertEqual('E0703', failed['diagnostics'][0]['code'])
        self.assertNotIn('untrusted_source_text', failed)
        self.assertNotIn('untrusted_source_text', self.snapshot())
        for key in ('ok', 'validation', 'source_hash', 'source_bytes', 'diagnostics'):
            self.assertEqual(snapshot_source(self.source)[key], self.snapshot()[key])

    def test_contract_call_added_removed_and_kind_change_parity(self):
        before = 'struct P { x: i32 } fn read(p: &P)->i32{return p.x;} fn f(p:P)->i32{return p.x;} fn removed()->i32{return 1;}'
        after = 'struct P { x: i32, y: bool } fn read(p: &P)->i32{return p.x;} fn f(p:&P)->i32{return read(&p);} fn added()->i32{return 2;}'
        packet = self.compare(before, after)
        self.assertEqual(['f', 'P'], [c['name'] for c in packet['changes']['contracts_changed']])
        self.assertEqual(['f'], [c['name'] for c in packet['changes']['calls_changed']])
        self.compare('struct Item { value:i32 }', 'fn Item()->i32{return 0;}')
        self.compare('fn f(x:i32,y:bool)->i32{return x;}', 'fn f(y:bool,x:i32)->i32{return x;}')

    def test_invalid_base_repair_candidate_errors_and_utf16_ranges(self):
        invalid = '// 😀\nfn main()->i32{return false;}'
        packet = self.compare(invalid, VALID)
        self.assertTrue(packet['ok'])
        self.assertFalse(packet['base']['ok'])
        self.assertIsNone(packet['changes'])
        self.assertFalse(self.compare(VALID, invalid)['ok'])
        self.compare('struct P{x:i32} fn f(p:&P)->i32{return p.x;}',
                     'struct P{x:i32} fn f(p:&P)->i32{p.x=1;return p.x;}')

    def test_layout_body_only_changes_and_same_file_noop(self):
        packet = self.compare(VALID, '// note\nfn main()->i32{let mut x=1;x=x-1;return x;}')
        self.assertEqual({'added':[], 'removed':[], 'contracts_changed':[], 'calls_changed':[]}, packet['changes'])
        packet = self.preview(candidate=self.source)[0]
        self.assertTrue(packet['ok'])
        self.assertFalse(packet['candidate_changed'])

    def test_revision_guards_precede_missing_candidate_and_analysis(self):
        for overrides, code in (({'expected_compiler':'0'*64}, 'E0702'), ({'expected_source':'0'*64}, 'E0501'),
                                ({'expected_source':'BAD'}, 'E0701')):
            packet = self.preview(candidate=self.root/'absent', **overrides)[0]
            self.assertFalse(packet['ok'])
            self.assertEqual(code, packet['diagnostics'][0]['code'])
            self.assertIsNone(packet['candidate'])
        self.source.write_text('invalid syntax')
        self.assertEqual('E0501', self.preview(expected_source='0'*64)[0]['diagnostics'][0]['code'])

    def test_validation_exact_byte_budget_and_invalid_limits(self):
        packet, output = self.preview()
        self.assertTrue(packet['ok'])
        self.assertEqual(output, self.preview('--max-bytes', len(output))[1])
        failed = self.preview('--max-bytes', len(output)-1)[0]
        self.assertEqual('E0703', failed['diagnostics'][0]['code'])
        self.assertIsNone(failed['base'])
        for budget in (0, 1048577):
            self.assertEqual('E0701', self.preview('--max-bytes', budget)[0]['diagnostics'][0]['code'])

    def test_io_errors_are_input_tagged_and_never_analyzed(self):
        fifo = self.root/'fifo'
        os.mkfifo(fifo)
        for path in (self.root, fifo, self.root/'absent'):
            packet = self.command('snapshot', source=path)[0]
            self.assertEqual(('E0901', 'source'), (packet['diagnostics'][0]['code'], packet['diagnostics'][0]['input']))
            packet = self.preview(candidate=path)[0]
            self.assertEqual(('E0901', 'candidate'), (packet['diagnostics'][0]['code'], packet['diagnostics'][0]['input']))
        for data, code in ((b'\xff', 'E0901'), (b' '*(256*1024+1), 'E0005')):
            self.source.write_bytes(data)
            self.assertEqual(code, self.snapshot()['diagnostics'][0]['code'])
            self.source.write_text(VALID)
            self.candidate.write_bytes(data)
            packet = self.preview()[0]
            self.assertEqual(code, packet['diagnostics'][0]['code'])
            self.assertEqual('candidate', packet['diagnostics'][0]['input'])

    def test_usage_errors_precede_file_access(self):
        cases = [('snapshot', '--include-source', '--include-source'), ('snapshot', '--max-bytes'),
                 ('snapshot', '--max-bytes', '-1'), ('snapshot', '--candidate', 'file'), ('validate',),
                 ('validate', '--include-source'), ('snapshot', '--json'), ('apply',)]
        for operation, *flags in cases:
            with self.subTest(operation=operation, flags=flags):
                result = subprocess.run([str(BINARY), 'edit', operation, 'absent', *flags], capture_output=True, timeout=5)
                self.assertEqual((2, b''), (result.returncode, result.stdout))
                self.assertIn(b'Usage:', result.stderr)

    def test_frontend_success_still_requires_independent_behavior(self):
        before = 'struct Counter{value:i32} fn bump(c:&mut Counter,amount:i32)->i32{c.value=c.value+amount;return c.value;} fn exercise(c:&Counter,amount:i32)->i32{return bump(&mut c,amount);} fn main()->i32{return 0;}'
        repaired = before.replace('fn exercise(c:&Counter', 'fn exercise(c:&mut Counter')
        wrong = repaired.replace('return bump(&mut c,amount);', 'return bump(&mut c,amount)+1;')
        driver = ('#include <stdint.h>\nstruct tv_s_Counter{int32_t tv_m_value;};\n'
                  'extern int32_t tv_f_exercise(struct tv_s_Counter*,int32_t);\n'
                  'int main(void){const int32_t v[][3]={{0,0,0},{2,3,5},{-7,4,-3},{1000,-2,998}};'
                  'for(unsigned i=0;i<4;i++){struct tv_s_Counter c={v[i][0]};'
                  'if(tv_f_exercise(&c,v[i][1])!=v[i][2]||c.tv_m_value!=v[i][2])return 1;}return 0;}')
        for text, expected in ((repaired, 0), (wrong, 1)):
            self.assertTrue(self.compare(before, text)['ok'])
            emitted = subprocess.check_output([str(BINARY), 'emit-c', str(self.candidate)]).replace(b'int main(void)', b'int unused_main(void)')
            generated, check = self.root/'generated.c', self.root/'driver.c'
            generated.write_bytes(emitted)
            check.write_text(driver)
            for optimization in ('-O0','-O2'):
                binary = self.root/'accepted'
                subprocess.run(['cc','-std=c11', optimization, '-fno-lto','-Wall','-Wextra','-Werror','-pedantic-errors',str(generated),str(check),'-o',str(binary)], check=True, capture_output=True, timeout=30)
                result = subprocess.run([str(binary)], capture_output=True, timeout=5)
                self.assertEqual(expected, result.returncode)

if __name__ == '__main__':
    unittest.main(verbosity=2)
