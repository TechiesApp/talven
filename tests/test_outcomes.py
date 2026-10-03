import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from talven.backend import emit_c
from talven.context import source_hash
from talven.formatter import format_source
from talven.frontend import CompileError, analyze
from talven.lsp import Server, read_message
from talven.outcomes import PROFILE, analyze_outcomes, outcome_context

DECL = 'struct P { x: i32 } outcome R { Ok(P), Bad(i32), Empty } '
SCALAR = 'outcome R { Ok(i32), Empty } '

INVALID = [
    ('empty declaration', 'outcome R {}', 'E0310'),
    ('first declaration error order', 'outcome R {} struct P {}', 'E0310'),
    ('duplicate variant', 'outcome R { A, A }', 'E0102'),
    ('nested outcome', 'outcome R { A(R) }', 'E0310'),
    ('borrow payload', 'struct P {x:i32} outcome R {A(&P)}', 'E0310'),
    ('text payload', 'outcome R {A(str)}', 'E0310'),
    ('unknown payload', 'outcome R {A(Missing)}', 'E0310'),
    ('unknown outcome', 'fn f()->i32 { Missing::A; return 0; }', 'E0310'),
    ('unknown variant', SCALAR + 'fn f()->R {return R::Missing;}', 'E0310'),
    ('missing constructor payload', SCALAR + 'fn f()->R {return R::Ok;}', 'E0310'),
    ('extra constructor payload', SCALAR + 'fn f()->R {return R::Empty(1);}', 'E0310'),
    ('wrong payload type', SCALAR + 'fn f()->R {return R::Ok(true);}', 'E0201'),
    ('nominal payload', DECL + 'struct Q{x:i32} fn f()->R{return R::Ok(Q{x:1});}', 'E0201'),
    ('discard expression', SCALAR + 'fn f()->i32 {R::Empty;return 0;}', 'E0311'),
    ('retained local', SCALAR + 'fn f()->i32 {let r=R::Empty;return 0;}', 'E0311'),
    ('ignored parameter', SCALAR + 'fn f(r:R)->i32{return 0;}', 'E0311'),
    ('inner scope', SCALAR + 'fn f(b:bool)->i32{if(b){let r=R::Empty;}return 0;}', 'E0311'),
    ('missing arm', SCALAR + 'fn f(r:R)->i32{match(r){R::Empty{return 0;}}}', 'E0310'),
    ('duplicate arm', SCALAR + 'fn f(r:R)->i32{match(r){R::Empty{return 0;}R::Empty{return 0;}}}', 'E0310'),
    ('wrong arm payload', SCALAR + 'fn f(r:R)->i32{match(r){R::Empty(x){return 0;}R::Ok(x){return x;}}}', 'E0310'),
    ('missing arm payload', SCALAR + 'fn f(r:R)->i32{match(r){R::Empty{return 0;}R::Ok{return 1;}}}', 'E0310'),
    ('scalar match', 'fn f(x:i32)->i32{match(x){}return 0;}', 'E0310'),
    ('borrow parameter', SCALAR + 'fn f(r:&R)->i32{return 0;}', 'E0305'),
    ('borrow argument', SCALAR + 'fn f(r:R)->R{return r;} fn g()->R{let r=R::Empty;return f(&r);}', 'E0305'),
    ('mutable outcome', SCALAR + 'fn f()->R{let mut r=R::Empty;return r;}', 'E0305'),
    ('outcome field extraction', SCALAR + 'fn f(r:R)->i32{return r.Ok;}', 'E0101'),
    ('record construction of outcome', SCALAR + 'fn f()->R{return R{};}', 'E0101'),
    ('outcome copy', SCALAR + 'fn f(r:R)->R{let a=r;return r;}', 'E0301'),
    ('record moved into constructor', DECL + 'fn f(p:P)->i32{let r=R::Ok(p);return p.x;}', 'E0301'),
    ('payload moved twice', DECL + 'fn take(p:P)->i32{return p.x;} fn f(r:R)->i32{match(r){R::Empty{return 0;}R::Bad(x){return x;}R::Ok(p){let x=take(p);return take(p);}}}', 'E0301'),
    ('scrutinee consumed', SCALAR + 'fn f(r:R)->R{match(r){R::Ok(x){}R::Empty{}}return r;}', 'E0301'),
    ('inconsistent continuing ownership', SCALAR + 'fn take(r:R)->R{return r;} fn f(r:R,b:bool)->R{if(b){let s=take(r);match(s){R::Ok(x){}R::Empty{}}}return r;}', 'E0311'),
    ('whole assignment', SCALAR + 'fn f(r:R)->R{r=R::Empty;return r;}', 'E0305'),
    ('short circuit may ignore outcome', SCALAR + 'fn take(r:R)->bool{match(r){R::Ok(x){return true;}R::Empty{return false;}}} fn f(r:R,b:bool)->i32{let x=b&&take(r);return 0;}', 'E0311'),
    ('nominal outcome', SCALAR + 'outcome S{Ok(i32),Empty} fn f()->R{return S::Empty;}', 'E0201'),
    ('wrong arm owner', SCALAR + 'outcome S{Ok(i32),Empty} fn f(r:R)->i32{match(r){S::Empty{return 0;}R::Ok(x){return x;}}}', 'E0201'),
]

