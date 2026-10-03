import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from talven.backend import emit_c, emit_c_units, emit_preprocess_units
from talven.context import encode, source_hash
from talven.formatter import format_source
from talven.frontend import CompileError, analyze
from talven.lsp import Server, read_message
from talven.outcomes import analyze_outcomes
from talven.resources import analyze_resources, resource_context

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = (ROOT / 'tests/fixtures/resources/workload.tal').read_text()
INVALID = [
    ('pending', 'fn f()->i32{region r(1){let a=reserve(r,1,1);}return 0;}', 'E0321'),
    ('payload', 'fn f()->i32{region r(1){match(reserve(r,1,1)){Allocation::Granted(b){} Allocation::InvalidRequest{} Allocation::Exhausted{}}}return 0;}', 'E0321'),
    ('moved-param', 'fn f(b:Block)->i32{let moved=b;return 0;}', 'E0321'),
    ('rewrap-leak', 'fn f(b:Block)->i32{let a=Allocation::Granted(b);return 0;}', 'E0321'),
    ('early-return', 'fn f()->i32{region r(1){let a=reserve(r,1,1);return 0;}}', 'E0321'),
    ('independent-origins', 'fn f(a:Block,b:Block)->i32{release(a);return 0;}', 'E0321'),
    ('double-release', 'fn f(b:Block)->i32{release(b);release(b);return 0;}', 'E0301'),
    ('read-released', 'fn f(b:Block)->i32{release(b);let x=read_byte(&b,0);return 0;}', 'E0301'),
    ('borrow-release', 'fn f(b:&Block)->i32{return release(b);}', 'E0304'),
    ('nested-loan-move', 'fn f(b:Block)->i32{let x=read_byte(&b,release(b));return 0;}', 'E0302'),
    ('immutable-loan', 'fn f(b:Block)->i32{let x=write_byte(&mut b,0,1);return release(b);}', 'E0303'),
    ('persistent-loan', 'fn f(b:Block)->i32{let x=&b;return release(b);}', 'E0304'),
    ('optional-release', 'fn free(b:Block)->bool{release(b);return true;}fn f(b:Block,c:bool)->i32{let x=c||free(b);return 0;}', 'E0321'),
    ('inconsistent-release', 'fn f(b:Block,c:bool)->i32{if(c){release(b);}return 0;}', 'E0321'),
    ('record-forgery', 'fn f()->i32{let b=Block{};return 0;}', 'E0320'),
    ('call-forgery', 'fn f()->i32{let b=Block();return 0;}', 'E0320'),
    ('opaque-field', 'fn f(b:Block)->i32{return b.length;}', 'E0320'),
    ('failure-construction', 'fn f()->i32{let a=Allocation::Exhausted;return 0;}', 'E0320'),
    ('block-result', 'fn f(b:Block)->Block{return b;}', 'E0320'),
    ('allocation-result', 'fn f()->Allocation{return Allocation::Exhausted;}', 'E0320'),
    ('allocation-parameter', 'fn f(a:&Allocation)->i32{return 0;}', 'E0320'),
    ('record-storage', 'struct P{x:Block}', 'E0320'),
    ('outcome-storage', 'outcome P{Value(Allocation)}', 'E0320'),
    ('capacity', 'fn f()->i32{region r(4097){}return 0;}', 'E0320'),
    ('region-alias', 'fn f()->i32{region r(1){let copy=r;}return 0;}', 'E0320'),
    ('reserve-busy', 'fn f()->i32{region r(1){let a=reserve(r,1,1);let b=reserve(r,1,1);}return 0;}', 'E0321'),
    ('reserve-wrong-shape', 'fn f()->i32{let a=reserve(1,1,1);return 0;}', 'E0320'),
    ('ignored-read', 'fn f(b:Block)->i32{read_byte(&b,0);return release(b);}', 'E0311'),
    ('declaration-order', 'struct Empty{} struct P{x:Block}', 'E0204'),
    ('ninth-region', 'fn f()->i32{' + ''.join(f'region r{i}(1){{}}' for i in range(9)) + 'return 0;}', 'E0320'),
]
VALID = [
    'fn f(b:Block)->i32{release(b);return 0;}',
    'fn f(b:Block,c:bool)->i32{if(c){release(b);return 1;}else{release(b);}return 0;}',
    'fn read(b:&Block)->ByteRead{return read_byte(&b,0);}fn f(b:Block)->i32{let a=read(&b);match(a){ByteRead::Value(v){release(b);return v;}ByteRead::OutOfBounds{return release(b);}}}',
    'fn write(b:&mut Block)->ByteWrite{return write_byte(&mut b,0,1);}fn f(b:Block)->i32{let mut w=b;let a=write(&mut w);match(a){ByteWrite::Written{}ByteWrite::OutOfBounds{}ByteWrite::InvalidByte{}}return release(w);}',
    'fn f()->i32{region a(1){region b(32){match(reserve(a,1,1)){Allocation::Granted(x){match(reserve(b,1,1)){Allocation::Granted(y){release(y);}Allocation::InvalidRequest{}Allocation::Exhausted{}}release(x);}Allocation::InvalidRequest{}Allocation::Exhausted{}}}}return 0;}',
    'struct P{x:i32}outcome R{Value(P),Empty}fn f()->R{return R::Empty;}',
]


