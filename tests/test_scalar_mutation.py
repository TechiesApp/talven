import json
from pathlib import Path
import unittest

from talven.backend import emit_c
from talven.context import context
from talven.formatter import format_source
from talven.frontend import CompileError, analyze, lex


class ScalarMutationTests(unittest.TestCase):
    def test_scalar_locals_keep_types_and_permissions_across_branches(self):
        analyze('''fn f(input: i32, choose: bool) -> i32 {
            let mut x: i32 = input;
            let mut flag = choose;
            if (flag) { x = x + 1; flag = false; }
            else { (x) = 8; flag = !flag; }
            let copy = x;
            x = copy + 2;
            if (flag) { return x; }
            return copy;
        }''')

    def test_invalid_destinations_and_types_are_rejected(self):
        cases = [
            ('let x = 1; x = 2;', 'E0303'),
            ('let mut x = 1; let y = x; y = 2;', 'E0303'),
            ('let mut x = 1; x = false;', 'E0201'),
            ('let mut x = true; x = 1;', 'E0201'),
            ('missing = 1;', 'E0101'),
            ('let mut s = "x";', 'E0305'),
            ('let s = "x"; s = "y";', 'E0305'),
            ('let mut x = 1; (x + 1) = 2;', 'E0305'),
            ('let mut x = 1; 1 = x;', 'E0305'),
            ('let mut x = 1; let x = 2;', 'E0102'),
            ('if (true) { let mut x = 1; } x = 2;', 'E0101'),
            ('let mut x = 1; x = x = 2;', 'E0002'),
        ]
        for body, code in cases:
            with self.subTest(body=body), self.assertRaises(CompileError) as caught:
                analyze(f'fn main() -> i32 {{ {body} return 0; }}')
            self.assertEqual(code, caught.exception.code)
        with self.assertRaises(CompileError) as caught:
            analyze('fn f(x: i32) -> i32 { x = 2; return x; }')
        self.assertEqual('E0303', caught.exception.code)

    def test_records_cannot_be_reassigned_or_revived(self):
        for body in ('p = P { x: 2 };', 'let q = p; p = q;'):
            with self.subTest(body=body), self.assertRaises(CompileError) as caught:
                analyze('struct P { x: i32 } fn main() -> i32 { '
                        'let mut p = P { x: 1 }; ' + body + ' return 0; }')
            self.assertEqual('E0301' if body.startswith('let q') else 'E0305', caught.exception.code)

    def test_formatter_preserves_assignment_tokens_and_lowering(self):
        source = 'fn main()->i32{let mut x=40;let mut b=true;if(b){x=x+2;b=false;}return x-42;}'
        formatted = format_source(source)
        self.assertEqual(formatted, format_source(formatted))
        self.assertEqual([(t.kind, t.text) for t in lex(source)],
                         [(t.kind, t.text) for t in lex(formatted)])
        self.assertEqual(emit_c(analyze(source)), emit_c(analyze(formatted)))

    def test_context_and_navigation_include_scalar_writes(self):
        source = 'fn main() -> i32 { let mut x = 1; x = x + 1; return x; }'
        analysis = analyze(source)
        uses = [r for r in analysis.references if r.description.startswith('x: i32')]
        self.assertEqual(4, len(uses))
        self.assertEqual(1, len({r.definition for r in uses}))
        self.assertTrue(all('mutable local' in r.description for r in uses))
        packet = json.loads(context(analysis, 'main'))
        self.assertIn('i32/bool locals', packet['rules']['mutation'])

    def test_example_checks_and_is_canonical(self):
        source = Path('examples/scalars.tal').read_text()
        analyze(source)
        self.assertEqual(source, format_source(source))