VALID = [
    SCALAR + 'fn f(r:R)->R{return r;}',
    SCALAR + 'fn f(r:R,b:bool)->R{if(b){return r;}return r;}',
    SCALAR + 'fn f(r:R)->i32{let mut x=0;match(r){R::Ok(v){x=v;}R::Empty{x=3;}}return x;}',
    SCALAR + 'fn take(r:R)->i32{match(r){R::Ok(x){return x;}R::Empty{return 0;}}} fn f(r:R,b:bool)->i32{if(b){return take(r);}return take(r);}',
    'outcome Empty{A,B} fn f(r:Empty)->i32{match(r){Empty::B{return 2;}Empty::A{return 1;}}}',
    DECL + 'fn f(r:R)->R{match(r){R::Ok(p){return R::Ok(p);}R::Bad(x){return R::Bad(x);}R::Empty{return R::Empty;}}}',
    DECL + 'fn read(p:&P)->i32{return p.x;} fn f(r:R)->i32{match(r){R::Ok(p){return read(&p);}R::Bad(x){return x;}R::Empty{return 0;}}}',
]

DRIVER = '''#define main talven_example_main
#include "generated.c"
#undef main
int main(void) {
    int32_t inputs[] = {INT32_MIN, -17, -1, 0, 1, 2, 73, INT32_MAX};
    for (unsigned i=0; i<sizeof(inputs)/sizeof(inputs[0]); ++i) {
        int32_t x=inputs[i];
        int32_t expected=x==1 ? 7 : x;
        if (tv_f_evaluate(x)!=expected) return 1;
        struct tv_s_Decision result=tv_f_decide(x);
        if (x<0) { if(result.tv_tag!=1 || result.tv_payload.tv_m_Failed!=x) return 2; }
        else if(x==0) { if(result.tv_tag!=3) return 3; }
        else if(x==1) { if(result.tv_tag!=2 || !result.tv_payload.tv_m_Flag) return 4; }
        else { if(result.tv_tag!=0 || result.tv_payload.tv_m_Ready.tv_m_value!=x || result.tv_payload.tv_m_Ready.tv_m_marked) return 5; }
    }
    return talven_example_main();
}
'''


def compile_driver(generated, driver, directory, optimization):
    (directory / 'generated.c').write_text(generated)
    (directory / 'driver.c').write_text(driver)
    subprocess.run(['cc', '-std=c11', optimization, '-Wall', '-Wextra', '-Werror', '-pedantic-errors',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', str(directory / 'driver.c'),
                    '-o', str(directory / 'program')], check=True, capture_output=True, timeout=30)
    return subprocess.run([str(directory / 'program')], capture_output=True, timeout=5)


