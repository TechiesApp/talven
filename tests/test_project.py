"""Module privacy, nominal identity, current navigation and actual native results."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from talven.__main__ import main
from talven.backend import emit_c
from talven.context import encode
from talven.formatter import format_source, token_identity
from talven.frontend import CompileError, Span, analyze, lex, source_range
from talven.lsp import Server, read_message
from talven.project import (ProjectError, ProjectReader, analyze_project, load_project,
                            module_path, parse_module, project_context, project_query)

COUNTER = '''pub struct Counter { value: i32 }
fn helper(value: i32) -> i32 { return value + 2; }
pub fn add(c: &mut Counter, amount: i32) -> i32 {
    c.value = c.value + helper(amount);
    return c.value;
}
'''
SOURCES = {'counter.tal': COUNTER,
           'main.tal': '''// 😀 current source
import "counter.tal" { Counter as Account, add as increment };
import "offset.tal" { adjust };
fn main() -> i32 {
    let mut account = Account { value: 35 };
    let result = increment(&mut account, 3);
    if (result == 40 && account.value == 40 && adjust(result) == 42) { return 0; }
    return 1;
}
''',
           'offset.tal': '''fn helper(value: i32) -> i32 { return value + 2; }
pub fn adjust(value: i32) -> i32 { return helper(value); }
'''}


class ProjectTests(unittest.TestCase):
    def test_aliases_private_helpers_and_deterministic_snapshot(self):
        first = analyze_project('main.tal', SOURCES)
        second = analyze_project('main.tal', dict(reversed(list(SOURCES.items()))))
        self.assertEqual(first.identity(), second.identity())
        self.assertEqual(emit_c(first.analysis), emit_c(second.analysis))
        self.assertEqual(2, len([n for n in first.analysis.functions if n.endswith('_helper')]))
        context = project_context(first, 'main.tal::main', True)
        self.assertEqual(['counter.tal::add', 'offset.tal::adjust'], [f['name'] for f in context['dependencies']])
        self.assertIn('increment(&mut account, 3)', context['functions'][0]['untrusted_source_text'])
        self.assertNotIn('untrusted_source_text', context['dependencies'][0])
        self.assertEqual('borrow-exclusive', context['dependencies'][0]['parameters'][0]['passing'])
        self.assertEqual(['counter.tal::Counter'], [r['name'] for r in context['records']])
        public = project_context(first, 'counter.tal::add', True)['functions'][0]
        self.assertTrue(public['untrusted_source_text'].startswith('pub fn add'))

    def test_private_exports_and_private_signature_types_are_rejected(self):
        cases = [('import "counter.tal" { helper }; fn main()->i32{return helper(1);}', COUNTER, 'E1103'),
                 ('import "counter.tal" { missing }; fn main()->i32{return 0;}', COUNTER, 'E1103'),
                 ('import "counter.tal" { Counter as i32 }; fn main()->i32{return 0;}', COUNTER, 'E0102'),
                 ('import "counter.tal" { Counter, Counter }; fn main()->i32{return 0;}', COUNTER, 'E0102'),
                 ('import "counter.tal" { Counter }; struct Counter{x:i32}', COUNTER, 'E0102'),
                 ('fn main()->i32{return 0;}', 'struct Hidden{x:i32} pub fn reveal(h:Hidden)->i32{return h.x;}', None)]
        # Unreachable source is not part of the checked dependency closure.
        for source, dependency, code in cases:
            with self.subTest(code=code):
                if code:
                    with self.assertRaises(ProjectError) as caught:
                        analyze_project('main.tal', {'main.tal': source, 'counter.tal': dependency})
                    self.assertEqual(code, caught.exception.code)
                else:
                    self.assertEqual(['main.tal'], list(analyze_project('main.tal', {'main.tal': source, 'counter.tal': dependency}).modules))
        with self.assertRaises(ProjectError) as caught:
            analyze_project('hidden.tal', {'hidden.tal': 'struct Hidden{x:i32} pub fn reveal(h:Hidden)->i32{return h.x;}'})
        self.assertEqual('E1103', caught.exception.code)

    def test_record_identity_moves_reborrows_and_argument_loan_order_cross_modules(self):
        other = 'pub struct Counter{value:i32} pub fn read(c:&Counter)->i32{return c.value;}'
        for body, code in [('let mut c=Account{value:1}; return increment(&mut c,c.value);', 'E0302'),
                           ('let c=Account{value:1}; return increment(&mut c,1);', 'E0303'),
                           ('let c=Account{value:1}; let moved=c; return c.value;', 'E0301'),
                           ('let c=Other{value:1}; return read(&c);', None),
                           ('let c=Account{value:1}; return read(&c);', 'E0201')]:
            source = 'import "counter.tal" {Counter as Account,add as increment}; import "other.tal" {Counter as Other,read}; fn main()->i32{' + body + '}'
            with self.subTest(code=code):
                if code:
                    with self.assertRaises(ProjectError) as caught:
                        analyze_project('main.tal', {'main.tal': source, 'counter.tal': COUNTER, 'other.tal': other})
                    self.assertEqual(code, caught.exception.code)
                else:
                    analyze_project('main.tal', {'main.tal': source, 'counter.tal': COUNTER, 'other.tal': other})
        with self.assertRaises(ProjectError) as caught:
            analyze_project('main.tal', {'main.tal': 'fn main()->i32{return __talven_module_0_helper(0);}'})
        self.assertEqual('E1101', caught.exception.code)

    def test_transitive_public_record_types_and_direct_imports(self):
        sources = {'types.tal': 'pub struct P{x:i32}',
                   'ops.tal': 'import "types.tal" {P}; pub fn add(p:&mut P)->i32{p.x=p.x+1;return p.x;}',
                   'main.tal': 'import "types.tal" {P}; import "ops.tal" {add}; fn main()->i32{let mut p=P{x:1};return add(&mut p)-2;}'}
        project = analyze_project('main.tal', sources)
        self.assertEqual('borrow-exclusive', project_context(project, 'ops.tal::add')['functions'][0]['parameters'][0]['passing'])
        sources['main.tal'] = sources['main.tal'].replace('import "types.tal" {P}; ', '')
        with self.assertRaises(ProjectError) as caught:
            analyze_project('main.tal', sources)
        self.assertEqual('E0101', caught.exception.code)

    def test_cycles_missing_modules_paths_and_resource_bounds(self):
        with self.assertRaises(ProjectError) as caught:
            analyze_project('a.tal', {'a.tal': 'import "b.tal" {g}; pub fn f()->i32{return 0;}',
                                      'b.tal': 'import "a.tal" {f}; pub fn g()->i32{return 0;}'})
        self.assertEqual('E1102', caught.exception.code)
        with self.assertRaises(ProjectError):
            analyze_project('a.tal', {'a.tal': 'import "b.tal" {g};'})
        for path in ('../a.tal', '/a.tal', 'a//b.tal', 'a/./b.tal', 'a\\b.tal', 'a.py', 'é.tal', 'a'*129+'.tal'):
            with self.subTest(path=path), self.assertRaises(CompileError):
                module_path(path)
        with self.assertRaises(CompileError) as caught:
            analyze_project('main.tal', {f'f{i}.tal': '' for i in range(33)})
        self.assertEqual('E1104', caught.exception.code)
        sources = {f'f{i}.tal': f'import "f{i+1}.tal" {{f}}; pub fn f()->i32{{return 0;}}' for i in range(16)}
        sources['f16.tal'] = 'pub fn f()->i32{return 0;}'
        with self.assertRaises(ProjectError) as caught:
            analyze_project('f0.tal', sources)
        self.assertEqual('E1104', caught.exception.code)
        with self.assertRaises(CompileError):
            analyze_project('main.tal', {'main.tal': ' ' * (256*1024+1)})
        with self.assertRaises(CompileError):
            parse_module('import "x.tal" {};')
        with self.assertRaises(CompileError):
            parse_module('fn f()->i32{return 0;} import "x.tal" {g};')

    def test_root_relative_nested_imports_empty_modules_and_owned_entry(self):
        sources = {'main.tal': 'import "nested/ops.tal" {run}; fn main()->i32{return run();}',
                   'nested/ops.tal': 'import "value.tal" {number}; pub fn run()->i32{return number();}',
                   'value.tal': 'pub fn number()->i32{return 0;}'}
        project = analyze_project('main.tal', sources)
        self.assertEqual(['main.tal', 'nested/ops.tal', 'value.tal'], list(project.modules))
        self.assertEqual([], project_context(analyze_project('empty.tal', {'empty.tal': ''}))['functions'])
        imported_entry = analyze_project('main.tal', {'main.tal': 'import "lib.tal" {main};',
                                                     'lib.tal': 'pub fn main()->i32{return 0;}'})
        with self.assertRaises(CompileError) as caught:
            emit_c(imported_entry.analysis)
        self.assertEqual('E0401', caught.exception.code)

    def test_original_utf16_diagnostics_and_cross_file_navigation(self):
        project = analyze_project('main.tal', SOURCES)
        source = SOURCES['main.tal']
        start = source.index('increment(&mut')
        position = source_range(source, Span(start, start))['start']
        result = project_query(project, 'main.tal', position)['result']
        expected = COUNTER.index('add(')
        self.assertEqual({'file': 'counter.tal', 'range': source_range(COUNTER, Span(expected, expected+3))}, result)
        hover = project_query(project, 'main.tal', position, 'hover')['result']
        self.assertIn('counter.tal::add', hover['description'])
        refs = project_query(project, 'main.tal', position, 'references')['result']
        self.assertEqual({'counter.tal', 'main.tal'}, {r['file'] for r in refs})
        shifted = dict(SOURCES, **{'counter.tal': '// 😀 shifted\n' + COUNTER})
        fresh = analyze_project('main.tal', shifted)
        self.assertNotEqual(project.identity()['graph_hash'], fresh.identity()['graph_hash'])
        self.assertEqual(result['range']['start']['line'] + 1,
                         project_query(fresh, 'main.tal', position)['result']['range']['start']['line'])
        with self.assertRaises(CompileError) as caught:
            project_context(fresh, expected_graph_hash=project.identity()['graph_hash'])
        self.assertEqual('E0501', caught.exception.code)
        broken = dict(SOURCES, **{'counter.tal': COUNTER.replace('return c.value;', 'return false;')})
        with self.assertRaises(ProjectError) as caught:
            analyze_project('main.tal', broken)
        self.assertEqual('counter.tal', caught.exception.diagnostic()['file'])
        expected = broken['counter.tal'].index('false')
        self.assertEqual(source_range(broken['counter.tal'], Span(expected, expected+5)), caught.exception.diagnostic()['range'])

    def test_exact_context_and_query_budgets(self):
        project = analyze_project('main.tal', SOURCES)
        context = project_context(project, max_bytes=1048576)
        size = len(encode(context).encode())
        self.assertEqual(context, project_context(project, max_bytes=size))
        for budget in (size-1, 0, True, 1048577):
            with self.assertRaises(CompileError):
                project_context(project, max_bytes=budget)
        query = project_query(project, 'main.tal', {'line': 0, 'character': 0})
        size = len(encode(query).encode())
        self.assertEqual(query, project_query(project, 'main.tal', {'line': 0, 'character': 0}, max_bytes=size))
        with self.assertRaises(CompileError):
            project_query(project, 'main.tal', {'line': 0, 'character': 0}, max_bytes=size-1)

    def test_module_formatting_is_syntax_only_and_base_profile_unchanged(self):
        for source in SOURCES.values():
            formatted = format_source(source, module=True)
            self.assertEqual(formatted, format_source(formatted, module=True))
            self.assertEqual(token_identity(lex(source, include_comments=True)), token_identity(lex(formatted, include_comments=True)))
        with self.assertRaises(CompileError):
            analyze(SOURCES['main.tal'])
        analyze('fn import()->i32{return 0;} fn pub()->i32{return import();}')
        format_source('pub fn broken()->i32{return false;}', module=True)

    def test_lsp_explicit_bundle_is_current_and_never_fetches_files(self):
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize'})
        start = SOURCES['main.tal'].index('increment(&mut')
        params = {'entry': 'main.tal', 'sources': dict(SOURCES), 'file': 'main.tal',
                  'position': source_range(SOURCES['main.tal'], Span(start, start))['start']}
        with patch('os.open', side_effect=AssertionError('LSP must not open files')), patch('subprocess.run', side_effect=AssertionError('LSP must not execute tools')):
            server.handle({'id': 2, 'method': 'talven/projectQuery', 'params': params})
            params['sources']['counter.tal'] = COUNTER.replace('return c.value;', 'return false;')
            server.handle({'id': 3, 'method': 'talven/projectQuery', 'params': params})
        stream = io.BytesIO(output.getvalue())
        messages = []
        while (message := read_message(stream)) is not None:
            messages.append(message)
        self.assertEqual('counter.tal', messages[1]['result']['result']['file'])
        self.assertEqual(-32803, messages[2]['error']['code'])
        self.assertEqual('E0201', messages[2]['error']['data']['diagnostics'][0]['code'])

    def write_project(self, root):
        for file, source in SOURCES.items():
            (root / file).write_text(source)

    def test_loader_rejects_symlinks_directories_fifo_and_observed_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_project(root)
            project = load_project(root, 'main.tal')
            reader = ProjectReader(root)
            try:
                (root/'counter.tal').write_text(COUNTER + '// change\n')
                with self.assertRaises(ProjectError) as caught:
                    reader.verify(project)
                self.assertEqual('E0501', caught.exception.code)
            finally:
                reader.close()
            (root/'counter.tal').unlink()
            (root/'counter.tal').symlink_to(root/'offset.tal')
            with self.assertRaises(ProjectError):
                load_project(root, 'main.tal')
            (root/'counter.tal').unlink()
            (root/'counter.tal').mkdir()
            with self.assertRaises(ProjectError):
                load_project(root, 'main.tal')
            (root/'counter.tal').rmdir()
            os.mkfifo(root/'counter.tal')
            with self.assertRaises(ProjectError):
                load_project(root, 'main.tal')
            (root/'alias').symlink_to(root, target_is_directory=True)
            (root/'entry.tal').write_text('import "alias/offset.tal" {adjust};')
            with self.assertRaises(ProjectError):
                load_project(root, 'entry.tal')

    def test_cli_context_build_and_failure_preserve_inputs_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_project(root)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, main(['project', 'context', 'main.tal', '--root', str(root), '--symbol', 'main.tal::main']))
            receipt = json.loads(output.getvalue())
            self.assertEqual('talven.project-context.v1', receipt['schema'])
            executable = root/'program'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(['project', 'build', 'main.tal', '--root', str(root), '-o', str(executable)]))
            result = subprocess.run([str(executable)], capture_output=True, timeout=5)
            self.assertEqual((0,b'',b''), (result.returncode,result.stdout,result.stderr))
            original = executable.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(1, main(['project', 'emit-c', 'main.tal', '--root', str(root), '-o', str(root/'counter.tal')]))
            self.assertEqual(COUNTER, (root/'counter.tal').read_text())
            def change_during_build(command, **kwargs):
                Path(command[-1]).write_bytes(b'rejected new binary')
                (root/'counter.tal').write_text(COUNTER + '// edited during build\n')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch('talven.project_cli.subprocess.run', side_effect=change_during_build), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(1, main(['project', 'build', 'main.tal', '--root', str(root), '-o', str(executable)]))
            self.assertEqual(original, executable.read_bytes())


if __name__ == '__main__':
    unittest.main()