def source_gate(native=None):
    spec = importlib.util.spec_from_file_location('resource_source_gate', ROOT / 'scripts/check-resource-sanitizers.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify(native)


class ResourceIntegrationTests(unittest.TestCase):
    def test_static_escape_loan_join_and_linear_obligation_rejections(self):
        for label, source, code in INVALID:
            with self.subTest(label=label), self.assertRaises(CompileError) as caught:
                analyze_resources('// 😀 inert prefix\n' + source)
            self.assertEqual(code, caught.exception.code)

    def test_valid_nested_regions_returns_borrowed_results_and_delegation(self):
        for source in [*VALID, WORKLOAD]:
            analyze_resources(source)

    def test_profiles_do_not_silently_inherit_opaque_builtin_names(self):
        source = 'struct Block{x:i32}struct Allocation{x:i32}fn reserve(b:Block)->i32{return b.x;}fn main()->i32{return reserve(Block{x:7});}'
        for analyze_selected in (analyze, analyze_outcomes):
            output = emit_c(analyze_selected(source))
            self.assertIn('struct tv_s_Block', output)
            self.assertNotIn('tv_region', output)
        with self.assertRaises(CompileError):
            analyze(WORKLOAD)
        with self.assertRaises(CompileError):
            analyze_outcomes(WORKLOAD)

    def test_context_exact_budget_runtime_contract_and_lsp_share_analysis(self):
        analysis = analyze_resources(WORKLOAD)
        context = resource_context(analysis)
        budget = len(encode(context).encode())
        self.assertEqual(context, resource_context(analysis, budget, source_hash(WORKLOAD)))
        with self.assertRaises(CompileError):
            resource_context(analysis, budget - 1)
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize', 'params': {}})
        server.handle({'id': 2, 'method': 'talven/resourceContext', 'params': {'source': WORKLOAD, 'maxBytes': budget, 'expectSourceHash': source_hash(WORKLOAD)}})
        output.seek(0)
        self.assertIn('talvenResourceContext', read_message(output)['result']['capabilities']['experimental'])
        self.assertEqual(context, read_message(output)['result'])
        for identity, source in enumerate((None, 1, [], {}), 3):
            cursor = output.tell()
            server.handle({'id': identity, 'method': 'talven/resourceContext', 'params': {'source': source}})
            output.seek(cursor)
            self.assertEqual(-32602, read_message(output)['error']['code'])
        bad = '// 😀\nfn f(b:Block)->i32{return 0;}'
        cursor = output.tell()
        server.handle({'id': 8, 'method': 'talven/resourceContext', 'params': {'source': bad}})
        output.seek(cursor)
        actual = read_message(output)['error']['data']['diagnostics'][0]
        try:
            analyze_resources(bad)
        except CompileError as error:
            self.assertEqual(error.diagnostic(bad), actual)
        cursor = output.tell()
        server.handle({'id': 9, 'method': 'talven/resourceContext', 'params': {'source': WORKLOAD, 'expectSourceHash': '0' * 64}})
        output.seek(cursor)
        self.assertEqual('E0501', read_message(output)['error']['data']['diagnostics'][0]['code'])
        cursor = output.tell()
        server.handle({'id': 10, 'method': 'talven/resourceContext', 'params': {'source': WORKLOAD}})
        output.seek(cursor)
        self.assertEqual(context, read_message(output)['result'])

    def test_cli_check_context_build_format_and_profile_output_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'workload.tal'
            path.write_text(format_source(WORKLOAD, resources=True))
            def command(operation, *options):
                return subprocess.run([sys.executable, '-m', 'talven', operation, str(path), '--resources', *options], capture_output=True, timeout=30)
            self.assertEqual(0, command('check', '--json').returncode)
            context = command('context')
            self.assertEqual('talven.resource-context.v1', json.loads(context.stdout)['schema'])
            self.assertEqual(0, command('fmt', '--check').returncode)
            for operation, options in [('check', ('--outcomes',)), ('fmt', ('--module',)), ('context', ('--compact',)), ('emit-c', ('--freestanding',)), ('emit-c', ('-o', str(path)))]:
                self.assertNotEqual(0, command(operation, *options).returncode)
            self.assertEqual(format_source(WORKLOAD, resources=True), path.read_text())
            executable = Path(temporary) / 'program'
            built = command('build', '-o', str(executable))
            self.assertEqual(0, built.returncode, built.stderr)
            self.assertEqual(0, subprocess.run([str(executable)], timeout=5).returncode)

    def test_unsupported_direct_units_do_not_accept_resource_analyses(self):
        analysis = analyze_resources(WORKLOAD)
        for emit in (emit_c_units, emit_preprocess_units):
            with self.assertRaises(CompileError) as caught:
                emit(analysis)
            self.assertEqual('E0502', caught.exception.code)

    def test_original_source_independent_ledger_faults_and_production_dependencies(self):
        report = source_gate()
        self.assertTrue(report['ok'])
        self.assertEqual(12, report['positive_executions'])
        self.assertEqual('reference', report['producer'])


if __name__ == '__main__':
    unittest.main()
