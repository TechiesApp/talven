import io
import json
import unittest
from unittest.mock import patch

from talven.frontend import analyze, source_range
from talven.formatter import format_source
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
        self.assertTrue(first["result"]["capabilities"]["documentFormattingProvider"])

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

    def test_borrow_permissions_appear_in_hover_and_field_definition(self):
        source = "struct P { x: i32 } fn update(p: &mut P) -> i32 { p.x = p.x + 1; return p.x; }"
        self.open(source)
        analysis = analyze(source)
        ref = next(r for r in analysis.references if "exclusive borrow" in r.description and r.span.start > 50)
        point = source_range(source, ref.span)["start"]
        self.assertIn("&mut P (exclusive borrow; call-scoped)", self.query("textDocument/hover", point)["result"]["contents"]["value"])
        field = next(r for r in analysis.references if r.description == "x: i32" and r.span.start > 50)
        definition = self.query("textDocument/definition", source_range(source, field.span)["start"])["result"]
        self.assertEqual(source_range(source, analysis.records["P"].fields[0][0].span), definition["range"])

    def test_conflicting_borrow_edit_uses_frontend_diagnostic_and_recovers(self):
        source = "struct P { x: i32 } fn f(a: &mut P, b: &P) -> i32 { return a.x + b.x; } fn main() -> i32 { let mut p = P { x: 1 }; return f(&mut p, &p); }"
        with patch("subprocess.run", side_effect=AssertionError("LSP must not execute tools")):
            self.open(source)
            self.assertEqual("E0302", self.messages()[-1]["params"]["diagnostics"][0]["code"])
            fixed = source.replace("a: &mut P", "a: &P").replace("f(&mut p,", "f(&p,")
            self.server.handle({"method": "textDocument/didChange", "params": {
                "textDocument": {"uri": URI, "version": 2}, "contentChanges": [{"text": fixed}]}})
        self.assertEqual([], self.messages()[-1]["params"]["diagnostics"])
        self.assertIsNotNone(self.server.documents[URI].analysis)

    def test_invalid_and_oversized_messages_fail_cleanly(self):
        cases = [b"Content-Length: 999999999\r\n\r\n", b"Content-Length: 2\r\n\r\nx",
                 b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}"]
        for raw in cases:
            with self.subTest(raw=raw):
                output = io.BytesIO()
                self.assertEqual(1, serve(io.BytesIO(raw), output))
                self.assertEqual(-32700, read_message(io.BytesIO(output.getvalue()))["error"]["code"])

    def framed(self, *bodies):
        return b"".join(f"Content-Length: {len(body)}\r\n\r\n".encode() + body for body in bodies)

    def test_complete_invalid_bodies_are_rejected_and_session_continues(self):
        initialize = b'{"jsonrpc":"2.0","id":7,"method":"initialize"}'
        cases = [(b"{}", -32600), (b'{"jsonrpc":"2.0",', -32700),
                 (b'{"jsonrpc":"2.0","id":"\\ud800","method":"x"}', -32600),
                 (b'{"jsonrpc":"2.0","id":{"a":1},"method":"x"}', -32600),
                 (b'{"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":'
                  b'{"uri":"file:///a.tal","version":1,"text":"\\udc00"}}}', -32600)]
        for body, code in cases:
            with self.subTest(body=body):
                output = io.BytesIO()
                self.assertEqual(1, serve(io.BytesIO(self.framed(body, initialize)), output))
                stream = io.BytesIO(output.getvalue())
                rejected, answered = read_message(stream), read_message(stream)
                self.assertEqual(code, rejected["error"]["code"])
                self.assertIsNone(rejected["id"])
                self.assertEqual(7, answered["id"])
                self.assertIn("capabilities", answered["result"])

    def test_null_params_are_treated_as_empty(self):
        self.server.handle({"id": 5, "method": "shutdown", "params": None})
        self.assertEqual(5, self.messages()[-1]["id"])
        self.assertNotIn("error", self.messages()[-1])
        self.assertEqual(0, self.server.handle({"method": "exit", "params": None}))

    def test_bare_carriage_return_is_diagnosed_on_its_own_line(self):
        self.open("fn main() -> i32 {\n    // note\r    return 7;\n}\n")
        diagnostic = self.messages()[-1]["params"]["diagnostics"][0]
        self.assertEqual("E0001", diagnostic["code"])
        self.assertEqual({"line": 1, "character": 11}, diagnostic["range"]["start"])

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
        # Python may reject the depth while parsing or leave it to the nesting limit.
        self.assertIn(read_message(io.BytesIO(output.getvalue()))["error"]["code"], (-32700, -32600))

    def position(self, source, offset):
        prefix = source[:offset]
        return {"line": prefix.count("\n"), "character": len(prefix.rsplit("\n", 1)[-1].encode("utf-16-le")) // 2}

    def request(self, method, source, offset, **params):
        self.server.handle({"id": 11, "method": method, "params": {
            "textDocument": {"uri": URI}, "position": self.position(source, offset), **params}})
        return self.messages()[-1]

    def test_references_group_by_declaration_and_respect_include_declaration(self):
        source = ("struct P { x: i32 }\nfn read(p: &P) -> i32 { return p.x; }\n"
                  "fn main() -> i32 { let p = P { x: 1 }; return read(&p) + p.x; }")
        self.open(source)
        field = self.request("textDocument/references", source, source.index("x"), context={"includeDeclaration": True})
        self.assertEqual(4, len(field["result"]))  # declaration, two reads, one constructor label
        without = self.request("textDocument/references", source, source.index("x"), context={"includeDeclaration": False})
        self.assertEqual(3, len(without["result"]))
        # The parameter p in read and the local p in main are different symbols.
        param = self.request("textDocument/references", source, source.index("p: &P"), context={"includeDeclaration": True})
        self.assertEqual(2, len(param["result"]))
        self.assertIsNone(self.request("textDocument/references", "", 0)["result"])

    def test_rename_edits_every_use_and_keeps_the_program_valid(self):
        source = ("struct Counter { value: i32 }\nfn add(c: &mut Counter) -> i32 { c.value = c.value + 1; return c.value; }\n"
                  "fn main() -> i32 { let mut c = Counter { value: 1 }; return add(&mut c); }")
        self.open(source)
        for offset, new_name, count in ((source.index("Counter"), "Tally", 3), (source.index("value"), "level", 5)):
            with self.subTest(new_name=new_name):
                edits = self.request("textDocument/rename", source, offset, newName=new_name)["result"]["changes"][URI]
                self.assertEqual(count, len(edits))
                renamed = source
                for edit in sorted(edits, key=lambda e: e["range"]["start"]["character"] + 1000 * e["range"]["start"]["line"],
                                   reverse=True):
                    lines = renamed.split("\n")
                    line = edit["range"]["start"]["line"]
                    start, end = edit["range"]["start"]["character"], edit["range"]["end"]["character"]
                    lines[line] = lines[line][:start] + edit["newText"] + lines[line][end:]
                    renamed = "\n".join(lines)
                analyze(renamed)
                self.assertIn(new_name, renamed)

    def test_rename_rejects_reserved_invalid_colliding_and_builtin_targets(self):
        source = "fn add(x: i32) -> i32 { return x; }\nfn main() -> i32 { let y = add(1); return print(\"a\") + y; }"
        self.open(source)
        for new_name, code in (("if", -32602), ("i32", -32602), ("9lives", -32602), ("main", -32803)):
            with self.subTest(new_name=new_name):
                reply = self.request("textDocument/rename", source, source.index("add"), newName=new_name)
                self.assertEqual(code, reply["error"]["code"])
        self.assertEqual(-32803, self.request("textDocument/rename", source, source.index("print"), newName="out")["error"]["code"])

    def test_diagnostics_include_every_recovered_error(self):
        self.open("fn f() -> i32 { let x = 1; let x = 2; return x; }\nfn g() -> i32 { return 1 }\n")
        published = self.messages()[-1]["params"]["diagnostics"]
        self.assertEqual(["E0002", "E0102"], sorted(d["code"] for d in published))

    def formatting(self, options=None):
        self.server.handle({"id": 4, "method": "textDocument/formatting", "params": {
            "textDocument": {"uri": URI}, "options": options or {"tabSize": 4, "insertSpaces": True}}})
        return self.messages()[-1]

    def test_formatting_returns_utf16_edit_without_mutating_document(self):
        source = "fn main()->i32{return 0;}// 😀"
        self.open(source, version=3)
        with patch("subprocess.run", side_effect=AssertionError("LSP must not execute tools")):
            edits = self.formatting({"tabSize": 8, "insertSpaces": False})["result"]
        self.assertEqual(1, len(edits))
        self.assertEqual({"line": 0, "character": len(source) + 1}, edits[0]["range"]["end"])
        self.assertEqual(format_source(source), edits[0]["newText"])
        self.assertEqual(source, self.server.documents[URI].source)
        self.assertEqual(3, self.server.documents[URI].version)

    def test_formatting_type_errors_succeeds_but_syntax_errors_produce_no_edit(self):
        self.open("fn main()->i32{return false;}")
        self.assertIsNone(self.server.documents[URI].analysis)
        self.assertIn("return false;", self.formatting()["result"][0]["newText"])
        self.open("fn main()->i32{return 0}", version=2)
        error = self.formatting()["error"]
        self.assertEqual(-32803, error["code"])
        self.assertEqual("E0002", error["data"]["diagnostics"][0]["code"])

    def test_formatting_noop_and_invalid_options(self):
        self.open(format_source(SOURCE))
        self.assertEqual([], self.formatting()["result"])
        self.assertEqual(-32602, self.formatting({"tabSize": True, "insertSpaces": True})["error"]["code"])
        self.assertEqual(-32602, self.formatting({"tabSize": 4})["error"]["code"])

    def test_formatting_does_not_fetch_unopened_uris(self):
        self.assertEqual(-32602, self.formatting()["error"]["code"])
        self.assertEqual({}, self.server.documents)
