import io
import json
import unittest
from unittest.mock import patch

from talven.frontend import analyze, source_range
from talven.lsp import Server, offset_at, read_message, serve, write_message

URI = "file:///workspace/example.tal"
SOURCE = "// 😀\nfn add(x: i32) -> i32 { return x + 1; }\nfn main() -> i32 { return add(1); }"


class LspTests(unittest.TestCase):
    def setUp(self):
        self.output = io.BytesIO()
        self.server = Server(self.output)
        self.server.handle({"id": 1, "method": "initialize"})

    def messages(self):
        stream = io.BytesIO(self.output.getvalue())
        result = []
        while (message := read_message(stream)) is not None:
            result.append(message)
        return result

    def open(self, text=SOURCE, version=1):
        self.server.handle({"method": "textDocument/didOpen",
                            "params": {"textDocument": {"uri": URI, "version": version, "text": text}}})

    def query(self, method, point=None):
        params = {"textDocument": {"uri": URI}}
        if point is not None:
            params["position"] = point
        self.server.handle({"id": 2, "method": method, "params": params})
        return self.messages()[-1]

    def test_lifecycle_framing_and_capabilities(self):
        requests = io.BytesIO()
        for message in ({"id": 1, "method": "initialize"}, {"id": 2, "method": "shutdown"}, {"method": "exit"}):
            write_message(requests, {"jsonrpc": "2.0", **message})
        output = io.BytesIO()
        self.assertEqual(0, serve(io.BytesIO(requests.getvalue()), output))
        first = read_message(io.BytesIO(output.getvalue()))
        self.assertEqual("utf-16", first["result"]["capabilities"]["positionEncoding"])
        self.assertEqual(1, first["result"]["capabilities"]["textDocumentSync"]["change"])

    def test_editor_and_compiler_share_diagnostics_without_execution(self):
        invalid = "fn main() -> i32 { return false; }"
        with patch("subprocess.run", side_effect=AssertionError("LSP must not execute code")):
            self.open(invalid)
        published = self.messages()[-1]["params"]["diagnostics"]
        self.assertEqual("E0201", published[0]["code"])
        self.assertEqual(1, len(published))

    def test_hover_definition_and_symbols_share_frontend(self):
        self.open()
        analysis = analyze(SOURCE)
        ref = next(r for r in analysis.references if r.description.startswith("fn add") and r.span.start > 50)
        point = source_range(SOURCE, ref.span)["start"]
        hover = self.query("textDocument/hover", point)["result"]
        self.assertEqual("fn add(x: i32) -> i32", hover["contents"]["value"])
        definition = self.query("textDocument/definition", point)["result"]
        self.assertEqual(source_range(SOURCE, analysis.functions["add"].name.span), definition["range"])
        self.assertEqual(["add", "main"], [v["name"] for v in self.query("textDocument/documentSymbol")["result"]])

    def test_new_version_replaces_stale_model_and_old_version_is_ignored(self):
        self.open()
        for version, text in ((2, "fn main() -> i32 { return false; }"), (1, SOURCE)):
            self.server.handle({"method": "textDocument/didChange", "params": {
                "textDocument": {"uri": URI, "version": version}, "contentChanges": [{"text": text}]}})
        self.assertIsNone(self.server.documents[URI].analysis)
        self.assertEqual(2, self.server.documents[URI].version)
        self.server.handle({"method": "textDocument/didClose", "params": {"textDocument": {"uri": URI}}})
        self.assertNotIn(URI, self.server.documents)
        self.assertEqual([], self.messages()[-1]["params"]["diagnostics"])

    def test_utf16_offset_does_not_split_surrogate_pair(self):
        self.assertEqual(1, offset_at("😀x", {"line": 0, "character": 2}))
        self.assertIsNone(offset_at("😀x", {"line": 0, "character": 1}))
        self.assertIsNone(offset_at(SOURCE, {"line": -1, "character": 0}))

    def test_invalid_and_oversized_messages_fail_cleanly(self):
        cases = [b"Content-Length: 999999999\r\n\r\n", b"Content-Length: 2\r\n\r\nx",
                 b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
                 b"Content-Length: 2\r\n\r\n{}"]
        for raw in cases:
            with self.subTest(raw=raw):
                output = io.BytesIO()
                self.assertEqual(1, serve(io.BytesIO(raw), output))
                self.assertEqual(-32700, read_message(io.BytesIO(output.getvalue()))["error"]["code"])

    def test_unknown_request_and_shutdown_behavior(self):
        self.assertEqual(-32601, self.query("workspace/executeCommand")["error"]["code"])
        self.server.handle({"id": 3, "method": "shutdown"})
        self.assertEqual(0, self.server.handle({"method": "exit"}))
        self.assertEqual(1, Server(io.BytesIO()).handle({"method": "exit"}))

    def test_malformed_parameters_and_deep_json_are_controlled(self):
        self.server.handle({"id": 9, "method": "textDocument/hover", "params": []})
        self.assertEqual(-32602, self.messages()[-1]["error"]["code"])
        self.assertIsNone(offset_at(SOURCE, []))
        body = ('{"jsonrpc":"2.0","params":' + '[' * 2000 + '0' + ']' * 2000 + '}').encode()
        raw = f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        output = io.BytesIO()
        self.assertEqual(1, serve(io.BytesIO(raw), output))
        self.assertEqual(-32700, read_message(io.BytesIO(output.getvalue()))["error"]["code"])
