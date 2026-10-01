import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from talven.frontend import CompileError, MAX_TOKENS, analyze, lex
from talven.lsp import Server, read_message
from talven.semantic_tokens import (DECLARATION, DEFAULT_LIBRARY, MODIFICATION,
                                    TOKEN_MODIFIERS, TOKEN_TYPES, semantic_tokens)


def decode(source, result):
    line = character = 0
    rows = []
    lines = source.split('\n')
    for index in range(0, len(result['data']), 5):
        delta_line, delta_character, length, role, mask = result['data'][index:index + 5]
        line += delta_line
        character = delta_character if delta_line else character + delta_character
        raw = lines[line].encode('utf-16-le')
        text = raw[character * 2:(character + length) * 2].decode('utf-16-le')
        rows.append((text, TOKEN_TYPES[role], mask, line, character, length))
    return rows


class SemanticTokenTests(unittest.TestCase):
    def test_checked_symbols_declarations_calls_fields_and_writes(self):
        source = ('struct P { value: i32 }\n'
                  'fn bump(p: &mut P) -> i32 { p.value = p.value + 1; return p.value; }\n'
                  'fn main() -> i32 { let mut p = P { value: 1 }; let mut x = bump(&mut p); '
                  'x = x + 1; return x; }')
        rows = decode(source, semantic_tokens(source, analyze(source)))
        select = lambda name, role: [row[2] for row in rows if row[:2] == (name, role)]
        self.assertEqual([DECLARATION, 0, 0], select('P', 'type'))
        self.assertEqual([DECLARATION, MODIFICATION, 0, 0, 0], select('value', 'property'))
        self.assertEqual([DECLARATION, 0], select('bump', 'function'))
        self.assertEqual([DECLARATION, 0, 0, 0], select('p', 'parameter'))
        self.assertEqual([DECLARATION, 0], select('p', 'variable'))
        self.assertEqual([DECLARATION, MODIFICATION, 0, 0], select('x', 'variable'))
        self.assertTrue(all(row[5] > 0 for row in rows))

    def test_builtin_default_library_roles_can_be_overridden_by_local_binding(self):
        source = 'fn f(i32: i32, print: i32) -> i32 { return i32 + print; } fn main() -> i32 { return print("ok"); }'
        rows = decode(source, semantic_tokens(source, analyze(source)))
        i32 = [(row[1], row[2]) for row in rows if row[0] == 'i32']
        self.assertEqual(('parameter', DECLARATION), i32[0])
        self.assertIn(('type', DEFAULT_LIBRARY), i32)
        self.assertIn(('parameter', 0), i32)
        calls = [(row[1], row[2]) for row in rows if row[0] == 'print']
        self.assertEqual([('parameter', DECLARATION), ('parameter', 0), ('function', DEFAULT_LIBRARY)], calls)

    def test_utf16_crlf_relative_positions_and_nonoverlap(self):
        source = '// 😀\r\nfn main() -> i32 { print("😀\\n"); return 12; }\r\n'
        rows = decode(source, semantic_tokens(source, analyze(source)))
        self.assertEqual(('// 😀', 'comment', 0, 0, 0, 5), rows[0])
        text = next(row for row in rows if row[1] == 'string')
        self.assertEqual('"😀\\n"', text[0])
        self.assertEqual(6, text[5])
        returned = next(row for row in rows if row[0] == 'return')
        expected = len(source.split('\n')[1].split('return')[0].encode('utf-16-le')) // 2
        self.assertEqual(expected, returned[4])
        for previous, current in zip(rows, rows[1:]):
            self.assertTrue(current[3] > previous[3] or current[4] >= previous[4] + previous[5])

    def test_invalid_revision_drops_semantics_but_preserves_current_lexical_colors(self):
        old = 'fn obsolete() -> i32 { let x = 1; return x; }'
        current = '// current\nfn replacement() -> i32 { let y = false; return missing; }'
        rows = decode(current, semantic_tokens(current, analyze(old)))
        self.assertTrue(any(row[1] == 'comment' for row in rows))
        self.assertTrue(any(row[1] == 'keyword' for row in rows))
        self.assertFalse(any(row[1] in ('variable', 'parameter', 'property', 'function') for row in rows))
        self.assertFalse(any(row[2] & (DECLARATION | MODIFICATION) for row in rows))

    def test_lexical_failures_and_source_limits_return_empty_current_result(self):
        for source in ('fn main() -> i32 { return @; }', '"unterminated',
                       '// \u202e', ' ' * (256 * 1024 + 1)):
            with self.subTest(source_length=len(source)):
                self.assertEqual({'data': []}, semantic_tokens(source))

    def test_result_covers_shared_lexical_spans_and_stays_bounded(self):
        for path in sorted(Path('examples').glob('*.tal')) + sorted(Path('tests/fixtures').glob('*.tal')):
            source = path.read_text()
            try:
                analysis = analyze(source)
            except CompileError:
                analysis = None
            with self.subTest(path=path):
                result = semantic_tokens(source, analysis)
                rows = decode(source, result)
                self.assertTrue(all(row[0] for row in rows))
                self.assertLessEqual(len(result['data']), MAX_TOKENS * 5)
                lexical = [t.text for t in lex(source, include_comments=True)]
                self.assertTrue(all(row[0] in lexical for row in rows))
        source = '// note\n' * MAX_TOKENS
        result = semantic_tokens(source)
        self.assertLessEqual(len(result['data']), MAX_TOKENS * 5)
        self.assertLessEqual(len(json.dumps(result, separators=(',', ':')).encode()), 512 * 1024)

    def test_lsp_full_capability_version_recovery_close_and_no_execution(self):
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize'})
        capability = read_message(io.BytesIO(output.getvalue()))['result']['capabilities']['semanticTokensProvider']
        self.assertEqual({'tokenTypes': TOKEN_TYPES, 'tokenModifiers': TOKEN_MODIFIERS}, capability['legend'])
        self.assertTrue(capability['full'])
        self.assertFalse(capability['range'])
        uri = 'file:///never/fetched.tal'
        valid = 'fn main() -> i32 { let mut x = 0; x = 1; return x; }'
        invalid = 'fn changed() -> i32 { return false; }'
        with patch('subprocess.run', side_effect=AssertionError('tokens must not execute')), \
             patch('pathlib.Path.open', side_effect=AssertionError('tokens must not read URIs')):
            server.update(uri, 1, valid)
            server.update(uri, 2, invalid)
            server.update(uri, 1, valid)
            server.handle({'id': 2, 'method': 'textDocument/semanticTokens/full', 'params': {'textDocument': {'uri': uri}}})
            server.update(uri, 3, valid)
            server.handle({'id': 3, 'method': 'textDocument/semanticTokens/full', 'params': {'textDocument': {'uri': uri}}})
            server.handle({'method': 'textDocument/didClose', 'params': {'textDocument': {'uri': uri}}})
            server.handle({'id': 4, 'method': 'textDocument/semanticTokens/full', 'params': {'textDocument': {'uri': uri}}})
            server.handle({'id': 5, 'method': 'textDocument/semanticTokens/full/delta', 'params': {'textDocument': {'uri': uri}}})
        messages = {}
        stream = io.BytesIO(output.getvalue())
        while (message := read_message(stream)) is not None:
            if 'id' in message:
                messages[message['id']] = message
        self.assertFalse(any(row[1] == 'function' for row in decode(invalid, messages[2]['result'])))
        self.assertTrue(any(row[2] & MODIFICATION for row in decode(valid, messages[3]['result'])))
        self.assertEqual(-32602, messages[4]['error']['code'])
        self.assertEqual(-32601, messages[5]['error']['code'])
