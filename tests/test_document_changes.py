import io
import unittest
from unittest.mock import patch

from talven.document_changes import MAX_DOCUMENT_BYTES, apply_changes, edit_offset
from talven.frontend import analyze
from talven.lsp import Server, read_message, serve, write_message

URI = 'file:///never-opened/example.tal'
SOURCE = '// 😀\r\nfn main() -> i32 { return 1; }\r\n'


def point(line, character):
    return {'line': line, 'character': character}


def edit(start, end, text, **extra):
    return {'range': {'start': point(*start), 'end': point(*end)}, 'text': text, **extra}


class DocumentChangeTests(unittest.TestCase):
    def test_sequential_insert_replace_delete_and_full_reset(self):
        self.assertEqual('aXc', apply_changes('abc', [edit((0, 1), (0, 2), ''), edit((0, 1), (0, 1), 'X')]))
        self.assertEqual('new!', apply_changes('old', [{'text': 'new'}, edit((0, 3), (0, 999), '!')]))
        self.assertEqual('abc', apply_changes('abc', []))
        self.assertEqual('new', apply_changes(None, [{'text': 'new'}]))

    def test_utf16_surrogates_crlf_cr_and_multiline_ranges(self):
        self.assertEqual('ab\r\nnext', apply_changes('a😀b\r\nnext', [edit((0, 1), (0, 3), '', rangeLength=2)]))
        self.assertEqual('aXext', apply_changes('a😀b\r\nnext', [edit((0, 1), (1, 1), 'X', rangeLength=6)]))
        self.assertEqual(3, edit_offset('ab\rcd\nef', point(1, 0)))
        self.assertEqual(2, edit_offset('ab\r\ncd', point(0, 500)))
        self.assertEqual(6, edit_offset('ab\r\ncd\r\n', point(1, 500)))
        self.assertEqual(8, edit_offset('ab\r\ncd\r\n', point(2, 0)))

    def test_rejects_invalid_ranges_and_lengths(self):
        source = 'a😀b'
        for changes in ([edit((0, 2), (0, 3), '')], [edit((0, 3), (0, 1), '')],
                        [edit((1, 0), (1, 0), '')], [edit((0, -1), (0, 1), '')],
                        [edit((0, True), (0, 1), '')], [edit((0, 1), (0, 3), '', rangeLength=1)],
                        [edit((0, 1), (0, 3), '', rangeLength=True)], [{'text': 'x', 'rangeLength': 1}],
                        [{'text': 5}], [{'text': '\ud800'}], [{'text': 'x', 'range': None}], {}, [None]):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply_changes(source, changes)

    def test_bounds_utf8_reconstruction_and_change_count(self):
        for source, changes in (('', [{'text': 'é'*(MAX_DOCUMENT_BYTES//2+1)}]),
                                ('x'*MAX_DOCUMENT_BYTES, [edit((0, 0), (0, 0), 'x')]),
                                ('', [{'text': ''}]*129)):
            with self.subTest(size=len(source)), self.assertRaises(ValueError):
                apply_changes(source, changes)
        with self.assertRaises(ValueError):
            apply_changes(None, [])


class IncrementalSyncTests(unittest.TestCase):
    def setUp(self):
        self.output = io.BytesIO()
        self.server = Server(self.output)
        self.server.handle({'id': 1, 'method': 'initialize'})
        self.server.handle({'method': 'textDocument/didOpen', 'params': {
            'textDocument': {'uri': URI, 'version': 1, 'text': SOURCE}}})

    def changes(self, changes, version=2):
        self.server.handle({'method': 'textDocument/didChange', 'params': {
            'textDocument': {'uri': URI, 'version': version}, 'contentChanges': changes}})

    def messages(self):
        stream, result = io.BytesIO(self.output.getvalue()), []
        while (message := read_message(stream)) is not None:
            result.append(message)
        return result

    def test_ranged_changes_match_fresh_shared_analysis_without_io(self):
        with patch('builtins.open', side_effect=AssertionError('no URI reads')), \
                patch('subprocess.run', side_effect=AssertionError('no native execution')):
            self.changes([edit((0, 3), (0, 5), '🙂', rangeLength=2), edit((1, 26), (1, 27), '256')])
        document = self.server.documents[URI]
        expected = SOURCE.replace('😀', '🙂').replace('return 1;', 'return 256;')
        self.assertEqual(expected, document.source)
        self.assertEqual(analyze(expected), document.analysis)
        self.assertTrue(document.synchronized)
        self.assertEqual(2, document.version)
        self.assertEqual([], self.messages()[-1]['params']['diagnostics'])

    def test_semantic_error_and_repair_publish_current_diagnostics(self):
        self.changes([edit((1, 26), (1, 27), 'true')])
        self.assertIsNone(self.server.documents[URI].analysis)
        self.assertTrue(self.server.documents[URI].synchronized)
        self.assertEqual('E0201', self.messages()[-1]['params']['diagnostics'][0]['code'])
        self.changes([edit((1, 26), (1, 30), '7')], version=3)
        self.assertEqual(analyze(SOURCE.replace('return 1;', 'return 7;')), self.server.documents[URI].analysis)

    def test_invalid_late_edit_does_not_publish_partial_source_and_requires_resync(self):
        self.changes([edit((1, 26), (1, 27), '2'), edit((0, 4), (0, 5), 'x')])
        document = self.server.documents[URI]
        self.assertEqual(SOURCE, document.source)
        self.assertFalse(document.synchronized)
        self.assertIsNone(document.analysis)
        self.assertEqual(2, document.version)
        self.assertEqual([], self.messages()[-2]['params']['diagnostics'])
        methods = ('hover', 'definition', 'documentSymbol', 'completion', 'signatureHelp', 'semanticTokens/full',
                   'references', 'rename', 'formatting')
        for method in methods:
            self.server.handle({'id': 2, 'method': 'textDocument/'+method,
                                'params': {'textDocument': {'uri': URI}, 'position': point(1, 3)}})
            self.assertEqual(-32602, self.messages()[-1]['error']['code'], method)
        self.changes([edit((1, 26), (1, 27), '3')], version=3)
        self.assertFalse(document.synchronized)
        fresh = SOURCE.replace('return 1;', 'return 9;')
        self.changes([{'text': fresh}, edit((1, 26), (1, 27), '8')], version=4)
        self.assertTrue(self.server.documents[URI].synchronized)
        self.assertEqual(analyze(fresh.replace('9', '8')), self.server.documents[URI].analysis)

    def test_stale_versions_are_ignored_before_interpreting_edit_ranges(self):
        self.changes([edit((1, 26), (1, 27), '2')])
        document = self.server.documents[URI]
        count = len(self.messages())
        self.changes([edit((100, 0), (100, 0), 'bad')], version=1)
        self.assertIs(document, self.server.documents[URI])
        self.assertTrue(document.synchronized)
        self.assertEqual(count, len(self.messages()))

    def test_large_mirror_has_current_size_error_and_can_be_repaired(self):
        self.changes([{'text': 'x'*262145}])
        self.assertTrue(self.server.documents[URI].synchronized)
        self.assertEqual('E0005', self.messages()[-1]['params']['diagnostics'][0]['code'])
        self.changes([{'text': SOURCE}], version=3)
        self.assertEqual(analyze(SOURCE), self.server.documents[URI].analysis)

    def test_empty_change_version_and_closed_document_rejection(self):
        self.changes([])
        self.assertEqual(2, self.server.documents[URI].version)
        self.assertEqual(SOURCE, self.server.documents[URI].source)
        self.server.handle({'method': 'textDocument/didClose', 'params': {'textDocument': {'uri': URI}}})
        self.changes([{'text': SOURCE}], version=3)
        self.assertNotIn(URI, self.server.documents)
        self.assertEqual('window/logMessage', self.messages()[-1]['method'])

    def test_framed_wire_delta_and_hover_use_reconstructed_text(self):
        messages = [{'id': 1, 'method': 'initialize'},
                    {'method': 'textDocument/didOpen', 'params': {'textDocument': {'uri': URI, 'version': 1, 'text': SOURCE}}},
                    {'method': 'textDocument/didChange', 'params': {'textDocument': {'uri': URI, 'version': 2},
                                                                 'contentChanges': [edit((1, 3), (1, 7), 'start')]}},
                    {'id': 2, 'method': 'textDocument/hover', 'params': {'textDocument': {'uri': URI}, 'position': point(1, 4)}},
                    {'id': 3, 'method': 'shutdown'}, {'method': 'exit'}]
        incoming, outgoing = io.BytesIO(), io.BytesIO()
        for message in messages:
            write_message(incoming, {'jsonrpc': '2.0', **message})
        self.assertEqual(0, serve(io.BytesIO(incoming.getvalue()), outgoing))
        stream, responses = io.BytesIO(outgoing.getvalue()), []
        while (message := read_message(stream)) is not None:
            responses.append(message)
        hover = next(response for response in responses if response.get('id') == 2)
        self.assertEqual('fn start() -> i32', hover['result']['contents']['value'])

    def test_missing_changes_at_new_version_clears_stale_model(self):
        self.server.handle({'method': 'textDocument/didChange', 'params': {'textDocument': {'uri': URI, 'version': 2}}})
        document = self.server.documents[URI]
        self.assertFalse(document.synchronized)
        self.assertIsNone(document.analysis)
        self.assertEqual(SOURCE, document.source)
