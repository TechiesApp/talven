import json
import unittest

from talven import FORMAT_PROFILE, PROFILE
from talven.context import context
from talven.formatter import format_source
from talven.backend import emit_c
from talven.frontend import CompileError, analyze, lex


RECORD = "struct P { x: i32 }\n"
FUNCTIONS = """
fn read(p: &P) -> i32 { return p.x; }
fn bump(p: &mut P) -> i32 { p.x = p.x + 1; return p.x; }
fn take(p: P) -> i32 { return p.x; }
fn shared(a: &P, b: &P) -> i32 { return a.x + b.x; }
fn mixed(a: &mut P, b: &P) -> i32 { a.x = b.x; return a.x; }
fn exclusive(a: &mut P, b: &mut P) -> i32 { a.x = b.x; return a.x; }
fn shared_value(a: &P, b: i32) -> i32 { return a.x + b; }
fn exclusive_value(a: &mut P, b: i32) -> i32 { a.x = b; return a.x; }
fn values(a: i32, b: i32) -> i32 { return a + b; }
"""


class BorrowingTests(unittest.TestCase):
    def check_body(self, body, extra=""):
        return analyze(RECORD + FUNCTIONS + extra + "fn main() -> i32 {" + body + "}")

    def reject(self, source, code):
        with self.assertRaises(CompileError) as caught:
            analyze(source)
        self.assertEqual(code, caught.exception.code, caught.exception.message)

    def test_shared_aliases_and_reads_are_allowed(self):
        self.check_body("let p = P { x: 1 }; shared(&p, &p); return shared_value(&p, p.x);")

    def test_mutable_owner_and_exclusive_parameter_write(self):
        self.check_body("let mut p = P { x: 1 }; p.x = 2; bump(&mut p); return read(&p);")

    def test_reborrowing_forwards_pointee_without_escape(self):
        self.check_body("let mut p = P { x: 1 }; return forward(&mut p);", """
            fn forward(p: &mut P) -> i32 { bump(&mut p); return read(&p); }
            fn forward_read(p: &P) -> i32 { return shared(&p, &p); }
        """)

    def test_loans_end_at_their_call_and_owner_can_move(self):
        self.check_body("""let mut p = P { x: 1 };
            shared(&p, &p); bump(&mut p); values(bump(&mut p), bump(&mut p));
            let q = p; return take(q);""")

    def test_scalar_read_before_exclusive_argument_is_allowed(self):
        self.check_body("let mut p = P { x: 1 }; return values(p.x, bump(&mut p));")

    def test_conflicts_cover_later_and_nested_arguments(self):
        cases = ["mixed(&mut p, &p)", "exclusive(&mut p, &mut p)",
                 "exclusive_value(&mut p, p.x)", "exclusive_value(&mut p, read(&p))",
                 "shared_value(&p, bump(&mut p))", "shared_value(&p, take(p))",
                 "shared_value(&p, values(read(&p), bump(&mut p)))",
                 "exclusive_value(&mut p, take(p))"]
        for call in cases:
            with self.subTest(call=call):
                self.reject(RECORD + FUNCTIONS + "fn main() -> i32 { let mut p = P { x: 1 }; return " + call + "; }", "E0302")
        self.reject(RECORD + "fn f(a: &P, b: &mut P) -> i32 { return a.x; }"
                    "fn main() -> i32 { let mut p = P { x: 1 }; return f(&p, &mut p); }", "E0302")

    def test_mutability_permissions_cannot_be_upgraded(self):
        cases = ["fn f(p: &P) -> i32 { p.x = 2; return p.x; }",
                 "fn f(p: &P) -> i32 { return bump(&mut p); }",
                 "fn f(p: P) -> i32 { return bump(&mut p); }",
                 "fn f() -> i32 { let p = P { x: 1 }; p.x = 2; return p.x; }",
                 "fn f() -> i32 { let p = P { x: 1 }; return bump(&mut p); }",
                 "fn f() -> i32 { let mut p = P { x: 1 }; let q = p; return bump(&mut q); }"]
        for source in cases:
            with self.subTest(source=source):
                self.reject(RECORD + FUNCTIONS + source, "E0303")

    def test_owned_parameter_can_move_into_mutable_local(self):
        analyze(RECORD + FUNCTIONS + "fn f(p: P) -> i32 { let mut q = p; return bump(&mut q); }")

    def test_references_cannot_escape_or_be_implicitly_forwarded(self):
        cases = ["fn f(p: &P) -> &P { return p; }",
                 "fn f(p: &P) -> i32 { let q = p; return q.x; }",
                 "fn f(p: &P) -> i32 { return read(p); }",
                 "fn f(p: &P) -> P { return p; }",
                 "fn f(p: P) -> i32 { let q = &p; return 0; }",
                 "fn f(p: P) -> i32 { &p; return 0; }",
                 "fn f(p: P) -> i32 { let q: &P = p; return 0; }"]
        for source in cases:
            with self.subTest(source=source):
                self.reject(RECORD + FUNCTIONS + source, "E0304")
        self.reject(RECORD + "struct Holder { p: &P }", "E0204")

    def test_only_named_record_places_and_scalar_field_writes(self):
        cases = ["fn f(x: &i32) -> i32 { return 0; }",
                 "fn f() -> i32 { let mut x = 1; return x; }",
                 "fn f() -> i32 { return read(&P { x: 1 }); }",
                 "fn f(p: P) -> i32 { return read(&p.x); }",
                 "fn f(p: P) -> i32 { return read(& &p); }",
                 "fn f() -> i32 { (P { x: 1 }).x = 2; return 0; }",
                 "fn f() -> i32 { let x = 1; return read(&x); }"]
        for source in cases:
            with self.subTest(source=source):
                self.reject(RECORD + FUNCTIONS + source, "E0305")

    def test_borrow_modes_and_nominal_record_types_must_match(self):
        for source in ["fn f() -> i32 { let mut p = P { x: 1 }; return read(&mut p); }",
                       "fn f() -> i32 { let p = P { x: 1 }; return bump(&p); }",
                       "struct Q { x: i32 } fn f() -> i32 { let q = Q { x: 1 }; return read(&q); }",
                       "fn f() -> i32 { let mut p = P { x: 1 }; p.x = false; return p.x; }"]:
            with self.subTest(source=source):
                self.reject(RECORD + FUNCTIONS + source, "E0201")

    def test_moves_cannot_be_undone_by_assignment_or_borrow(self):
        for body in ["take(p); return read(&p);", "p.x = take(p); return 0;",
                     "if (true) { take(p); } return bump(&mut p);",
                     "take(p); p.x = 2; return 0;"]:
            with self.subTest(body=body):
                self.reject(RECORD + FUNCTIONS + "fn main() -> i32 { let mut p = P { x: 1 };" + body + "}", "E0301")

    def test_branch_local_borrows_and_assignment_rhs_loans_end(self):
        self.check_body("""let mut p = P { x: 1 };
            if (true) { bump(&mut p); } else { read(&p); }
            p.x = bump(&mut p) + 1; return take(p);""")

    def test_context_v2_declares_parameter_permissions_and_dependencies(self):
        analysis = analyze(RECORD + FUNCTIONS + "fn forward(p: &mut P) -> i32 { bump(&mut p); return read(&p); }")
        packet = json.loads(context(analysis, "forward"))
        self.assertEqual("talven.context.v2", packet["schema"])
        self.assertEqual(PROFILE, packet["profile"])
        self.assertEqual(FORMAT_PROFILE, packet["formatter_profile"])
        self.assertEqual([{"name": "p", "type": "&mut P", "passing": "borrow-exclusive",
                           "scope": "call", "may_write": True, "escapes": False}], packet["functions"][0]["parameters"])
        read = next(f for f in packet["dependencies"] if f["name"] == "read")
        self.assertEqual("borrow-shared", read["parameters"][0]["passing"])
        self.assertFalse(read["parameters"][0]["may_write"])
        self.assertEqual(["P"], [r["name"] for r in packet["records"]])
        self.assertNotIn("untrusted_source_text", packet["functions"][0])
        changed = json.loads(context(analyze(RECORD + "fn forward(p: &P) -> i32 { return p.x; }"), "forward"))
        self.assertNotEqual(packet["cache_key"], changed["cache_key"])

    def test_borrow_formatting_preserves_every_comment_boundary_and_lowering(self):
        source = RECORD + "fn f(p:&mut P)->i32{p.x=p.x+1;return p.x;} fn main()->i32{let mut p=P{x:1};return f(&mut p);}"
        baseline = emit_c(analyze(source))
        tokens = [t.text for t in lex(source) if t.kind != "eof"]
        for index in range(len(tokens) + 1):
            with self.subTest(boundary=index):
                variant = " ".join(tokens[:index]) + " // retained\n" + " ".join(tokens[index:])
                formatted = format_source(variant)
                self.assertEqual(formatted, format_source(formatted))
                self.assertEqual(baseline, emit_c(analyze(formatted)))
                self.assertEqual([(t.kind, t.text) for t in lex(variant)], [(t.kind, t.text) for t in lex(formatted)])

    def test_invalid_nested_borrow_tokens_never_merge_into_logical_and(self):
        source = RECORD + "fn f(p: P) -> i32 { return read(& &p); }"
        formatted = format_source(source)
        self.assertIn("& &p", formatted)
        self.assertEqual([(t.kind, t.text) for t in lex(source)], [(t.kind, t.text) for t in lex(formatted)])
