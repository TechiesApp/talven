"""Shared differential conformance corpus for the reference and native compilers.

Every case runs both CLIs and compares ok/failure, diagnostic code, message and range.
Programs both compilers accept are emitted with and without --console; the emitted C
must be byte-identical, and each C output is compiled and executed. Generated programs
also carry an independent Python oracle for exit status and stdout.

The only accepted divergences are listed in EXPECTED_DIVERGENCES (fixed cases) or follow
the documented rule: a program which the reference parses successfully, which declares a
struct, and which uses borrowing or mutation (a borrowed parameter type, a borrow
expression, `let mut`, or a field assignment) receives native E0801. Every other program,
including by-value record programs, must match exactly. No provider calls.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from talven.frontend import CompileError, Expr, MAX_SOURCE_BYTES, Program, analyze, parse

BINARY = Path(os.environ.get("TALVEN_NATIVE", ROOT / "experiments/native-compiler/target/release/talven-native")).resolve()
REFERENCE = [sys.executable, "-B", "-m", "talven"]
SEED = 20260924
GENERATED_PROGRAMS = 160
MUTATIONS = 260
CC = ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic-errors", "-Werror"]

# Fixed cases whose native result is documented to differ: case -> expected native code.
# "E0901-message" means the code matches but the host decoder's error text differs.
EXPECTED_DIVERGENCES = {
    "examples/borrowing.tal": "E0801",
    "examples/invalid/borrow-conflict.tal": "E0801",
    "tests/fixtures/borrowing-order.tal": "E0801",
    "tests/fixtures/borrowing-reborrow.tal": "E0801",
    "experiments/corpora/borrowing-v1/order.tal": "E0801",
    "experiments/corpora/borrowing-v1/overlap.tal": "E0801",
    "experiments/corpora/borrowing-v1/permission.tal": "E0801",
    "experiments/corpora/borrowing-v1/reborrow.tal": "E0801",
    "edge/record-borrow-param": "E0801",
    "edge/record-borrow-mut-param": "E0801",
    "edge/record-borrow-scalar-param": "E0801",
    "edge/record-borrow-argument": "E0801",
    "edge/record-borrow-let": "E0801",
    "edge/record-let-mut": "E0801",
    "edge/record-let-mut-scalar": "E0801",
    "edge/record-field-assign": "E0801",
    "edge/record-borrow-before-error": "E0801",
    "edge/invalid-utf8": "E0901-message",
}


def uses_borrow_or_mutation(program: Program) -> bool:
    """A borrowed parameter type, a borrow expression, `let mut`, or a field assignment."""
    if any(typ.text.startswith("&") for fn in program.functions for _, typ in fn.params):
        return True
    pending = [stmt for fn in program.functions for stmt in fn.body]
    while pending:
        node = pending.pop()
        if isinstance(node, Expr):
            if node.kind == "borrow":
                return True
            pending.extend([*node.args, *(child for _, child in node.fields)])
            continue
        if node.mutable or node.kind == "assign":
            return True
        pending.extend([node.expr, *node.then, *node.otherwise])
    return False


def rule_divergence(source: bytes):
    """The documented rule: reference-parseable struct programs that borrow or mutate get E0801."""
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return "E0901-message"
    if len(source) > MAX_SOURCE_BYTES:
        return None
    try:
        program = parse(text)
    except CompileError:
        return None
    return "E0801" if program.records and uses_borrow_or_mutation(program) else None


def fn(body: str, result: str = "i32", params: str = "") -> str:
    return f"fn f({params}) -> {result} {{ {body} }}"


def edge_cases():
    unary = lambda n: fn("return " + "-" * n + "1;")
    ifs = lambda n: fn("if (true) { " * n + "}" * n + " return 0;")
    parens = lambda n: fn("return " + "(" * n + "1" + ")" * n + ";")
    cases = {
        "edge/empty": "",
        "edge/crlf": "fn main() -> i32 {\r\n    return 0;\r\n}\r\n",
        "edge/lone-cr": "fn main() -> i32 {\r    return 0;\n}\n",
        "edge/cr-cr-lf": "fn main() -> i32 {\r\r\n return 0; }",
        "edge/comment-lone-cr": "// hidden\rfn main() -> i32 { return 0; }",
        "edge/comment-crlf": "// note\r\nfn main() -> i32 { return 0; }",
        "edge/cr-in-text": 'fn main() -> i32 { return print("a\rb"); }',
        "edge/bidi-in-text": 'fn main() -> i32 { return print("\u202e"); }',
        "edge/bidi-isolate-comment": "// \u2066x\u2069\nfn main() -> i32 { return 0; }",
        "edge/bidi-after-error": "fn main() -> i32 { return @; } // \u202a",
        "edge/nbsp": "fn\u00a0main() -> i32 { return 0; }",
        "edge/line-separator": "fn main() -> i32 {\u2028return 0; }",
        "edge/form-feed": "fn main() -> i32 {\x0creturn 0; }",
        "edge/file-separator": "fn main() -> i32 {\x1creturn 0; }",
        "edge/unit-separator": "fn main() -> i32 {\x1freturn 0; }",
        "edge/nel": "fn main() -> i32 {\u0085return 0; }",
        "edge/vertical-tab": "fn main() -> i32 {\x0breturn 0; }",
        "edge/emoji-range": "// \U0001f642\nfn f() -> i32 { \"\U0001f642\"; return missing; }",
        "edge/unicode-identifier": "fn caf\u00e9() -> i32 { return 0; }",
        "edge/chain-eq": fn("return 1 == 1 == true;", "bool"),
        "edge/chain-lt": fn("return a < 1 < 2;", "bool", "a: i32"),
        "edge/chain-mixed-level": fn("return a == 1 < 2;", "bool", "a: bool"),
        "edge/chain-ge-le": fn("return a >= 1 <= 2;", "bool", "a: i32"),
        "edge/chain-ne-in-and": fn("return true && a != 1 != false;", "bool", "a: i32"),
        "edge/chain-parenthesized": fn("return (a < 1) == (2 < a);", "bool", "a: i32"),
        "edge/let-mut-scalar": fn("let mut x = 1; return x;"),
        "edge/let-mut-annotated": fn("let mut x: i32 = 1; return x;"),
        "edge/let-mut-bad-value": fn("let mut x = missing; return 0;"),
        "edge/borrow-param": "fn f(x: &i32) -> i32 { return 0; }",
        "edge/borrow-mut-unknown": "fn f(x: &mut Unknown) -> i32 { return 0; }",
        "edge/borrow-result": "fn f() -> &i32 { return 0; }",
        "edge/borrow-let-annotation": fn("let x: &i32 = 1; return 0;"),
        "edge/borrow-expression": fn("let y = &x; return 0;", params="x: i32"),
        "edge/borrow-call-name": "fn g(x: i32) -> i32 { return x; } " + fn("return g(&x);", params="x: i32"),
        "edge/borrow-call-temp": "fn g(x: i32) -> i32 { return x; } " + fn("return g(&mut 1);"),
        "edge/borrow-call-unknown": "fn g(x: i32) -> i32 { return x; } " + fn("return g(&y);"),
        "edge/borrow-print": fn("return print(&x);", params="x: str"),
        "edge/field-read": fn("return x.value;", params="x: i32"),
        "edge/field-unknown-base": fn("return y.value;"),
        "edge/field-assign": fn("x.value = 1; return 0;", params="x: i32"),
        "edge/field-assign-call": fn("g().value = 1; return 0;") + " fn g() -> i32 { return 0; }",
        "edge/record-literal": fn("return Point { x: 1 };"),
        "edge/unknown-type": "fn f(x: Point) -> i32 { return 0; }",
        "edge/unknown-result-type": "fn f() -> u8 { return 0; }",
        "edge/unknown-annotation": fn("let x: u8 = 1; return 0;"),
        "edge/assign-to-name": fn("x = 1; return 0;", params="x: i32"),
        "edge/struct-only": "struct A { x: i32 }",
        "edge/struct-after-function": "fn main() -> i32 { return 0; }\nstruct A { x: i32 }",
        "edge/struct-parse-error": "struct A { x i32 }",
        "edge/struct-deep-tree": "struct A { x: i32 } " + unary(200),
        "edge/parens-127": parens(127),
        "edge/parens-254": parens(254),
        "edge/parens-255": parens(255),
        "edge/parens-500": parens(500),
        "edge/parens-2000": parens(2000),
        "edge/if-300": ifs(300),
        "edge/unary-126": unary(126),
        "edge/unary-127": unary(127),
        "edge/unary-128": unary(128),
        "edge/if-126": ifs(126),
        "edge/if-127": ifs(127),
        "edge/if-128": ifs(128),
        "edge/if-2000": ifs(2000),
        "edge/plus-chain-127": fn("return " + "+".join(["1"] * 127) + ";"),
        "edge/plus-chain-128": fn("return " + "+".join(["1"] * 128) + ";"),
        "edge/plus-chain-10000": fn("return " + "+".join(["1"] * 10000) + ";"),
        "edge/call-chain-deep": "fn g(x: i32) -> i32 { return x; } " + fn("return " + "g(" * 140 + "1" + ")" * 140 + ";"),
        "edge/token-limit": fn("return " + "+".join(["1"] * 9000) + ";"),
        "edge/size-limit": " " * (MAX_SOURCE_BYTES + 1),
        "edge/int-limits": "fn main() -> i32 { return -0002147483648 + 2147483647 + 0; }",
        "edge/int-too-large": fn("return 2147483648;"),
        "edge/int-many-digits": fn("return 00000000000000000001;"),
        "edge/int-eleven-digits": fn("return 10000000000;"),
        "edge/text-escapes": 'fn main() -> i32 { return print("\\"\\\\\\n\\r\\t\\0\u00e9\U0001f642"); }',
        "edge/text-empty": 'fn main() -> i32 { return print(""); }',
        "edge/text-bad-escape": fn('return print("\\q");'),
        "edge/text-bad-unicode-escape": fn('return print("\\\u00e9");'),
        "edge/text-unterminated": fn('return print("abc'),
        "edge/text-trailing-backslash": 'fn f() -> str { return "\\',
        "edge/text-del": 'fn f() -> str { return "\x7f"; }',
        "edge/text-long": 'fn main() -> i32 { return print("' + "x" * 40 + '"); }',
        "edge/print-in-uncalled": 'fn quiet() -> i32 { return print("x"); } fn main() -> i32 { return 0; }',
        "edge/print-arity": fn("return print();"),
        "edge/print-type": fn("return print(3);"),
        "edge/print-declared": "fn print() -> i32 { return 0; }",
        "edge/reserved-i32": "fn i32() -> i32 { return 0; }",
        "edge/duplicate-fn": "fn f() -> i32 { return 0; } fn f() -> i32 { return 1; }",
        "edge/duplicate-param": "fn f(x: i32, x: bool) -> i32 { return 0; }",
        "edge/shadow": fn("let x = 1; return x;", params="x: i32"),
        "edge/unreachable": fn("return 0; return 1;"),
        "edge/missing-return": fn("let x = 0;"),
        "edge/if-missing-else-return": fn("if (true) { return 1; }"),
        "edge/if-both-return": fn("if (true) { return 1; } else { return 2; }"),
        "edge/after-if-both-return": fn("if (true) { return 1; } else { return 2; } return 3;"),
        "edge/if-condition-type": fn("if (1) { return 0; } return 1;"),
        "edge/if-scope": fn("if (true) { let y = 1; } return y;"),
        "edge/text-equality": fn('return "a" == "b";', "bool"),
        "edge/bool-arith": fn("return true + 1;"),
        "edge/not-int": fn("return !1;", "bool"),
        "edge/neg-bool": fn("return -true;"),
        "edge/unknown-function": fn("return nope();"),
        "edge/arity": "fn g(x: i32) -> i32 { return x; } " + fn("return g(1, 2);"),
        "edge/argument-type": "fn g(x: i32) -> i32 { return x; } " + fn("return g(true);"),
        "edge/trailing-comma": "fn g(x: i32,) -> i32 { return x; } fn main() -> i32 { return g(4,); }",
        "edge/missing-semicolon": fn("return 0"),
        "edge/eof-in-block": "fn f() -> i32 { return 0;",
        "edge/stray-token": "let x = 1;",
        "edge/keyword-name": "fn let() -> i32 { return 0; }",
        "edge/andand-prefix": fn("return &&x;", params="x: i32"),
        "edge/main-bool": "fn main() -> bool { return true; }",
        "edge/main-param": "fn main(x: i32) -> i32 { return x; }",
        "edge/no-main": "fn g() -> i32 { return 0; }",
        "edge/recursion": "fn main() -> i32 { return later(4); } fn later(x: i32) -> i32 { if (x == 0) { return 0; } else { return later(x - 1); } }",
        "edge/short-circuit-order": 'fn mark(s: str) -> i32 { return print(s); }\nfn bomb() -> bool { return (1 / 0) == 0; }\nfn main() -> i32 {\n    if (false && bomb()) { return 9; }\n    if (true || bomb()) { return mark("a") + mark("b"); }\n    return 8;\n}\n',
        "edge/overflow-trap": "fn main() -> i32 { return 2147483647 + 1; }",
        "edge/division-trap": "fn main() -> i32 { return -2147483648 / -1; }",
        "edge/remainder": "fn main() -> i32 { return (-7 % 3) + (7 / -2) + 100; }",
    }
    cases.update(record_cases())
    encoded = {name: source.encode() for name, source in cases.items()}
    encoded["edge/invalid-utf8"] = b"fn main() -> i32 { return 0; } \xff"
    return encoded


def record_cases():
    """By-value records, moves, and the borrow/mutation boundary of the native profile."""
    point = "struct P { x: i32, y: bool }\n"
    take = "fn take(p: P) -> bool { return p.y; }\n"
    make = "fn make(v: i32) -> P { return P { y: v > 0, x: v }; }\n"
    main = lambda body: point + take + make + "fn main() -> i32 { " + body + " }\n"
    nested = lambda n: "struct R { x: i32 }\n" + fn("return " + "R { x: " * n + "1" + " }.x" * n + ";")
    record_parens = lambda n: point + fn("return P { x: " + "(" * n + "1" + ")" * n + ", y: true }.x;")
    return {
        "edge/record-basic": main("let p = P { y: true, x: 3, }; if (p.y) { return p.x; } return 0;"),
        "edge/record-annotated": main("let p: P = make(4); let q: P = p; return q.x;"),
        "edge/record-returned-field": main("return make(5).x + make(-6).x + 50;"),
        "edge/record-literal-field": main("return P { x: 7, y: true }.x + (P { x: 1, y: false }).x;"),
        "edge/record-by-value-args": point + "fn sum(a: P, b: P) -> i32 { return a.x + b.x; }\n"
                                     "fn main() -> i32 { let a = P { x: 2, y: true }; let b = P { x: 3, y: false }; return sum(a, b); }",
        "edge/record-discard-moves": main("let p = make(1); p; return p.x;"),
        "edge/record-discard": main("let p = make(9); p; make(2); return 0;"),
        "edge/record-move-then-use": main("let p = make(1); let q = p; return p.x;"),
        "edge/record-read-then-move": point + "fn both(v: i32, p: P) -> i32 { return v + p.x; }\n"
                                      "fn main() -> i32 { let p = P { x: 4, y: true }; return both(p.x, p); }",
        "edge/record-move-then-read-arg": point + "fn both(p: P, v: i32) -> i32 { return v + p.x; }\n"
                                          "fn main() -> i32 { let p = P { x: 4, y: true }; return both(p, p.x); }",
        "edge/record-move-twice-in-call": point + "fn sum(a: P, b: P) -> i32 { return a.x + b.x; }\n"
                                          "fn main() -> i32 { let p = P { x: 1, y: true }; return sum(p, p); }",
        "edge/record-move-param": point + "fn f(p: P) -> i32 { let q = p; return p.x; }",
        "edge/record-move-returning-branch": main("let p = make(3); if (p.x > 1) { let q = p; return q.x; } return p.x;"),
        "edge/record-move-else-returning": main("let p = make(3); if (p.x > 9) { return 1; } else { let q = p; return q.x; }"),
        "edge/record-move-fallthrough-then": main("let p = make(3); if (true) { let q = p; } return p.x;"),
        "edge/record-move-fallthrough-else": main("let p = make(3); if (false) { return 1; } else { take(p); } return p.x;"),
        "edge/record-move-both-branches": main("let p = make(3); if (true) { take(p); } else { take(p); } return p.x;"),
        "edge/record-move-unused-after": main("let p = make(3); if (true) { take(p); } return 4;"),
        "edge/record-move-nested-branch": main("let p = make(3); if (true) { if (false) { take(p); } } return p.x;"),
        "edge/record-move-branch-local": main("if (true) { let q = make(1); let r = q; } return 0;"),
        "edge/record-move-in-condition": main("let p = make(3); if (take(p)) { return 1; } return p.x;"),
        "edge/record-move-and-right": main("let p = make(3); if (false && take(p)) { return 1; } return p.x;"),
        "edge/record-move-or-right": main("let p = make(3); if (true || take(p)) { return 1; } return p.x;"),
        "edge/record-move-and-left-reuse": main("let p = make(3); if (take(p) && p.y) { return 1; } return 0;"),
        "edge/record-move-or-same-expression": main("let p = make(3); return (take(p) || take(p)) == true;"),
        "edge/record-move-and-ok": main("let p = make(3); let q = make(4); if (take(p) && take(q)) { return 1; } return 0;"),
        "edge/record-move-print-arg": main("let p = make(1); return print(p);"),
        "edge/record-move-equality-self": main("let p = make(1); if (p == p) { return 1; } return 0;"),
        "edge/record-equality": main("let p = make(1); let q = make(1); if (p == q) { return 1; } return 0;"),
        "edge/record-inequality-left-scalar": main("let p = make(1); if (1 != p) { return 1; } return 0;"),
        "edge/record-arith": main("let p = make(1); return p + 1;"),
        "edge/record-negate": main("let p = make(1); return -p;"),
        "edge/record-not": main("let p = make(1); if (!p) { return 1; } return 0;"),
        "edge/record-condition": main("let p = make(1); if (p) { return 1; } return 0;"),
        "edge/record-return-mismatch": point + "fn f() -> P { return 1; }",
        "edge/record-let-mismatch": main("let p: P = 1; return 0;"),
        "edge/record-wrong-record": point + "struct Q { x: i32, y: bool }\nfn f(p: P) -> i32 { return p.x; }\n"
                                    "fn main() -> i32 { return f(Q { x: 1, y: true }); }",
        "edge/record-no-field": main("let p = make(1); return p.z;"),
        "edge/record-field-of-scalar": main("let p = make(1); return p.x.y;"),
        "edge/record-field-of-call-scalar": main("return make(1).x.y;"),
        "edge/record-field-of-text": point + fn('return "t".x;'),
        "edge/record-duplicate-literal-field": main("return P { x: 1, x: 2, y: true }.x;"),
        "edge/record-unknown-literal-field": main("return P { x: 1, z: 2, y: true }.x;"),
        "edge/record-literal-field-type": main("return P { x: true, y: true }.x;"),
        "edge/record-missing-fields": main("return P { }.x;"),
        "edge/record-missing-sorted": "struct Q { b: i32, a: i32, c: bool }\n" + fn("return Q { c: true }.a;"),
        "edge/record-literal-error-order": main("return P { z: missing, x: 1 }.x;"),
        "edge/record-unknown-record": point + fn("return Nope { x: 1 }.x;"),
        "edge/record-literal-of-function": point + "fn g() -> i32 { return 0; }\n" + fn("return g { x: 1 }.x;"),
        "edge/record-call-of-record": point + fn("return P(1);"),
        "edge/record-named-like-function": "struct f { x: i32 }\n" + fn("return 0;"),
        "edge/record-function-before-record": fn("return 0;") + "\nstruct f { x: i32 }",
        "edge/record-duplicate-struct": "struct P { x: i32 }\nstruct P { y: i32 }",
        "edge/record-reserved-i32": "struct i32 { x: i32 }",
        "edge/record-reserved-print": "struct print { x: i32 }",
        "edge/record-empty": "struct E {}",
        "edge/record-empty-after-error-free": "struct A { x: i32 }\nstruct E { }\nfn main() -> i32 { return 0; }",
        "edge/record-duplicate-field": "struct P { x: i32, x: bool }",
        "edge/record-duplicate-then-bad-type": "struct P { x: i32, x: str }",
        "edge/record-str-field": "struct P { x: str }",
        "edge/record-record-field": "struct P { x: i32 }\nstruct Q { p: P }",
        "edge/record-unknown-field-type": "struct P { x: u8 }",
        "edge/record-borrow-field-type": "struct P { x: i32 }\nstruct Q { p: &P }",
        "edge/record-trailing-comma-decl": "struct P { x: i32, y: bool, }\nfn main() -> i32 { return P { x: 2, y: true }.x; }",
        "edge/record-unknown-param-type": point + "fn f(q: Q) -> i32 { return 0; }",
        "edge/record-borrow-result": point + "fn f(p: P) -> &P { return p; }",
        "edge/record-borrow-annotation": main("let p = make(1); let q: &P = p; return 0;"),
        "edge/record-shadow-record-name": main("let P = 4; return P + P { x: 1, y: true }.x;"),
        "edge/record-main-returns-record": point + "fn main() -> P { return P { x: 0, y: true }; }",
        "edge/record-evaluation-order": point + 'fn mark(s: str) -> i32 { return print(s); }\n'
                                        'fn main() -> i32 { let p = P { y: mark("b") == 0, x: mark("a") + 3 }; '
                                        'return p.x + P { x: mark("c"), y: true }.x; }',
        "edge/record-field-trap": main("return P { x: 2147483647 + 1, y: true }.x;"),
        "edge/record-trap-order": point + 'fn main() -> i32 { return P { y: print("before") == 0, x: 1 / 0 }.x; }',
        "edge/record-two-structs-same-field": "struct A { v: i32 }\nstruct B { v: bool }\n"
                                              "fn main() -> i32 { if (B { v: true }.v) { return A { v: 6 }.v; } return 1; }",
        "edge/record-recursive": point + "fn count(p: P) -> P { if (p.x == 0) { return p; } return count(P { x: p.x - 1, y: !p.y }); }\n"
                                 "fn main() -> i32 { let r = count(P { x: 5, y: true }); if (r.y) { return 1; } return 2; }",
        "edge/record-forward-use": "fn main() -> i32 { return later().x; }\nfn later() -> Late { return Late { x: 8 }; }\nstruct Late { x: i32 }",
        "edge/record-missing-return": point + "fn f(p: P) -> P { if (p.y) { return p; } }",
        "edge/record-nested-60": nested(60),
        "edge/record-nested-63": nested(63),
        "edge/record-nested-64": nested(64),
        "edge/record-nested-70": nested(70),
        "edge/record-parens-253": record_parens(253),
        "edge/record-parens-254": record_parens(254),
        # Borrowing and mutation in a struct program: the native profile's documented E0801.
        "edge/record-borrow-param": point + "fn r(p: &P) -> i32 { return p.x; }",
        "edge/record-borrow-mut-param": point + "fn r(p: &mut P) -> i32 { return p.x; }",
        "edge/record-borrow-scalar-param": point + "fn r(x: &i32) -> i32 { return 0; }",
        "edge/record-borrow-argument": main("let p = make(1); return take(&p) == true;"),
        "edge/record-borrow-let": main("let p = make(1); let q = &p; return 0;"),
        "edge/record-let-mut": main("let mut p = make(1); return p.x;"),
        "edge/record-let-mut-scalar": main("let mut x = 1; return x;"),
        "edge/record-field-assign": main("let p = make(1); p.x = 2; return p.x;"),
        "edge/record-borrow-before-error": point + "fn f() -> i32 { return 0; } fn f() -> i32 { return take(&p); }",
    }


def fixed_cases():
    paths = sorted({*ROOT.glob("examples/*.tal"), *ROOT.glob("examples/invalid/*.tal"),
                    *ROOT.glob("tests/fixtures/*.tal"), *ROOT.glob("experiments/corpora/*/*.tal")})
    cases = {str(path.relative_to(ROOT)): path.read_bytes() for path in paths}
    cases.update(edge_cases())
    return cases


class Trap(Exception):
    pass


class Oracle:
    """Direct Talven scalar and record semantics over the reference AST; no C involved."""

    def __init__(self, source: str):
        self.functions = {f.name.text: f for f in analyze(source).program.functions}
        self.stdout = bytearray()

    def call(self, name, args):
        fn = self.functions[name]
        env = {param.text: value for (param, _), value in zip(fn.params, args)}
        return self.block(fn.body, env)[1]

    def block(self, statements, env):
        for stmt in statements:
            value = self.evaluate(stmt.expr, env)
            if stmt.kind == "let":
                env[stmt.name.text] = value
            elif stmt.kind == "return":
                return True, value
            elif stmt.kind == "if":
                done, result = self.block(stmt.then if value else stmt.otherwise, dict(env))
                if done:
                    return True, result
        return False, None

    @staticmethod
    def narrow(value):
        if not -2**31 <= value < 2**31:
            raise Trap
        return value

    def evaluate(self, expr: Expr, env):
        kind, value = expr.kind, expr.value
        if kind == "int":
            return int(value)
        if kind == "bool":
            return value == "true"
        if kind == "text":
            return value
        if kind == "name":
            return env[value]
        if kind == "record":
            # Records are immutable here, so a dictionary models the moved value exactly.
            return {name.text: self.evaluate(child, env) for name, child in expr.fields}
        if kind == "field":
            return self.evaluate(expr.args[0], env)[value]
        if kind == "call":
            args = [self.evaluate(child, env) for child in expr.args]
            if value == "print":
                self.stdout += args[0].encode()
                return 0
            return self.call(value, args)
        if kind == "unary":
            child = expr.args[0]
            if value == "-" and child.kind == "int" and int(child.value) == 2**31:
                return -2**31
            operand = self.evaluate(child, env)
            return self.narrow(-operand) if value == "-" else not operand
        left = self.evaluate(expr.args[0], env)
        if value in ("&&", "||"):
            if left == (value == "||"):
                return left
            return self.evaluate(expr.args[1], env)
        right = self.evaluate(expr.args[1], env)
        if value in ("/", "%"):
            if right == 0 or (left == -2**31 and right == -1):
                raise Trap
            quotient = abs(left) // abs(right) * (1 if (left < 0) == (right < 0) else -1)
            return quotient if value == "/" else left - quotient * right
        operations = {"+": lambda: self.narrow(left + right), "-": lambda: self.narrow(left - right),
                      "*": lambda: self.narrow(left * right), "==": lambda: left == right,
                      "!=": lambda: left != right, "<": lambda: left < right, ">": lambda: left > right,
                      "<=": lambda: left <= right, ">=": lambda: left >= right}
        return operations[value]()

    def run(self):
        """Expected (returncode, stdout) of the hosted executable."""
        try:
            status = self.call("main", []) & 0xFF
        except Trap:
            status = -signal.SIGABRT
        return status, bytes(self.stdout)


TEXTS = ["", "a", "h\u00e9\U0001f642", "line\\n", "tab\\t", "nul\\0end", "quote\\\"", "slash\\\\", "Hello, world!\\n"]
PRECEDENCE = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, ">": 4, "<=": 4, ">=": 4,
              "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


MOVED = "moved"


class ProgramGenerator:
    """Deterministic well-typed programs over scalars, text, and by-value records.

    Calls only reach earlier functions. A record binding is marked MOVED as soon as an
    expression consumes it, in evaluation order, so later code never uses it again; a field
    read does not move. Every generated branch returns, so a move inside a branch never
    affects the code after the if statement.
    """

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.signatures = []
        self.records = {}

    def types(self):
        return ["i32", "i32", "bool", *self.records]

    def record(self, typ, env, depth):
        """A record literal with every field once, in any order, sometimes with a trailing comma."""
        fields = list(self.records[typ].items())
        self.rng.shuffle(fields)
        inits = [f"{name}: {self.expr(t, env, depth - 1)[0]}" for name, t in fields]
        return f"{typ} {{ {', '.join(inits)}{',' if self.rng.random() < 0.3 else ''} }}", 9

    def record_value(self, typ, env, depth):
        rng = self.rng
        names = [name for name, t in env.items() if t == typ]
        calls = [s for s in self.signatures if s[2] == typ]
        if names and rng.random() < 0.5:
            name = rng.choice(names)
            env[name] = MOVED
            return name, 9
        if calls and depth > 0 and rng.random() < 0.4:
            name, params, _ = rng.choice(calls)
            return f"{name}({', '.join(self.expr(t, env, depth - 1)[0] for t in params)})", 9
        return self.record(typ, env, depth)

    def field_read(self, typ, env, depth):
        """Read a scalar field of a named record, a call result, or a record literal."""
        rng = self.rng
        owners = [(record, field) for record, fields in self.records.items()
                  for field, t in fields.items() if t == typ]
        if not owners:
            return None
        record, field = rng.choice(owners)
        names = [name for name, t in env.items() if t == record]
        if names and (depth <= 0 or rng.random() < 0.6):
            return f"{rng.choice(names)}.{field}", 9
        if depth <= 0:
            return None
        base, _ = self.record_value(record, env, depth - 1) if rng.random() < 0.6 else self.record(record, env, depth - 1)
        return f"{base}.{field}", 9

    def literal(self):
        rng = self.rng
        return rng.choice([str(rng.randrange(0, 60)), str(rng.randrange(0, 60)), "0", "2147483647",
                           "0007", str(rng.randrange(1000, 70000))])

    def wrap(self, text, precedence, parent, right):
        """Parenthesize when required, and sometimes when not."""
        needed = precedence < parent or (right and precedence <= parent) or \
            (precedence == parent and parent in (3, 4))
        return f"({text})" if needed or self.rng.random() < 0.25 else text

    def expr(self, typ, env, depth):
        """Return (source, precedence) for an expression of type typ."""
        rng = self.rng
        if typ in self.records:
            return self.record_value(typ, env, depth)
        names = [name for name, t in env.items() if t == typ]
        calls = [s for s in self.signatures if s[2] == typ]
        if self.records and rng.random() < 0.12:
            read = self.field_read(typ, env, depth)
            if read:
                return read
        if depth <= 0 or rng.random() < 0.25:
            if typ == "i32":
                if names and rng.random() < 0.5:
                    return rng.choice(names), 9
                return (("-2147483648", 7) if rng.random() < 0.03 else (self.literal(), 9))
            if names and rng.random() < 0.5:
                return rng.choice(names), 9
            return rng.choice(["true", "false"]), 9
        roll = rng.random()
        if calls and roll < 0.15:
            name, params, _ = rng.choice(calls)
            args = [self.expr(t, env, depth - 1)[0] for t in params]
            return f"{name}({', '.join(args)})", 9
        if typ == "i32":
            if roll < 0.22:
                return f'print("{rng.choice(TEXTS)}")', 9
            if roll < 0.32:
                child, precedence = self.expr("i32", env, depth - 1)
                return "-" + (child if precedence >= 7 and not child.startswith("-") else f"({child})"), 7
            op = rng.choice(["+", "-", "*", "/", "%", "+", "-"])
        else:
            if roll < 0.28:
                child, precedence = self.expr("bool", env, depth - 1)
                return "!" + (child if precedence >= 7 else f"({child})"), 7
            op = rng.choice(["&&", "||", "==", "!=", "<", ">", "<=", ">="])
        operand = "bool" if op in ("&&", "||") or (op in ("==", "!=") and rng.random() < 0.4) else "i32"
        parent = PRECEDENCE[op]
        left, lp = self.expr(operand, env, depth - 1)
        right, rp = self.expr(operand, env, depth - 1)
        return f"{self.wrap(left, lp, parent, False)} {op} {self.wrap(right, rp, parent, True)}", parent

    def body(self, result, env, depth, indent):
        rng = self.rng
        pad = "    " * indent
        lines = []
        for _ in range(rng.randrange(0, 4)):
            roll = rng.random()
            if roll < 0.45:
                typ = rng.choice(self.types())
                name = f"v{len(env)}"
                annotation = f": {typ}" if rng.random() < 0.3 else ""
                lines.append(f"{pad}let {name}{annotation} = {self.expr(typ, env, 3)[0]};")
                env[name] = typ
            elif roll < 0.65:
                lines.append(f'{pad}print("{rng.choice(TEXTS)}");')
            elif roll < 0.8:
                # Discarding a record moves it.
                lines.append(f"{pad}{self.expr(rng.choice(self.types()), env, 2)[0]};")
            elif depth > 0:
                condition = self.expr("bool", env, 2)[0]
                then = self.body(result, dict(env), depth - 1, indent + 1)
                lines.append(f"{pad}if ({condition}) {{")
                lines.extend(then)
                if rng.random() < 0.6:
                    # Both branches return, so the if statement ends this block.
                    lines.append(f"{pad}}} else {{")
                    lines.extend(self.body(result, dict(env), depth - 1, indent + 1))
                    lines.append(f"{pad}}}")
                    return lines
                lines.append(f"{pad}}}")
        lines.append(f"{pad}return {self.expr(result, env, 3)[0]};")
        return lines

    def program(self):
        rng = self.rng
        self.signatures = []
        self.records = {}
        declarations = []
        for index in range(rng.choice([0, 0, 1, 1, 2])):
            fields = {name: rng.choice(["i32", "bool"]) for name in rng.sample(["a", "b", "c", "x"], rng.randrange(1, 4))}
            self.records[f"R{index}"] = fields
            declarations.append(f"struct R{index} {{\n" + ",\n".join(f"    {n}: {t}" for n, t in fields.items()) +
                                ("," if rng.random() < 0.3 else "") + "\n}\n")
        functions = []
        for index in range(rng.randrange(0, 4)):
            params = [rng.choice(self.types()) for _ in range(rng.randrange(0, 4))]
            result = rng.choice(["i32", "bool", *self.records])
            env = {f"p{i}": t for i, t in enumerate(params)}
            header = ", ".join(f"p{i}: {t}" for i, t in enumerate(params))
            functions.append(f"fn g{index}({header}) -> {result} {{\n" +
                             "\n".join(self.body(result, env, 2, 1)) + "\n}\n")
            self.signatures.append((f"g{index}", params, result))
        functions.append("fn main() -> i32 {\n" + "\n".join(self.body("i32", {}, 2, 1)) + "\n}\n")
        if rng.random() < 0.5:
            functions.reverse()  # forward calls are valid
        items = [*declarations, *functions]
        if declarations and rng.random() < 0.5:
            items = [*functions, *declarations]  # records may be used before their declaration
        return "\n".join(items)


VOCABULARY = ["fn", "let", "mut", "return", "if", "else", "true", "false", "struct", "print",
              "(", ")", "{", "}", ";", ":", ",", ".", "&", "&&", "||", "=", "==", "!=", "<", "<=",
              ">", ">=", "+", "-", "*", "/", "%", "!", "->", "i32", "bool", "str", "x", "main",
              "0", "2147483648", "99999999999", '"t"', '"', '"\\q"', "\r", "\u00a0", "\u202e",
              "@", "#", "//", "\x0c", "\\", "\u00e9"]


def mutate(rng: random.Random, source: str) -> str:
    import re
    tokens = re.findall(r'"(?:[^"\\\n]|\\.)*"|//[^\n]*|\s+|[A-Za-z_0-9]+|->|==|!=|<=|>=|&&|\|\||.', source)
    for _ in range(rng.choice([1, 1, 1, 2, 3])):
        if not tokens:
            tokens = [rng.choice(VOCABULARY)]
            continue
        at = rng.randrange(len(tokens))
        operation = rng.choice(["delete", "insert", "replace", "duplicate", "swap"])
        if operation == "delete":
            del tokens[at]
        elif operation == "insert":
            tokens.insert(at, rng.choice(VOCABULARY))
        elif operation == "replace":
            tokens[at] = rng.choice(VOCABULARY)
        elif operation == "duplicate":
            tokens.insert(at, tokens[at])
        elif at + 1 < len(tokens):
            tokens[at], tokens[at + 1] = tokens[at + 1], tokens[at]
    return "".join(tokens)


def generated_cases():
    rng = random.Random(SEED)
    generator = ProgramGenerator(rng)
    programs = {f"generated/program-{i:03}": generator.program() for i in range(GENERATED_PROGRAMS)}
    seeds = [*programs.values(), *(s.decode() for n, s in fixed_cases().items()
                                   if n.startswith("examples/") or n.startswith("edge/recursion"))]
    mutations = {f"generated/mutation-{i:03}": mutate(rng, rng.choice(seeds)) for i in range(MUTATIONS)}
    return ({name: source.encode() for name, source in programs.items()},
            {name: source.encode() for name, source in mutations.items()})


def run(argv, timeout=30):
    return subprocess.run(argv, capture_output=True, timeout=timeout)


def diagnostic_view(stdout):
    receipt = json.loads(stdout)
    return receipt["ok"], [(d["code"], d["message"], d["severity"], d["range"]) for d in receipt["diagnostics"]]


class DifferentialCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.fixed = fixed_cases()
        cls.programs, cls.mutations = generated_cases()
        cls.cases = {**cls.fixed, **cls.programs, **cls.mutations}
        cls.paths = {}
        for index, (name, source) in enumerate(cls.cases.items()):
            path = cls.root / f"case-{index:04}.tal"
            path.write_bytes(source)
            cls.paths[name] = path
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
            cls.checks = dict(zip(cls.cases, pool.map(cls.check_both, cls.cases)))
            accepted = [n for n, (reference, native, _) in cls.checks.items() if reference.returncode == 0 == native.returncode]
            cls.emits = dict(zip(accepted, pool.map(cls.emit_both, accepted)))
            runnable = [n for n, results in cls.emits.items() if results[True][0].returncode == 0]
            cls.runs = dict(zip(runnable, pool.map(cls.execute_both, runnable)))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @classmethod
    def check_both(cls, name):
        path = str(cls.paths[name])
        return (run([*REFERENCE, "check", path, "--json"]), run([str(BINARY), "check", path, "--json"]),
                EXPECTED_DIVERGENCES.get(name) if name in cls.fixed else rule_divergence(cls.cases[name]))

    @classmethod
    def emit_both(cls, name):
        path = str(cls.paths[name])
        return {console: (run([*REFERENCE, "emit-c", path, *(["--console"] if console else [])]),
                          run([str(BINARY), "emit-c", path, *(["--console"] if console else [])]))
                for console in (False, True)}

    @classmethod
    def execute_both(cls, name):
        results = []
        for label, emitted in zip(("reference", "native"), cls.emits[name][True]):
            cfile = cls.root / f"{cls.paths[name].stem}-{label}.c"
            executable = cls.root / f"{cls.paths[name].stem}-{label}"
            cfile.write_bytes(emitted.stdout)
            built = run([*CC, str(cfile), "-o", str(executable)], timeout=60)
            if built.returncode:
                results.append(("build failed", built.stderr.decode(errors="replace")))
                continue
            executed = run([str(executable)], timeout=10)
            results.append((executed.returncode, executed.stdout, executed.stderr))
        return results

    def test_corpus_is_nontrivial(self):
        self.assertGreaterEqual(len(self.cases), 500)
        self.assertGreaterEqual(len(self.runs), GENERATED_PROGRAMS)
        failing = sum(not json.loads(reference.stdout)["ok"] for reference, _, _ in self.checks.values())
        self.assertGreaterEqual(failing, 200, "mutations must exercise diagnostics")
        self.assertTrue(all(json.loads(self.checks[n][0].stdout)["ok"] for n in self.programs))

    def test_fixed_allowlist_matches_the_documented_rule(self):
        for name, source in self.fixed.items():
            with self.subTest(case=name):
                self.assertEqual(rule_divergence(source), EXPECTED_DIVERGENCES.get(name))

    def test_diagnostics_agree_except_documented_divergences(self):
        used = set()
        for name, (reference, native, expected) in self.checks.items():
            with self.subTest(case=name):
                self.assertIn(reference.returncode, (0, 1), reference.stderr)
                self.assertIn(native.returncode, (0, 1), native.stderr)
                self.assertEqual(json.loads(native.stdout)["profile"], "native-scalar-text-v1")
                ref_ok, ref_diagnostics = diagnostic_view(reference.stdout)
                nat_ok, nat_diagnostics = diagnostic_view(native.stdout)
                if expected is None:
                    self.assertEqual((ref_ok, ref_diagnostics), (nat_ok, nat_diagnostics))
                    self.assertEqual(reference.returncode, native.returncode)
                    continue
                used.add(expected)
                self.assertFalse(nat_ok)
                if expected == "E0801":
                    self.assertEqual("E0801", nat_diagnostics[0][0])
                else:
                    self.assertEqual(("E0901", "E0901"), (ref_diagnostics[0][0], nat_diagnostics[0][0]))
        self.assertEqual({"E0801", "E0901-message"}, used)

    def test_emitted_c_is_byte_identical_or_fails_identically(self):
        for name, results in self.emits.items():
            for console, (reference, native) in results.items():
                with self.subTest(case=name, console=console):
                    self.assertEqual(reference.returncode, native.returncode, native.stderr)
                    self.assertEqual(reference.stdout, native.stdout)
                    self.assertEqual(reference.stderr, native.stderr)
        codes = {r.stderr.split(b": ")[1] for results in self.emits.values()
                 for r, _ in results.values() if r.returncode}
        self.assertEqual({b"E0401", b"E0404"}, codes)

    def test_executables_agree_with_each_other_and_the_oracle(self):
        for name, (reference, native) in self.runs.items():
            with self.subTest(case=name):
                self.assertNotEqual("build failed", reference[0], reference)
                self.assertEqual(reference, native)
                self.assertEqual(b"", native[2])
                if name in self.programs:
                    expected = Oracle(self.cases[name].decode()).run()
                    self.assertEqual(expected, native[:2])
        outcomes = {native[0] for _, native in self.runs.values()}
        self.assertIn(-signal.SIGABRT, outcomes, "the corpus must exercise checked traps")


if __name__ == "__main__":
    if not BINARY.is_file():
        raise SystemExit(f"Build the native compiler first: {BINARY}")
    unittest.main(verbosity=2)
