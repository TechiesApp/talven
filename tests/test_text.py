import io
import json
import tempfile
import unittest
from pathlib import Path

from talven.backend import emit_c
from talven.context import context
from talven.edit_validation import snapshot_source, validate_edit
from talven.formatter import format_source, token_identity
from talven.frontend import CompileError, analyze, lex
from talven.lsp import Server, read_message


HELLO = 'fn main() -> i32 { return print("Hello, world!\\n"); }'


class TextTests(unittest.TestCase):
    def checked(self, source):
        try:
            return analyze(source)
        except CompileError as error:
            self.fail(f"Valid static text rejected: {error.code}: {error.message}")

    def rejects(self, source, code):
        with self.assertRaises(CompileError) as caught:
            analyze(source)
        self.assertEqual(code, caught.exception.code)

    def test_hello_is_a_checked_call_returning_output_status(self):
        result = self.checked(HELLO)
        self.assertEqual({"print"}, result.functions["main"].calls)
        self.assertEqual("i32", result.functions["main"].body[0].expr.typ)

    def test_static_text_can_be_copied_passed_and_returned(self):
        source = '''fn identity(value: str) -> str { return value; }
fn text() -> str { let s: str = "hello"; identity(s); return s; }
fn main() -> i32 { let s = text(); print(s); return print(s); }'''
        self.checked(source)

    def test_print_requires_exactly_one_text_argument(self):
        for source, code in (
            ('fn main() -> i32 { return print(); }', "E0203"),
            ('fn main() -> i32 { return print("x", "y"); }', "E0203"),
            ('fn main() -> i32 { return print(42); }', "E0201"),
            ('fn main() -> bool { return print("x"); }', "E0201"),
        ):
            with self.subTest(source=source):
                self.rejects(source, code)

    def test_str_and_print_cannot_be_redeclared_globally(self):
        for name in ("str", "print"):
            for source in (f"fn {name}() -> i32 {{ return 0; }}", f"struct {name} {{ x: i32 }}"):
                with self.subTest(source=source):
                    self.rejects(source, "E0102")

    def test_text_does_not_expand_record_fields_borrowing_or_mutation(self):
        cases = (
            ('struct S { text: str }', "E0204"),
            ('fn read(s: &str) -> i32 { return 0; }', "E0305"),
            ('fn main() -> i32 { let mut s = "x"; return 0; }', "E0305"),
            ('fn main() -> i32 { let s = "x"; return print(&s); }', "E0305"),
            ('fn main() -> i32 { let s: i32 = "x"; return s; }', "E0201"),
        )
        for source, code in cases:
            with self.subTest(source=source):
                self.rejects(source, code)

    def test_text_operators_are_rejected_instead_of_pointer_comparisons(self):
        for op, code in (("==", "E0204"), ("!=", "E0204"), ("+", "E0201"), ("<", "E0201")):
            with self.subTest(op=op):
                self.rejects(f'fn f() -> bool {{ return "a" {op} "b"; }}', code)

    def test_print_preserves_an_enclosing_calls_active_borrow(self):
        source = '''struct P { value: i32 }
fn label(p: &P) -> str { return "x"; }
fn use(p: &mut P, result: i32) -> i32 { return result; }
fn main() -> i32 {
    let mut p = P { value: 1 };
    return use(&mut p, print(label(&p)));
}'''
        self.rejects(source, "E0302")

    def test_invalid_and_unterminated_literals_have_structured_diagnostics(self):
        for literal in ('"bad\\q"', '"bad\\u0041"', '"bad\\x41"', '"open', '"open\\',
                        '"raw\nline"', '"raw\rline"', '"raw\tcontrol"', '"raw\x00control"'):
            source = 'fn f() -> str { return ' + literal + '; }'
            with self.subTest(literal=literal), self.assertRaises(CompileError) as caught:
                lex(source)
            self.assertEqual("E0006", caught.exception.code)
            self.assertEqual(23, caught.exception.span.start)

    def test_formatter_preserves_literal_bytes_escapes_and_comment_markers(self):
        source = r'''fn main()->i32{let s="// {} , ; \" \\ \n \r \t \0 😀";return print(s);}'''
        try:
            formatted = format_source(source)
        except CompileError as error:
            self.fail(f"Text formatting rejected: {error.code}")
        self.assertEqual(token_identity(lex(source)), token_identity(lex(formatted)))
        self.assertIn(r'"// {} , ; \" \\ \n \r \t \0 😀"', formatted)
        self.assertEqual(formatted, format_source(formatted))

    def test_context_exposes_builtin_dependency_and_copy_contract(self):
        result = self.checked('fn echo(s: str) -> i32 { return print(s); } ' +
                              'fn main() -> i32 { return echo("x"); }')
        for symbol in (None, "echo", "main"):
            with self.subTest(symbol=symbol):
                packet = json.loads(context(result, symbol=symbol))
                self.assertEqual(["posix-console"], packet["required_runtime"])
                self.assertEqual("print", packet["builtins"][0]["name"])
                self.assertEqual("fn print(text: str) -> i32", packet["builtins"][0]["signature"])
                facts = packet["functions"] + packet["dependencies"]
                echo = next(f for f in facts if f["name"] == "echo")
                self.assertEqual("copy", echo["parameters"][0]["passing"])

    def test_context_reports_runtime_even_for_an_unselected_emitted_function(self):
        source = 'fn other() -> i32 { return print("x"); } fn main() -> i32 { return 0; }'
        packet = json.loads(context(self.checked(source), symbol="main", freestanding=True))
        self.assertEqual("frontend-only", packet["validation"])
        self.assertEqual(["posix-console"], packet["required_runtime"])

    def test_console_requires_explicit_hosted_emission_option(self):
        result = self.checked(HELLO)
        for options in ({}, {"freestanding": True}, {"freestanding": True, "console": True}):
            with self.subTest(options=options), self.assertRaises(CompileError) as caught:
                emit_c(result, **options)
            self.assertEqual("E0404", caught.exception.code)
        unused = self.checked('fn unused() -> i32 { return print("x"); } fn main() -> i32 { return 0; }')
        with self.assertRaises(CompileError) as caught:
            emit_c(unused)
        self.assertEqual("E0404", caught.exception.code)

    def test_edit_preview_records_adding_print_without_executing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, candidate = Path(temporary) / "a.tal", Path(temporary) / "b.tal"
            source.write_text('fn main() -> i32 { return 0; }')
            candidate.write_text(HELLO)
            snapshot = snapshot_source(source)
            result = validate_edit(source, candidate, expected_source_hash=snapshot["source_hash"],
                                   expected_compiler_hash=snapshot["compiler_hash"])
            self.assertTrue(result["ok"], result)
            self.assertEqual([{"name": "main", "before": [], "after": ["print"]}], result["changes"]["calls_changed"])

    def test_editor_reports_text_errors_and_builtin_hover_without_fake_definition(self):
        output = io.BytesIO()
        server = Server(output)
        server.handle({"id": 0, "method": "initialize"})
        uri = "file:///workspace/hello.tal"
        server.handle({"method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "version": 1, "text": HELLO}}})
        self.assertIsNotNone(server.documents[uri].analysis)
        for identity, method in ((1, "hover"), (2, "definition")):
            server.handle({"id": identity, "method": "textDocument/" + method, "params": {
                "textDocument": {"uri": uri}, "position": {"line": 0, "character": HELLO.index("print")}}})
        stream = io.BytesIO(output.getvalue())
        messages = []
        while (message := read_message(stream)) is not None:
            messages.append(message)
        self.assertIn("fn print(text: str) -> i32", messages[-2]["result"]["contents"]["value"])
        self.assertIsNone(messages[-1]["result"])
        server.handle({"method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": HELLO.replace('"Hello, world!\\n"', '7')}]}})
        self.assertIsNone(server.documents[uri].analysis)


if __name__ == "__main__":
    unittest.main()
