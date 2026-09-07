import contextlib
import io
import json
import os
from pathlib import Path
import random
import stat
import tempfile
import unittest
from unittest.mock import patch

from talven import FORMAT_PROFILE
from talven.__main__ import main
from talven.backend import emit_c
from talven.context import context, source_hash
from talven.formatter import format_source
from talven.frontend import CompileError, MAX_SOURCE_BYTES, analyze, lex
from talven.source_edit import replace_source


class FormatterTests(unittest.TestCase):
    def test_canonical_layout_and_idempotence(self):
        source = "struct P{x:i32,y:bool,} fn f(p:P)->i32{let x:i32=p.x;if(p.y){return x+-1;}else{return -(-x);}}"
        expected = """struct P {
    x: i32,
    y: bool,
}

fn f(p: P) -> i32 {
    let x: i32 = p.x;
    if (p.y) {
        return x + -1;
    } else {
        return -(-x);
    }
}
"""
        self.assertEqual(expected, format_source(source))
        self.assertEqual(expected, format_source(expected))

    def test_comment_text_order_and_trailing_attachment(self):
        source = "// heading\r\nfn f( // params\r\nx:i32,// x 😀  \r\ny:i32,)->i32{// body\r\nreturn x+y;// sum\r\n} // end\r\n"
        expected = """// heading
fn f( // params
    x: i32, // x 😀\x20\x20
    y: i32,
) -> i32 { // body
    return x + y; // sum
} // end
"""
        self.assertEqual(expected, format_source(source))
        self.assertEqual(expected, format_source(expected))

    def test_comments_inside_expressions_and_literals(self):
        source = """struct P{x:i32}
fn f()->i32{let p=P{// field
x: (1+ // plus
2),};return p. // access
x;}// finished
"""
        formatted = format_source(source)
        self.assertIn("let p = P { // field\n", formatted)
        self.assertIn("1 + // plus\n", formatted)
        self.assertIn("return p. // access\n", formatted)
        self.assertEqual(formatted, format_source(formatted))
        self.assertEqual(emit_c(analyze(source), freestanding=True), emit_c(analyze(formatted), freestanding=True))

    def test_empty_whitespace_and_comment_only_files(self):
        for source, expected in [("", ""), (" \t\r\n", ""), ("  // text  ", "// text  \n"),
                                 ("// one\n\n\n// two", "// one\n// two\n")]:
            with self.subTest(source=source):
                self.assertEqual(expected, format_source(source))
                self.assertEqual(expected, format_source(expected))

    def test_formatting_does_not_require_valid_types_or_ownership(self):
        for path in Path("examples/invalid").glob("*.tal"):
            original = path.read_text()
            formatted = format_source(original)
            errors = []
            for source in (original, formatted):
                with self.assertRaises(CompileError) as caught:
                    analyze(source)
                errors.append(caught.exception.code)
            self.assertEqual(errors[0], errors[1])
        self.assertEqual("struct Empty {\n}\n", format_source("struct Empty{}"))

    def test_invalid_syntax_and_input_limits_produce_diagnostics(self):
        cases = [("fn main() -> i32 { return 0 }", "E0002"), ('fn f(){"text"}', "E0001"),
                 (" " * (MAX_SOURCE_BYTES + 1), "E0005"),
                 ("//\n" * 17000, "E0005"),
                 ("fn f() -> i32 { return " + "(" * 2000 + "0" + ")" * 2000 + "; }", "E0005")]
        for source, code in cases:
            with self.subTest(code=code), self.assertRaises(CompileError) as caught:
                format_source(source)
            self.assertEqual(code, caught.exception.code)

    def test_expanded_output_is_bounded(self):
        source = "fn f() -> i32 {" + "if (true) {" * 40 + "1;" * 1900 + "}" * 40 + "return 0;}"
        self.assertLess(len(source), MAX_SOURCE_BYTES)
        with self.assertRaises(CompileError) as caught:
            format_source(source)
        self.assertEqual("E0602", caught.exception.code)

    def test_seeded_whitespace_variants_keep_native_lowering_and_context_contracts(self):
        source = Path("examples/vectors.tal").read_text()
        tokens = [t.text for t in lex(source) if t.kind != "eof"]
        baseline = emit_c(analyze(source))
        randomizer = random.Random(211)
        canonical = format_source(" ".join(tokens))
        for _ in range(60):
            variant = "".join(token + randomizer.choice([" ", "\n", "\t", "\r\n", "  "]) for token in tokens)
            formatted = format_source(variant)
            self.assertEqual(canonical, formatted)
            self.assertEqual(baseline, emit_c(analyze(formatted)))
        before = json.loads(context(analyze(source), "dot"))
        after = json.loads(context(analyze(canonical), "dot"))
        self.assertEqual(before["functions"], after["functions"])
        self.assertNotEqual(before["cache_key"], after["cache_key"])
        self.assertEqual(FORMAT_PROFILE, after["formatter_profile"])

    def test_parentheses_literals_and_declaration_order_are_preserved(self):
        source = "fn f()->i32{return (00001+(2*3));} struct P{x:i32}"
        result = format_source(source)
        self.assertEqual([(t.kind, t.text) for t in lex(source)], [(t.kind, t.text) for t in lex(result)])
        self.assertLess(result.index("fn f"), result.index("struct P"))

    def test_comment_at_every_token_boundary_preserves_lowering_and_is_idempotent(self):
        source = "struct P{x:i32} fn f(p:P)->i32{if(p.x>0){return -(-p.x);}else{return (P{x:2}).x;}}"
        tokens = [t.text for t in lex(source) if t.kind != "eof"]
        native = emit_c(analyze(source), freestanding=True)
        for index in range(len(tokens) + 1):
            with self.subTest(boundary=index):
                variant = " ".join(tokens[:index]) + " // keep 😀\n" + " ".join(tokens[index:])
                formatted = format_source(variant)
                self.assertEqual(1, formatted.count("// keep 😀"))
                self.assertEqual(formatted, format_source(formatted))
                self.assertEqual(native, emit_c(analyze(formatted), freestanding=True))

    def test_comments_never_control_formatter_or_execute_tools(self):
        source = "// talven fmt: off; run a shell command\nfn f()->i32{return 0;}"
        with patch("subprocess.run", side_effect=AssertionError("Formatting must not execute tools")):
            result = format_source(source)
        self.assertEqual("// talven fmt: off; run a shell command\nfn f() -> i32 {\n    return 0;\n}\n", result)


