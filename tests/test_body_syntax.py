from pathlib import Path
import unittest
from unittest.mock import patch

from talven.backend import emit_c
from talven.body_syntax import parse_bodies
from talven.context import context
from talven.frontend import CompileError, analyze, parse
from talven.incremental import IncrementalFrontend


SOURCE = ('struct P { x: i32 }\n'
          'fn add(p: &mut P, delta: i32) -> i32 { p.x = p.x + delta; return p.x; }\n'
          'fn spare(unused: i32) -> i32 { return 7; }\n'
          'fn main() -> i32 { let mut p = P { x: 1 }; return add(&mut p, 2) - 3; }\n')


class BodySyntaxTests(unittest.TestCase):
    def setUp(self):
        self.frontend = IncrementalFrontend(reuse_body_syntax=True)

    def equivalent(self, source):
        result = self.frontend.analyze(source)
        expected = analyze(source)
        self.assertEqual(expected, result)
        self.assertEqual(context(expected), context(result))
        try:
            executable = emit_c(expected, console=True)
        except CompileError as error:
            with self.assertRaises(CompileError) as caught:
                emit_c(result, console=True)
            self.assertEqual(error.diagnostic(source), caught.exception.diagnostic(source))
        else:
            self.assertEqual(executable, emit_c(result, console=True))
        self.assertEqual(emit_c(expected, console=True, library=True),
                         emit_c(result, console=True, library=True))
        return result

    def rejected(self, source):
        before = dict(self.frontend._syntax)
        with self.assertRaises(CompileError) as full:
            analyze(source)
        with self.assertRaises(CompileError) as cached:
            self.frontend.analyze(source)
        self.assertEqual(full.exception.diagnostic(source), cached.exception.diagnostic(source))
        self.assertEqual(before, self.frontend._syntax)

    def test_unchanged_shifted_reordered_and_crlf_bodies_have_current_complete_facts(self):
        original = self.equivalent(SOURCE)
        for source in (SOURCE, '// 😀 shifted\n' + SOURCE, SOURCE.replace('\n', '\r\n'),
                       '\n'.join(reversed(SOURCE.strip().splitlines())) + '\n', SOURCE):
            result = self.equivalent(source)
            self.assertIsNot(original.program.functions[0].body, result.program.functions[0].body)
            # CRLF inside a body's exact text is a parse miss, not normalization.
            self.assertEqual({'add', 'spare', 'main'}, set(self.frontend.parse_stats['reused']))
            self.assertEqual([], self.frontend.parse_stats['parsed'])

    def test_header_only_edits_keep_body_grammar_but_current_semantics_and_names(self):
        self.equivalent(SOURCE)
        changed = SOURCE.replace('unused: i32', 'ignored: bool')
        result = self.equivalent(changed)
        self.assertEqual([], self.frontend.parse_stats['parsed'])
        self.assertEqual(['spare'], self.frontend.stats['checked'])
        self.assertEqual('ignored', result.functions['spare'].params[0][0].text)
        self.rejected(SOURCE.replace('delta: i32', 'amount: i32'))
        self.equivalent(changed)
        self.assertEqual([], self.frontend.stats['checked'])

    def test_body_whitespace_comment_and_crlf_edits_are_exact_parse_misses(self):
        source = SOURCE.replace('{ return 7; }', '{\n// inside body\nreturn 7;\n}')
        self.equivalent(source)
        for changed in (source.replace('inside body', 'new comment'), source.replace('\n', '\r\n'),
                        source.replace('return 7;', 'return  7;'), source):
            self.equivalent(changed)
            self.assertEqual(['spare'], self.frontend.parse_stats['parsed'])
            self.assertEqual(['add', 'main'], self.frontend.parse_stats['reused'])

    def test_body_edits_record_contracts_new_removed_functions_and_repair(self):
        self.equivalent(SOURCE)
        changed = SOURCE.replace('return 7;', 'let mut total = 1; total = total + 6; return total;')
        self.equivalent(changed)
        self.assertEqual(['spare'], self.frontend.parse_stats['parsed'])
        self.assertEqual(['spare'], self.frontend.stats['checked'])
        schema = changed.replace('x: i32 }', 'x: i32, y: bool }').replace('x: 1 }', 'x: 1, y: false }')
        self.equivalent(schema)
        self.assertEqual(['main'], self.frontend.parse_stats['parsed'])
        self.assertEqual(['add', 'main'], self.frontend.stats['checked'])
        self.rejected(schema.replace('return total;', 'return false;'))
        self.equivalent(schema)
        self.assertEqual([], self.frontend.parse_stats['parsed'])
        self.equivalent(schema + 'fn extra() -> i32 { return 0; }\n')
        self.assertEqual(['extra'], self.frontend.parse_stats['parsed'])
        self.equivalent(schema)
        self.assertNotIn('extra', self.frontend._syntax)

    def test_restored_program_is_untyped_and_independent_of_returned_ast_mutation(self):
        result = self.equivalent(SOURCE)
        result.functions['add'].body[0].target.args.clear()
        result.functions['main'].body.clear()
        result.functions['spare'].params.clear()
        result.references.clear()
        source = '// 😀\n' + SOURCE
        stats = {'parsed': [], 'reused': []}
        program, _ = parse_bodies(source, self.frontend._syntax, stats)
        self.assertEqual(parse(source), program)
        self.assertEqual([], stats['parsed'])
        self.equivalent(source)

    def test_fresh_lexing_and_current_syntax_semantics_limits_never_promote_failure(self):
        self.equivalent(SOURCE)
        for source in (SOURCE + ';', SOURCE + '\r', SOURCE + '\u202e', SOURCE + '/* unsupported */',
                       SOURCE + 'fn broken() -> i32 { return "bad\\q"; }',
                       SOURCE + 'fn broken() -> i32 { return ',
                       SOURCE + 'fn main() -> i32 { return 0; }',
                       ' ' * (256 * 1024) + SOURCE,
                       SOURCE + 'fn deep() -> i32 { return ' + '(' * 257 + '0' + ')' * 257 + '; }',
                       SOURCE + 'fn deep() -> i32 { return ' + ' + '.join(['1'] * 130) + '; }',
                       SOURCE + 'fn tokens() -> i32 { ' + 'let a = 0; ' * 4000 + 'return 0; }'):
            with self.subTest(source=source[-100:]):
                self.rejected(source)
        self.equivalent(SOURCE)
        self.assertEqual([], self.frontend.parse_stats['parsed'])

    def test_all_valid_fixtures_text_branches_stores_borrows_and_source_moves(self):
        for path in sorted(Path('examples').glob('*.tal')) + sorted(Path('tests/fixtures').glob('*.tal')):
            source = path.read_text()
            try:
                analyze(source)
            except CompileError:
                continue
            with self.subTest(path=path):
                self.equivalent(source)
                self.equivalent('// shifted 😀\n' + source)
                self.assertEqual([], self.frontend.parse_stats['parsed'])
                self.equivalent(source)

    def test_call_type_selection_recursion_compiler_pin_and_boolean_guards(self):
        self.frontend = IncrementalFrontend(reuse_body_syntax=True, call_type_contracts=True)
        source = ('fn recur(x: i32) -> i32 { if (x == 0) { return 0; } return recur(x - 1); } '
                  'fn main() -> i32 { return recur(2); }\n')
        self.equivalent(source)
        self.equivalent(source.replace('x', 'remaining'))
        self.assertEqual(['recur'], self.frontend.parse_stats['parsed'])
        self.assertEqual(['main'], self.frontend.parse_stats['reused'])
        self.assertEqual(['main'], self.frontend.stats['reused'])
        with patch('talven.incremental.compiler_hash', return_value='changed'):
            with self.assertRaises(CompileError) as caught:
                self.frontend.analyze(source)
        self.assertEqual('E0501', caught.exception.code)
        for invalid in (1, None, 'yes'):
            with self.assertRaises(ValueError):
                IncrementalFrontend(reuse_body_syntax=invalid)
        self.frontend.reuse_body_syntax = 1
        with self.assertRaises(ValueError):
            self.frontend.analyze(source)
