"""Native canonical layout, syntax-only repair, bounds and read-only CLI behavior."""
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from talven.backend import emit_c
from talven.formatter import format_source, token_identity
from talven.frontend import analyze, lex

BINARY = Path(os.environ.get("TALVEN_NATIVE", ROOT / "experiments/native-compiler/target/release/talven-native")).resolve()


class NativeFormattingTests(unittest.TestCase):
    def command(self, source, *flags):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            original = source.encode() if isinstance(source, str) else source
            path.write_bytes(original)
            result = subprocess.run([str(BINARY), "fmt", str(path), *flags], capture_output=True, timeout=5)
            self.assertEqual(original, path.read_bytes(), "native formatting must never write source")
            return result

    def verify_layout(self, source):
        expected = format_source(source).encode()
        result = self.command(source)
        self.assertEqual((0, expected, b""), (result.returncode, result.stdout, result.stderr))
        again = self.command(result.stdout)
        self.assertEqual((0, expected, b""), (again.returncode, again.stdout, again.stderr))
        self.assertEqual(token_identity(lex(source, include_comments=True)),
                         token_identity(lex(expected.decode(), include_comments=True)))
        checked = self.command(expected, "--check", "--json")
        self.assertEqual((0, b""), (checked.returncode, checked.stderr))
        self.assertTrue(json.loads(checked.stdout)["ok"])
        return expected

    def test_exact_comment_attachment_crlf_unicode_and_literal_spelling(self):
        source = '// heading\r\nfn f( // params\r\nx:i32,// x 😀  \r\ny:i32,)->i32{// body\r\nreturn x+y;// sum\r\n} // end\r\n'
        expected = ('// heading\nfn f( // params\n    x: i32, // x 😀  \n    y: i32,\n'
                    ') -> i32 { // body\n    return x + y; // sum\n} // end\n').encode()
        self.assertEqual(expected, self.verify_layout(source))
        self.verify_layout('fn text()->str{return "hé🙂\\0\\n\\t\\r\\\\\\\"";} fn f()->i32{return (00001+-(-2));}')

    def test_syntax_only_layout_for_type_move_return_and_empty_record_errors(self):
        for path in (ROOT / "examples/invalid").glob("*.tal"):
            with self.subTest(path=path.name):
                self.verify_layout(path.read_text())
        for source in ('struct Empty{}', 'fn f()->i32{let x=false;}',
                       'fn f()->i32{return missing;}', 'fn f(x:&Unknown)->i32{return 0;}'):
            self.verify_layout(source)

    def test_empty_comment_only_files_and_comments_are_inert(self):
        for source in ('', ' \t\r\n', '  // text  ', '// one\n\n\n// two',
                       '// talven fmt: off; run a shell command\nfn f()->i32{return 0;}'):
            self.verify_layout(source)

    def test_every_comment_boundary_and_seeded_whitespace_preserve_native_semantics(self):
        source = ('struct P{x:i32} fn bump(p:&mut P,v:i32)->i32{p.x=p.x+v;return p.x;} '
                  'fn f()->i32{let mut p=P{x:1};let mut x=bump(&mut p,2);'
                  'if(x>0){x=x+-1;}else{x=-(-p.x);}return x;}')
        tokens = [t.text for t in lex(source) if t.kind != 'eof']
        baseline = emit_c(analyze(source), freestanding=True)
        for index in range(len(tokens) + 1):
            variant = ' '.join(tokens[:index]) + ' // keep 😀\r\n' + ' '.join(tokens[index:])
            result = self.verify_layout(variant)
            self.assertEqual(baseline, emit_c(analyze(result.decode()), freestanding=True))
        rng = random.Random(211)
        canonical = format_source(' '.join(tokens)).encode()
        for _ in range(30):
            variant = ''.join(t + rng.choice([' ', '\n', '\t', '\r\n', '  ']) for t in tokens)
            self.assertEqual(canonical, self.verify_layout(variant))

    def test_check_mode_reports_needed_layout_without_writing(self):
        source = 'fn f()->i32{return 0;}'
        result = self.command(source, '--check', '--json')
        self.assertEqual((1, b''), (result.returncode, result.stderr))
        receipt = json.loads(result.stdout)
        self.assertEqual(('native-call-borrows-v1', 'E0601'),
                         (receipt['profile'], receipt['diagnostics'][0]['code']))
        self.assertNotIn('--write', receipt['diagnostics'][0]['message'])
        human = self.command(source, '--check')
        self.assertEqual((1, b''), (human.returncode, human.stdout))
        self.assertIn(b'E0601', human.stderr)
        success = self.command(format_source(source), '--check')
        self.assertEqual((0, b'Formatting check passed\n', b''),
                         (success.returncode, success.stdout, success.stderr))

    def test_invalid_syntax_utf8_comment_limits_and_output_expansion(self):
        cases = [('fn f()->i32{return 0}', 'E0002'), (b'\xff', 'E0901'),
                 ('fn f()->i32{return @;}', 'E0001'), (' '*262145, 'E0005'),
                 ('//\n'*16385, 'E0005'),
                 ('fn f()->i32{return '+'('*2000+'0'+')'*2000+';}', 'E0005'),
                 ('fn f()->i32{'+'if(true){'*40+'1;'*1900+'}'*40+'return 0;}', 'E0602'),
                 ('//'+'x'*262142, 'E0602')]
        for source, code in cases:
            with self.subTest(code=code):
                result = self.command(source, '--check', '--json')
                self.assertEqual((1, b''), (result.returncode, result.stderr))
                self.assertEqual(code, json.loads(result.stdout)['diagnostics'][0]['code'])
        self.assertEqual(262144, len(self.verify_layout('//'+'x'*262141)))
        self.verify_layout('//'+'😀'*65535)

    def test_usage_rejects_unsupported_or_duplicate_options_before_io(self):
        for flags in (['--json'], ['--check', '--check'], ['--check', '--json', '--json'],
                      ['--write'], ['--check', '--write'], ['--console'], ['--compact'],
                      ['--expect-source-hash', '0'*64]):
            result = subprocess.run([str(BINARY), 'fmt', 'does-not-exist.tal', *flags],
                                    capture_output=True, timeout=3)
            self.assertEqual((2, b''), (result.returncode, result.stdout))
            self.assertIn(b'Usage:', result.stderr)

    def test_nonregular_sources_fail_without_waiting(self):
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / 'pipe.tal'
            os.mkfifo(fifo)
            for path in (fifo, Path(temporary), Path(temporary)/'missing.tal'):
                result = subprocess.run([str(BINARY), 'fmt', str(path), '--check', '--json'],
                                        capture_output=True, timeout=3)
                self.assertEqual((1, b''), (result.returncode, result.stderr))
                self.assertEqual('E0901', json.loads(result.stdout)['diagnostics'][0]['code'])


if __name__ == '__main__':
    if not BINARY.is_file():
        raise SystemExit(f'Build the native compiler first: {BINARY}')
    unittest.main(verbosity=2)