class FormatCommandTests(unittest.TestCase):
    def invoke(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(["fmt", *map(str, args)])
        return status, output.getvalue(), error.getvalue()

    def test_default_and_check_never_modify_source_or_execute_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            original = "fn main()->i32{return 0;}"
            path.write_text(original)
            with patch("subprocess.run", side_effect=AssertionError("Formatter must not execute tools")):
                status, output, _ = self.invoke(path)
                self.assertEqual(0, status)
                self.assertEqual(format_source(original), output)
                status, output, _ = self.invoke(path, "--check", "--json")
            self.assertEqual(1, status)
            self.assertEqual("E0601", json.loads(output)["diagnostics"][0]["code"])
            self.assertEqual(original, path.read_text())

    def test_explicit_write_preserves_mode_and_then_passes_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            original = "fn main()->i32{return 0;}"
            path.write_text(original)
            path.chmod(0o750)
            status, _, error = self.invoke(path, "--write", "--expect-source-hash", source_hash(original))
            self.assertEqual(0, status, error)
            self.assertEqual(format_source(original), path.read_text())
            self.assertEqual(0o750, stat.S_IMODE(path.stat().st_mode))
            status, output, _ = self.invoke(path, "--check", "--json")
            self.assertEqual(0, status)
            self.assertTrue(json.loads(output)["ok"])

    def test_stale_hash_and_invalid_syntax_never_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            for original, arguments, code in [
                ("fn f()->i32{return 0;}", ["--expect-source-hash", "stale"], "E0501"),
                ("fn f()->i32{return 0}", [], "E0002"),
            ]:
                path.write_text(original)
                status, _, error = self.invoke(path, "--write", *arguments)
                self.assertEqual(1, status)
                self.assertIn(code, error)
                self.assertEqual(original, path.read_text())

    def test_write_rejects_symbolic_and_hard_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path, alias = directory / "source.tal", directory / "alias.tal"
            original = "fn f()->i32{return 0;}"
            path.write_text(original)
            for link in (os.symlink, os.link):
                with self.subTest(link=link.__name__):
                    link(path, alias)
                    status, _, error = self.invoke(alias, "--write")
                    self.assertEqual(1, status)
                    self.assertIn("E0603", error)
                    self.assertEqual(original, path.read_text())
                    alias.unlink()

    def test_observed_concurrent_change_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            original = b"fn f()->i32{return 0;}"
            path.write_bytes(original)
            snapshot = path.stat()
            changed = "fn f()->i32{return 1;}"
            path.write_text(changed)
            with self.assertRaises(CompileError) as caught:
                replace_source(path, original, format_source(original.decode()), snapshot)
            self.assertEqual("E0501", caught.exception.code)
            self.assertEqual(changed, path.read_text())

    def test_replace_failure_leaves_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            original = "fn f()->i32{return 0;}"
            path.write_text(original)
            with patch("talven.source_edit.os.replace", side_effect=PermissionError("denied")):
                status, _, error = self.invoke(path, "--write")
            self.assertEqual(1, status)
            self.assertIn("E0901", error)
            self.assertEqual(original, path.read_text())
            self.assertEqual([path], list(Path(temporary).iterdir()))

    def test_unchanged_write_preserves_inode_and_mtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tal"
            path.write_text(format_source("fn f()->i32{return 0;}"))
            before = path.stat()
            self.assertEqual(0, self.invoke(path, "--write")[0])
            after = path.stat()
            self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