class OutcomeTests(unittest.TestCase):
    def test_semantic_rejections(self):
        for label, source, code in INVALID:
            with self.subTest(label=label):
                with self.assertRaises(CompileError) as caught:
                    analyze_outcomes(source)
                self.assertEqual(code, caught.exception.code)

    def test_moves_payload_transfer_and_continuing_joins(self):
        for source in VALID:
            with self.subTest(source=source):
                analyze_outcomes(source)

    def test_base_profile_stays_explicit(self):
        with self.assertRaises(CompileError):
            analyze(SCALAR)
        analyze('fn outcome(match:i32)->i32{return match;}')

    def test_formatting_preserves_comments_and_is_syntax_only(self):
        for source in [*VALID, 'outcome R{A,B} // outcome match 😀\nfn f(r:R)->i32{match(r){R::A{return 1;}R::B{return 2;}}}',
                       SCALAR + 'fn f()->R{return R::Ok(true);}']:
            formatted = format_source(source, outcomes=True)
            self.assertEqual(formatted, format_source(formatted, outcomes=True))
        with self.assertRaises(CompileError):
            format_source(SCALAR, module=True, outcomes=True)

    def test_bounds_include_match_arm_bodies(self):
        source = SCALAR + 'fn f(r:R)->i32{match(r){R::Empty{' + 'if(true){' * 129 + 'return 0;' + '}' * 129 + '}R::Ok(x){return x;}}}'
        with self.assertRaises(CompileError) as caught:
            analyze_outcomes(source)
        self.assertEqual('E0005', caught.exception.code)

    def test_context_and_lsp_share_checked_contract(self):
        source = Path('examples/outcomes/decision.tal').read_text()
        analysis = analyze_outcomes(source)
        context = outcome_context(analysis)
        self.assertEqual(PROFILE, context['language_profile'])
        self.assertEqual([0, 1, 2, 3], [v['tag'] for v in context['outcomes'][0]['variants']])
        self.assertEqual(['Ready', 'Failed', 'Flag', 'Empty'], [v['name'] for v in context['outcomes'][0]['variants']])
        for options in ({'max_bytes': 1}, {'expected_source_hash': '0' * 64}):
            with self.assertRaises(CompileError):
                outcome_context(analysis, **options)
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize', 'params': {}})
        server.handle({'id': 2, 'method': 'talven/outcomeContext', 'params': {'source': source, 'expectSourceHash': source_hash(source)}})
        output.seek(0)
        read_message(output)
        self.assertEqual(context, read_message(output)['result'])
        bad = '// 😀\n' + SCALAR + 'fn f()->i32{R::Empty;return 0;}'
        cursor = output.tell()
        server.handle({'id': 3, 'method': 'talven/outcomeContext', 'params': {'source': bad}})
        output.seek(cursor)
        failure = read_message(output)['error']
        self.assertEqual('Outcome context failed', failure['message'])
        try:
            analyze_outcomes(bad)
        except CompileError as error:
            self.assertEqual(error.diagnostic(bad), failure['data']['diagnostics'][0])
        for invalid in (None, 1, {}, []):
            cursor = output.tell()
            server.handle({'id': 4, 'method': 'talven/outcomeContext', 'params': {'source': invalid}})
            output.seek(cursor)
            self.assertEqual(-32602, read_message(output)['error']['code'])
        cursor = output.tell()
        server.handle({'id': 5, 'method': 'talven/outcomeContext', 'params': {'source': source}})
        output.seek(cursor)
        self.assertEqual(context, read_message(output)['result'])

    def test_cli_and_source_output_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'test.tal'
            path.write_text(Path('examples/outcomes/decision.tal').read_text())
            for command in ('check', 'context'):
                result = subprocess.run([sys.executable, '-m', 'talven', command, str(path), '--outcomes', *(['--json'] if command == 'check' else [])], capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIsInstance(json.loads(result.stdout), dict)
            before = path.read_bytes()
            result = subprocess.run([sys.executable, '-m', 'talven', 'emit-c', str(path), '--outcomes', '-o', str(path)], capture_output=True, timeout=10)
            self.assertEqual(1, result.returncode)
            self.assertEqual(before, path.read_bytes())
            result = subprocess.run([sys.executable, '-m', 'talven', 'emit-c', str(path), '--outcomes', '--freestanding'], capture_output=True, timeout=10)
            self.assertEqual(1, result.returncode)
            self.assertIn(b'E0502', result.stderr)

    def test_independent_variant_values_and_layout_with_sanitizers(self):
        generated = emit_c(analyze_outcomes(Path('examples/outcomes/decision.tal').read_text()))
        with tempfile.TemporaryDirectory() as temporary:
            for optimization in ('-O0', '-O2'):
                with self.subTest(optimization=optimization):
                    result = compile_driver(generated, DRIVER, Path(temporary), optimization)
                    self.assertEqual((0, b'', b''), (result.returncode, result.stdout, result.stderr))

    def test_invalid_foreign_tag_traps_before_payload_access(self):
        source = 'outcome R{A(i32),B} fn handle(r:R)->i32{match(r){R::A(x){return x;}R::B{return 0;}}} fn main()->i32{return 0;}'
        generated = emit_c(analyze_outcomes(source))
        driver = '#define main talven_example_main\n#include "generated.c"\n#undef main\nint main(void){struct tv_s_R r={.tv_tag=99};return tv_f_handle(r);}\n'
        with tempfile.TemporaryDirectory() as temporary:
            for optimization in ('-O0', '-O2'):
                result = compile_driver(generated, driver, Path(temporary), optimization)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn(b'runtime error:', result.stderr)
                self.assertNotIn(b'ERROR: AddressSanitizer', result.stderr)


if __name__ == '__main__':
    unittest.main()
