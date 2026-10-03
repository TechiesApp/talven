from pathlib import Path
import unittest
from unittest.mock import patch

from talven.backend import emit_c
from talven.context import context
from talven.frontend import CompileError, analyze
from talven.incremental import IncrementalFrontend


SOURCE = '''struct P { x: i32 }
fn add(p: &mut P, delta: i32) -> i32 { p.x = p.x + delta; return p.x; }
fn spare() -> i32 { return 7; }
fn main() -> i32 { let mut p = P { x: 1 }; return add(&mut p, 2); }
'''


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.frontend = IncrementalFrontend()

    def equivalent(self, source):
        actual = self.frontend.analyze(source)
        expected = analyze(source)
        self.assertEqual(expected, actual)
        try:
            executable = emit_c(expected, console=True)
        except CompileError as error:
            with self.assertRaises(CompileError) as caught:
                emit_c(actual, console=True)
            self.assertEqual(error.diagnostic(source), caught.exception.diagnostic(source))
        else:
            self.assertEqual(executable, emit_c(actual, console=True))
        self.assertEqual(emit_c(expected, console=True, library=True),
                         emit_c(actual, console=True, library=True))
        self.assertEqual(context(expected), context(actual))
        return actual

    def test_unchanged_source_reuses_bodies_and_rebuilds_current_analysis(self):
        first = self.equivalent(SOURCE)
        self.assertEqual(['add', 'spare', 'main'], self.frontend.stats['checked'])
        second = self.equivalent(SOURCE)
        self.assertIsNot(first, second)
        self.assertEqual([], self.frontend.stats['checked'])
        self.assertEqual(['add', 'spare', 'main'], self.frontend.stats['reused'])

    def test_body_change_does_not_invalidate_callers_with_unchanged_contracts(self):
        self.equivalent(SOURCE)
        self.equivalent(SOURCE.replace('p.x + delta', 'p.x + delta + 1'))
        self.assertEqual(['add'], self.frontend.stats['checked'])
        self.assertEqual(['spare', 'main'], self.frontend.stats['reused'])

    def test_global_and_local_definitions_remap_after_declaration_moves(self):
        self.equivalent(SOURCE)
        self.equivalent('// 😀\n' + SOURCE.replace('fn spare()', '\n\nfn spare()'))
        self.assertEqual(['add', 'spare', 'main'], self.frontend.stats['reused'])
        self.equivalent('\n'.join(reversed(SOURCE.strip().splitlines())) + '\n')
        self.assertEqual([], self.frontend.stats['checked'])

    def test_record_schema_and_called_signature_invalidate_dependents(self):
        self.equivalent(SOURCE)
        changed = SOURCE.replace('x: i32 }', 'x: i32, y: bool }').replace('x: 1 }', 'x: 1, y: false }')
        self.equivalent(changed)
        self.assertEqual(['add', 'main'], self.frontend.stats['checked'])
        self.equivalent(changed.replace('delta: i32', 'amount: i32').replace('p.x + delta', 'p.x + amount'))
        self.assertEqual(['add', 'main'], self.frontend.stats['checked'])

    def test_invalid_revisions_return_current_errors_and_never_publish_cache(self):
        self.equivalent(SOURCE)
        for source in (SOURCE.replace('delta: i32', 'delta: bool'), SOURCE.replace('return 7;', 'return false;'),
                       SOURCE.replace('add(&mut p, 2)', 'add(&p, 2)'), SOURCE.replace('x: i32', 'x: bool'),
                       SOURCE.replace('return 7;', 'return 7'), SOURCE.replace('let mut p', 'let p')):
            with self.subTest(source=source):
                with self.assertRaises(CompileError) as full:
                    analyze(source)
                with self.assertRaises(CompileError) as incremental:
                    self.frontend.analyze(source)
                self.assertEqual(full.exception.diagnostic(source), incremental.exception.diagnostic(source))
                self.assertEqual({'add', 'spare', 'main'}, set(self.frontend.entries))
        self.equivalent(SOURCE)
        self.assertEqual([], self.frontend.stats['checked'])

    def test_removed_dependencies_and_invalid_declarations_are_rechecked(self):
        self.equivalent(SOURCE)
        for source in (SOURCE.replace(SOURCE.splitlines()[1] + '\n', ''),
                       SOURCE.replace('struct P { x: i32 }\n', ''),
                       SOURCE + 'fn spare() -> i32 { return 8; }\n',
                       SOURCE.replace('delta: i32', 'delta: i32, delta: i32')):
            with self.subTest(source=source):
                with self.assertRaises(CompileError) as full:
                    analyze(source)
                with self.assertRaises(CompileError) as incremental:
                    self.frontend.analyze(source)
                self.assertEqual(full.exception.diagnostic(source), incremental.exception.diagnostic(source))

    def test_input_and_depth_limits_apply_to_cached_revisions(self):
        self.equivalent(SOURCE)
        for source in (' ' * (256 * 1024 + 1),
                       'fn main() -> i32 { return ' + '-' * 200 + '0; }'):
            with self.subTest(length=len(source)):
                with self.assertRaises(CompileError) as full:
                    analyze(source)
                with self.assertRaises(CompileError) as incremental:
                    self.frontend.analyze(source)
                self.assertEqual(full.exception.diagnostic(source), incremental.exception.diagnostic(source))
        self.equivalent(SOURCE)
        self.assertEqual([], self.frontend.stats['checked'])

    def test_new_removed_and_unrelated_declarations(self):
        self.equivalent(SOURCE)
        self.equivalent(SOURCE + 'fn extra() -> i32 { return 0; }\n')
        self.assertEqual(['extra'], self.frontend.stats['checked'])
        self.equivalent(SOURCE.replace('fn spare() -> i32 { return 7; }\n', ''))
        self.assertEqual({'add', 'main'}, set(self.frontend.entries))
        self.assertEqual([], self.frontend.stats['checked'])

    def test_cache_is_independent_of_returned_mutable_objects(self):
        result = self.equivalent(SOURCE)
        result.functions['add'].body.clear()
        result.functions['main'].calls.clear()
        result.references[0].description = 'changed by caller'
        self.equivalent(SOURCE)

    def test_compiler_identity_change_requires_a_new_session(self):
        self.equivalent(SOURCE)
        with patch('talven.incremental.compiler_hash', return_value='changed'):
            with self.assertRaises(CompileError) as caught:
                self.frontend.analyze(SOURCE)
        self.assertEqual('E0501', caught.exception.code)

    def test_existing_valid_fixtures_and_trivia_revisions_match_full_frontend(self):
        for path in sorted(Path('examples').glob('*.tal')) + sorted(Path('tests/fixtures').glob('*.tal')):
            source = path.read_text()
            try:
                analyze(source)
            except CompileError:
                continue
            with self.subTest(path=path):
                self.equivalent(source)
                self.equivalent('// shifted 😀\n' + source)
                self.equivalent(source)

    def test_call_type_contracts_refresh_current_names_after_repeated_renames_and_moves(self):
        self.frontend = IncrementalFrontend(call_type_contracts=True)
        self.equivalent(SOURCE)
        for parameter in ('amount', 'increment', 'step'):
            source = SOURCE.replace('delta', parameter).replace('add(p:', 'add(owner:').replace('p.x', 'owner.x')
            source = '// shifted 😀\n' + source
            result = self.equivalent(source)
            self.assertEqual(['add'], self.frontend.stats['checked'])
            self.assertEqual(['spare', 'main'], self.frontend.stats['reused'])
            calls = [ref for ref in result.references if ref.definition == result.functions['add'].name.span]
            self.assertTrue(calls)
            self.assertTrue(all(ref.description == result.functions['add'].signature() for ref in calls))
        moved = '\n'.join(reversed(source.strip().splitlines())) + '\n'
        self.equivalent(moved)
        self.assertEqual([], self.frontend.stats['checked'])

    def test_call_type_contracts_invalidate_types_modes_results_arity_and_missing_callees(self):
        self.frontend = IncrementalFrontend(call_type_contracts=True)
        self.equivalent(SOURCE)
        for source in (SOURCE.replace('delta: i32', 'delta: bool'),
                       SOURCE.replace('add(p: &mut P', 'add(p: &P'),
                       SOURCE.replace('delta: i32) -> i32', 'delta: i32) -> bool'),
                       SOURCE.replace('delta: i32)', 'delta: i32, extra: bool)'),
                       SOURCE.replace(SOURCE.splitlines()[1] + '\n', ''),
                       SOURCE.replace('delta: i32', 'p: i32')):
            with self.subTest(source=source):
                with self.assertRaises(CompileError) as full:
                    analyze(source)
                with self.assertRaises(CompileError) as cached:
                    self.frontend.analyze(source)
                self.assertEqual(full.exception.diagnostic(source), cached.exception.diagnostic(source))
        self.equivalent(SOURCE)
        self.assertEqual([], self.frontend.stats['checked'])
        changed = SOURCE.replace('&mut P', '&P').replace('p.x = p.x + delta; ', '').replace('add(&mut p, 2)', 'add(&p, 2)')
        self.equivalent(changed)
        self.assertEqual(['add', 'main'], self.frontend.stats['checked'])

    def test_call_type_contracts_preserve_global_record_invalidation_and_result_independence(self):
        self.frontend = IncrementalFrontend(call_type_contracts=True)
        result = self.equivalent(SOURCE)
        result.functions['add'].params.clear()
        for ref in result.references:
            ref.description = 'caller mutation'
        changed = SOURCE.replace('delta', 'amount')
        self.equivalent(changed)
        self.assertEqual(['add'], self.frontend.stats['checked'])
        changed = changed.replace('x: i32 }', 'x: i32, y: bool }').replace('x: 1 }', 'x: 1, y: false }')
        self.equivalent(changed)
        self.assertEqual(['add', 'main'], self.frontend.stats['checked'])

    def test_call_type_contracts_recursion_and_boolean_option_guards(self):
        self.frontend = IncrementalFrontend(call_type_contracts=True)
        source = ('fn recurse(x: i32) -> i32 { if (x == 0) { return 0; } return recurse(x - 1); } '
                  'fn main() -> i32 { return recurse(3); }\n')
        self.equivalent(source)
        self.equivalent(source.replace('x', 'remaining'))
        self.assertEqual(['recurse'], self.frontend.stats['checked'])
        self.assertEqual(['main'], self.frontend.stats['reused'])
        for invalid in (1, None, 'yes'):
            with self.assertRaises(ValueError):
                IncrementalFrontend(call_type_contracts=invalid)
        self.frontend.call_type_contracts = 1
        with self.assertRaises(ValueError):
            self.frontend.analyze(source)

    def test_call_type_contracts_all_valid_fixtures_trivia_and_compiler_pin(self):
        self.frontend = IncrementalFrontend(call_type_contracts=True)
        self.test_existing_valid_fixtures_and_trivia_revisions_match_full_frontend()
        with patch('talven.incremental.compiler_hash', return_value='changed'):
            with self.assertRaises(CompileError) as caught:
                self.frontend.analyze(SOURCE)
        self.assertEqual('E0501', caught.exception.code)
