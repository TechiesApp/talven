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
        self.assertEqual(emit_c(expected, console=True), emit_c(actual, console=True))
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
