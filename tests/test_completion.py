import io
import json
import unittest
from unittest.mock import patch

from talven.completion import MAX_COMPLETION_BYTES, MAX_COMPLETIONS, completion_items
from talven.frontend import CompileError, Span, analyze, source_range
from talven.lsp import Server, offset_at, read_message


def complete(source, marker, *, checked=True):
    offset = source.index(marker) + len(marker)
    try:
        analysis = analyze(source) if checked else None
    except CompileError:
        analysis = None
    return completion_items(source, offset, analysis, 7)


def labels(result):
    return [item['label'] for item in result['items']]


class CompletionTests(unittest.TestCase):
    def test_current_globals_keywords_builtins_and_plain_identifier_edit(self):
        source = 'fn adjust(x: i32) -> i32 { return x; } fn main() -> i32 { return ad; }'
        result = complete(source, 'return ad')
        self.assertEqual(['adjust'], labels(result))
        item = result['items'][0]
        self.assertIn('unchecked source', item['detail'])
        start, end = source.index('ad;'), source.index('ad;') + 2
        self.assertEqual({'range': source_range(source, Span(start, end)), 'newText': 'adjust'}, item['textEdit'])
        self.assertEqual(1, item['insertTextFormat'])
        self.assertEqual({'documentVersion': 7}, item['data'])
        self.assertNotIn('command', item)
        self.assertEqual(['return'], labels(complete('fn f() -> i32 { ret 0; }', 'ret')))
        self.assertEqual(['print'], labels(complete('fn f() -> i32 { return pri; }', 'return pri')))

    def test_scope_excludes_later_and_sibling_branch_locals(self):
        source = ('fn f(param: i32) -> i32 { let outer = 1; '
                  'if (true) { let inside = 2; return outer + inside + param; } '
                  'else { let sibling = 3; return sibling + outer; } }')
        offset = source.index('return outer')
        items = completion_items(source, offset, analyze(source))['items']
        local = {i['label'] for i in items if i['kind'] == 6}
        self.assertEqual({'param', 'outer', 'inside'}, local)
        offset = source.index('let inside')
        local = {i['label'] for i in completion_items(source, offset, analyze(source))['items'] if i['kind'] == 6}
        self.assertEqual({'param', 'outer'}, local)
        offset = source.index('return sibling')
        local = {i['label'] for i in completion_items(source, offset, analyze(source))['items'] if i['kind'] == 6}
        self.assertEqual({'param', 'outer', 'sibling'}, local)

    def test_branch_bindings_do_not_escape_or_appear_in_their_initializer(self):
        source = 'fn f() -> i32 { if (true) { let branch = 1; } let next = 2; return next; }'
        analysis = analyze(source)
        at_initializer = source.index('= 2') + 2
        local = {i['label'] for i in completion_items(source, at_initializer, analysis)['items'] if i['kind'] == 6}
        self.assertEqual(set(), local)
        at_return = source.index('return next')
        local = {i['label'] for i in completion_items(source, at_return, analysis)['items'] if i['kind'] == 6}
        self.assertEqual({'next'}, local)
        at_end = len(source)
        self.assertFalse(any(i['kind'] == 6 for i in completion_items(source, at_end, analysis)['items']))

    def test_current_record_fields_and_checked_borrow_details(self):
        source = 'struct P { value: i32, ready: bool } fn read(p: &P) -> i32 { return p.value; }'
        result = complete(source, 'return p.')
        self.assertEqual(['ready', 'value'], labels(result))
        self.assertTrue(all(item['kind'] == 5 for item in result['items']))
        self.assertTrue(all('unchecked' not in item['detail'] for item in result['items']))
        local = complete(source, 'return p')['items']
        item = next(i for i in local if i['kind'] == 6)
        self.assertEqual('p: &P (shared borrow; call-scoped)', item['detail'])

    def test_recovered_fields_and_names_work_while_typing(self):
        source = 'struct P { value: i32 } fn f() -> i32 { let p = P { value: 1 }; return p.va; }'
        result = complete(source, 'return p.va')
        self.assertEqual(['value'], labels(result))
        self.assertIn('unchecked source', result['items'][0]['detail'])
        self.assertEqual(['p'], [i['label'] for i in complete(source, 'return p')['items'] if i['kind'] == 6])
        missing_end = source.replace('return p.va; }', 'return p.va')
        self.assertEqual(['value'], labels(complete(missing_end, 'return p.va')))

    def test_field_completion_does_not_guess_unknown_or_chained_receivers(self):
        for source in ('struct P { value: i32 } fn f() -> i32 { return unknown.; }',
                       'struct P { value: i32 } fn f(p: P) -> i32 { return p.value.; }'):
            with self.subTest(source=source):
                self.assertEqual([], labels(complete(source, source.rsplit('.', 1)[0] + '.')))

    def test_comments_text_and_numeric_tokens_are_inert(self):
        for source, marker in (('// print\nfn main() -> i32 { return 0; }', '// pri'),
                               ('fn main() -> i32 { return print("print"); }', 'print("pri'),
                               ('fn main() -> i32 { return 123; }', 'return 12'),
                               ('fn main() -> i32 { return print("unfinished); }', '"unfi')):
            with self.subTest(source=source):
                self.assertEqual([], labels(complete(source, marker)))

    def test_utf16_text_edit_replaces_entire_word_at_middle_cursor(self):
        source = '// 😀\r\nfn adjust() -> i32 { return 0; }\r\nfn main() -> i32 { return adwrong; }'
        item = complete(source, 'return ad')['items'][0]
        start = source.index('adwrong')
        self.assertEqual(source_range(source, Span(start, start + 7)), item['textEdit']['range'])

    def test_applying_call_completion_repairs_current_source_with_same_line_utf16(self):
        source = ('fn adjust(value: i32) -> i32 { return value; } '
                  'fn main() -> i32 { print("😀"); return adwrong(4); }')
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize'})
        uri = 'file:///example.tal'
        server.update(uri, 3, source)
        point = source_range(source, Span(source.index('adwrong') + 2, source.index('adwrong') + 2))['start']
        server.handle({'id': 2, 'method': 'textDocument/completion', 'params': {
            'textDocument': {'uri': uri}, 'position': point}})
        stream = io.BytesIO(output.getvalue())
        last = None
        while (message := read_message(stream)) is not None:
            last = message
        item = last['result']['items'][0]
        self.assertEqual('adjust', item['label'])
        edit = item['textEdit']
        start = offset_at(source, edit['range']['start'])
        end = offset_at(source, edit['range']['end'])
        repaired = source[:start] + edit['newText'] + source[end:]
        self.assertEqual({'print', 'adjust'}, analyze(repaired).functions['main'].calls)
        self.assertEqual(source, server.documents[uri].source)

    def test_stale_analysis_never_supplies_old_names_or_types(self):
        old = 'fn obsolete() -> i32 { return 1; }'
        current = 'fn replacement() -> i32 { return missing; }'
        result = completion_items(current, 0, analyze(old))
        self.assertIn('replacement', labels(result))
        self.assertNotIn('obsolete', labels(result))
        self.assertIn('unchecked source', next(i for i in result['items'] if i['label'] == 'replacement')['detail'])

    def test_item_and_byte_limits_mark_incomplete_without_oversize_results(self):
        source = '\n'.join(f'fn helper_{i}() -> i32 {{ return 0; }}' for i in range(150))
        result = completion_items(source, len(source), analyze(source))
        self.assertEqual(MAX_COMPLETIONS, len(result['items']))
        self.assertTrue(result['isIncomplete'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()), MAX_COMPLETION_BYTES)
        huge = 'x' * 40000
        source = f'fn {huge}() -> i32 {{ return 0; }}'
        result = completion_items(source, len(source), analyze(source))
        self.assertNotIn(huge, labels(result))
        self.assertTrue(result['isIncomplete'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()), MAX_COMPLETION_BYTES)
        self.assertEqual([], labels(completion_items(' ' * (256 * 1024 + 1), 0)))

    def test_lsp_capability_version_updates_close_and_invalid_positions(self):
        output = io.BytesIO()
        server = Server(output)
        server.handle({'id': 1, 'method': 'initialize'})
        capabilities = read_message(io.BytesIO(output.getvalue()))['result']['capabilities']
        self.assertEqual({'resolveProvider': False, 'triggerCharacters': ['.']}, capabilities['completionProvider'])
        uri = 'file:///never/read.tal'
        with patch('subprocess.run', side_effect=AssertionError('completion must not execute')), \
             patch('pathlib.Path.open', side_effect=AssertionError('completion must not fetch URIs')):
            for version, source in ((1, 'fn old() -> i32 { return 0; }'),
                                    (2, 'fn current() -> i32 { return missing; }'),
                                    (1, 'fn old() -> i32 { return 0; }')):
                server.handle({'method': 'textDocument/didOpen', 'params': {'textDocument': {
                    'uri': uri, 'version': version, 'text': source}}})
            server.handle({'id': 2, 'method': 'textDocument/completion', 'params': {
                'textDocument': {'uri': uri}, 'position': {'line': 0, 'character': 0}}})
        stream = io.BytesIO(output.getvalue())
        messages = []
        while (message := read_message(stream)) is not None:
            messages.append(message)
        self.assertIn('current', labels(messages[-1]['result']))
        self.assertNotIn('old', labels(messages[-1]['result']))
        server.handle({'id': 3, 'method': 'textDocument/completion', 'params': {
            'textDocument': {'uri': uri}, 'position': {'line': 0, 'character': 9999}}})
        server.handle({'method': 'textDocument/didClose', 'params': {'textDocument': {'uri': uri}}})
        server.handle({'id': 4, 'method': 'textDocument/completion', 'params': {
            'textDocument': {'uri': uri}, 'position': {'line': 0, 'character': 0}}})
        stream = io.BytesIO(output.getvalue())
        errors = []
        while (message := read_message(stream)) is not None:
            if 'error' in message:
                errors.append(message['error']['code'])
        self.assertEqual([-32602, -32602], errors)
