import io
import json
import unittest
from unittest.mock import patch

from talven.frontend import CompileError, Span, analyze, source_range
from talven.lsp import Server, read_message
from talven.signature_help import MAX_SIGNATURE_BYTES, signature_help

ADD = 'fn add(x: i32, y: i32) -> i32 { return x + y; } '


def help_at(marked, *, analysis=None):
    offset = marked.index('|')
    source = marked.replace('|', '', 1)
    if analysis is None:
        try:
            analysis = analyze(source)
        except CompileError:
            pass
    return signature_help(source, offset, analysis)


class SignatureHelpTests(unittest.TestCase):
    def test_checked_contract_parameter_selection_and_trailing_argument(self):
        for call, expected in [('add(|1, 2)', 0), ('add(1, |2)', 1), ('add(1, 2, |)', 1)]:
            result = help_at(ADD + f'fn main() -> i32 {{ return {call}; }}')
            self.assertEqual(0, result['activeSignature'])
            self.assertEqual(expected, result['activeParameter'])
            signature = result['signatures'][0]
            self.assertEqual('fn add(x: i32, y: i32) -> i32', signature['label'])
            self.assertEqual(['x: i32', 'y: i32'], [p['label'] for p in signature['parameters']])
            self.assertTrue(all(p['label'] in signature['label'] for p in signature['parameters']))
        checked = help_at(ADD + 'fn main() -> i32 { return add(1, |2); }')
        self.assertIn('Checked current', checked['signatures'][0]['documentation'])
        self.assertEqual('Copied value.', checked['signatures'][0]['parameters'][0]['documentation'])

    def test_nested_calls_grouping_and_record_commas_belong_to_their_frame(self):
        sources = [(ADD + 'fn main() -> i32 { return add(add(1, |2), 3); }', 'add', 1),
                   (ADD + 'fn main() -> i32 { return add(add(1, 2), |3); }', 'add', 1),
                   (ADD + 'fn main() -> i32 { return add((|1 + 2), 3); }', 'add', 0),
                   ('struct P { x: i32, y: bool } fn use(p: P, n: i32) -> i32 { return p.x + n; } '
                    'fn main() -> i32 { return use(P { x: 1, y: |true }, 2); }', 'use', 0),
                   ('struct P { x: i32, y: bool } fn use(p: P, n: i32) -> i32 { return p.x + n; } '
                    'fn main() -> i32 { return use(P { x: 1, y: true }, |2); }', 'use', 1)]
        for source, name, active in sources:
            with self.subTest(source=source):
                result = help_at(source)
                self.assertTrue(result['signatures'][0]['label'].startswith('fn ' + name + '('))
                self.assertEqual(active, result['activeParameter'])
        self.assertIsNone(help_at(ADD + 'fn main() -> i32 { return add(unknown(|1, 2), 3); }'))

    def test_borrow_move_and_static_text_contracts_come_from_checked_parameters(self):
        source = ('struct P { x: i32 } '
                  'fn read(p: &P, other: &mut P, owned: P, text: str) -> i32 { return p.x; } '
                  'fn main() -> i32 { let p = P { x: 1 }; let mut q = P { x: 2 }; '
                  'let r = P { x: 3 }; return read(&p, |&mut q, r, "ok"); }')
        result = help_at(source)
        self.assertEqual(1, result['activeParameter'])
        params = result['signatures'][0]['parameters']
        self.assertIn('Shared borrow; read permission; call-scoped; cannot escape.', params[0]['documentation'])
        self.assertIn('Exclusive borrow; write permission; call-scoped; cannot escape.', params[1]['documentation'])
        self.assertEqual('Moved record value.', params[2]['documentation'])
        self.assertEqual('Copied value.', params[3]['documentation'])

    def test_incomplete_current_source_and_stale_analysis_do_not_reuse_old_contracts(self):
        old = analyze(ADD + 'fn main() -> i32 { return add(1, 2); }')
        current = 'fn add(input: bool) -> bool { return input; } fn main() -> i32 { return add(|'
        result = help_at(current, analysis=old)
        self.assertEqual('fn add(input: bool) -> bool', result['signatures'][0]['label'])
        self.assertIn('Unchecked current source', result['signatures'][0]['documentation'])
        self.assertTrue(all('Unchecked' in p['documentation'] for p in result['signatures'][0]['parameters']))
        duplicate = ADD + ADD + 'fn main() -> i32 { return add(|'
        self.assertIsNone(help_at(duplicate))

    def test_builtin_and_zero_parameters_have_correct_contract_shapes(self):
        result = help_at('fn main() -> i32 { return print(|"ok"); }')
        self.assertEqual('fn print(text: str) -> i32', result['signatures'][0]['label'])
        self.assertIn('--console', result['signatures'][0]['documentation'])
        result = help_at('fn zero() -> i32 { return 0; } fn main() -> i32 { return zero(|); }')
        self.assertEqual([], result['signatures'][0]['parameters'])
        self.assertNotIn('activeParameter', result)

    def test_inert_text_closed_calls_declarations_and_malformed_source(self):
        for source in [ADD + '// add(1, |\nfn main() -> i32 { return 0; }',
                       ADD + 'fn main() -> i32 { print("add(1, |)"); return 0; }',
                       ADD + 'fn main() -> i32 { return add(1, 2)|; }',
                       'fn add(x: i32, |y: i32) -> i32 { return x + y; }',
                       ADD + 'fn main() -> i32 { return p.add(|1, 2); }',
                       ADD + 'fn main() -> i32 { return add(1, |@); }',
                       ADD + 'fn main() -> i32 { return add(1, |"unfinished); }',
                       ADD + 'fn main() -> i32 { return add(1, } |',
                       'fn main() -> i32 { return ' + '(' * 260 + '|0; }']:
            with self.subTest(source=source):
                self.assertIsNone(help_at(source))

    def test_reply_budget_and_invalid_offsets(self):
        parameters = ', '.join(f'parameter_{i}: i32' for i in range(600))
        source = f'fn huge({parameters}) -> i32 {{ return 0; }} fn main() -> i32 {{ return huge(|'
        self.assertIsNone(help_at(source))
        small = help_at(ADD + 'fn main() -> i32 { return add(|')
        self.assertLessEqual(len(json.dumps(small, ensure_ascii=False, separators=(',', ':')).encode()), MAX_SIGNATURE_BYTES)
        for offset in (-1, 99999, True, 0.5):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                signature_help(ADD, offset)

    def test_lsp_utf16_versions_lifecycle_and_no_external_actions(self):
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize'})
        caps = read_message(io.BytesIO(output.getvalue()))['result']['capabilities']
        self.assertEqual({'triggerCharacters': ['(', ',']}, caps['signatureHelpProvider'])
        uri = 'file:///never/read.tal'
        source = ADD + '\r\nfn main() -> i32 { print("😀"); return add(1, 2); }'
        offset = source.index('add(1, 2)') + len('add(1, ')
        point = source_range(source, Span(offset, offset))['start']
        with patch('subprocess.run', side_effect=AssertionError('no execution')), \
             patch('pathlib.Path.open', side_effect=AssertionError('no URI fetch')):
            server.handle({'method': 'textDocument/didOpen', 'params': {'textDocument': {
                'uri': uri, 'version': 2, 'text': source}}})
            server.handle({'method': 'textDocument/didChange', 'params': {'textDocument': {
                'uri': uri, 'version': 1}, 'contentChanges': [{'text': 'fn main() -> i32 { return 0; }'}]}})
            server.handle({'id': 2, 'method': 'textDocument/signatureHelp', 'params': {
                'textDocument': {'uri': uri}, 'position': point,
                'context': {'activeSignatureHelp': {'signatures': [{'label': 'stale'}]}}}})
        self.assertEqual(source, server.documents[uri].source)
        stream = io.BytesIO(output.getvalue())
        messages = []
        while (message := read_message(stream)) is not None:
            messages.append(message)
        self.assertEqual(1, messages[-1]['result']['activeParameter'])
        self.assertEqual('fn add(x: i32, y: i32) -> i32', messages[-1]['result']['signatures'][0]['label'])
        current = 'fn add(input: bool) -> bool { return input; } fn main() -> i32 { return add('
        server.handle({'method': 'textDocument/didChange', 'params': {'textDocument': {
            'uri': uri, 'version': 3}, 'contentChanges': [{'text': current}]}})
        point = source_range(current, Span(len(current), len(current)))['start']
        server.handle({'id': 5, 'method': 'textDocument/signatureHelp', 'params': {
            'textDocument': {'uri': uri}, 'position': point}})
        stream = io.BytesIO(output.getvalue())
        while (message := read_message(stream)) is not None:
            latest = message
        self.assertEqual('fn add(input: bool) -> bool', latest['result']['signatures'][0]['label'])
        self.assertIn('Unchecked current source', latest['result']['signatures'][0]['documentation'])
        for point in ({'line': 1, 'character': 99999}, {'line': True, 'character': 0}):
            server.handle({'id': 3, 'method': 'textDocument/signatureHelp', 'params': {
                'textDocument': {'uri': uri}, 'position': point}})
        server.handle({'method': 'textDocument/didClose', 'params': {'textDocument': {'uri': uri}}})
        server.handle({'id': 4, 'method': 'textDocument/signatureHelp', 'params': {
            'textDocument': {'uri': uri}, 'position': {'line': 0, 'character': 0}}})
        stream = io.BytesIO(output.getvalue())
        errors = []
        while (message := read_message(stream)) is not None:
            if 'error' in message:
                errors.append(message['error']['code'])
        self.assertEqual([-32602, -32602, -32602], errors)
