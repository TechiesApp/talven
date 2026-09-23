"""Shared differential conformance corpus for the reference and native compilers.

Every case runs both CLIs and compares ok/failure, diagnostic code, message and range.
Programs both compilers accept are emitted with and without --console; the emitted C
must be byte-identical, and each C output is compiled and executed. Generated programs
also carry an independent Python oracle for exit status and stdout.

The only accepted divergences are listed in EXPECTED_DIVERGENCES (fixed cases) or follow
the documented rule that a program which the reference parses successfully and which
declares a struct receives native E0801. Any other difference fails. No provider calls.
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
from talven.frontend import CompileError, Expr, MAX_SOURCE_BYTES, analyze, parse

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
    "examples/vectors.tal": "E0801",
    "examples/invalid/borrow-conflict.tal": "E0801",
    "examples/invalid/moved.tal": "E0801",
    "tests/fixtures/borrowing-order.tal": "E0801",
    "tests/fixtures/borrowing-reborrow.tal": "E0801",
    "experiments/corpora/agent-v2/moved.tal": "E0801",
    "experiments/corpora/agent-v2/vectors.tal": "E0801",
    "experiments/corpora/borrowing-v1/order.tal": "E0801",
    "experiments/corpora/borrowing-v1/overlap.tal": "E0801",
    "experiments/corpora/borrowing-v1/permission.tal": "E0801",
    "experiments/corpora/borrowing-v1/reborrow.tal": "E0801",
    "edge/struct-only": "E0801",
    "edge/struct-after-function": "E0801",
    "edge/invalid-utf8": "E0901-message",
}


def rule_divergence(source: bytes):
    """The documented rule for generated cases: reference-parseable struct programs get E0801."""
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return "E0901-message"
    if len(source) > MAX_SOURCE_BYTES:
        return None
    try:
        return "E0801" if parse(text).records else None
    except CompileError:
        return None


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
    encoded = {name: source.encode() for name, source in cases.items()}
    encoded["edge/invalid-utf8"] = b"fn main() -> i32 { return 0; } \xff"
    return encoded


def fixed_cases():
    paths = sorted({*ROOT.glob("examples/*.tal"), *ROOT.glob("examples/invalid/*.tal"),
                    *ROOT.glob("tests/fixtures/*.tal"), *ROOT.glob("experiments/corpora/*/*.tal")})
    cases = {str(path.relative_to(ROOT)): path.read_bytes() for path in paths}
    cases.update(edge_cases())
    return cases


class Trap(Exception):
    pass


class Oracle:
    """Direct Talven scalar semantics over the reference AST; no C involved."""

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


class ProgramGenerator:
    """Deterministic well-typed scalar programs; calls only reach earlier functions."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.signatures = []

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
        names = [name for name, t in env.items() if t == typ]
        calls = [s for s in self.signatures if s[2] == typ]
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
                typ = rng.choice(["i32", "i32", "bool"])
                name = f"v{len(env)}"
                annotation = f": {typ}" if rng.random() < 0.3 else ""
                lines.append(f"{pad}let {name}{annotation} = {self.expr(typ, env, 3)[0]};")
                env[name] = typ
            elif roll < 0.65:
                lines.append(f'{pad}print("{rng.choice(TEXTS)}");')
            elif roll < 0.8:
                lines.append(f"{pad}{self.expr(rng.choice(['i32', 'bool']), env, 2)[0]};")
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
        functions = []
        for index in range(rng.randrange(0, 4)):
            params = [rng.choice(["i32", "i32", "bool"]) for _ in range(rng.randrange(0, 4))]
            result = rng.choice(["i32", "bool"])
            env = {f"p{i}": t for i, t in enumerate(params)}
            header = ", ".join(f"p{i}: {t}" for i, t in enumerate(params))
            functions.append(f"fn g{index}({header}) -> {result} {{\n" +
                             "\n".join(self.body(result, env, 2, 1)) + "\n}\n")
            self.signatures.append((f"g{index}", params, result))
        functions.append("fn main() -> i32 {\n" + "\n".join(self.body("i32", {}, 2, 1)) + "\n}\n")
        if rng.random() < 0.5:
            functions.reverse()  # forward calls are valid
        return "\n".join(functions)


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
