"""One parser and semantic checker shared by the CLI, context API, and LSP.

The prototype deliberately stops at the first diagnostic. Records contain only
scalars and are affine values: they may be moved once or discarded, with no
user-defined destructor, heap allocation, reference, or foreign resource.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

MAX_SOURCE_BYTES = 256 * 1024
MAX_TOKENS = 16384
MAX_AST_DEPTH = 128
SCALARS = {"i32", "bool"}
KEYWORDS = {"fn", "struct", "let", "return", "if", "else", "true", "false"}


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def position(source: str, offset: int) -> dict:
    """LSP-compatible zero-based line and UTF-16 code-unit character."""
    prefix = source[:offset]
    return {"line": prefix.count("\n"),
            "character": len(prefix.rsplit("\n", 1)[-1].encode("utf-16-le")) // 2}


def source_range(source: str, span: Span) -> dict:
    return {"start": position(source, span.start), "end": position(source, span.end)}


class CompileError(Exception):
    def __init__(self, code: str, message: str, span: Span):
        super().__init__(message)
        self.code, self.message, self.span = code, message, span

    def diagnostic(self, source: str) -> dict:
        return {"code": self.code, "message": self.message, "severity": 1,
                "source": "talven", "range": source_range(source, self.span)}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    span: Span


def lex(source: str) -> list[Token]:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise CompileError("E0005", "Source exceeds the 256 KiB prototype limit", Span(0, 0))
    pattern = re.compile(r"(?P<skip>\s+|//[^\n]*)|(?P<int>[0-9]+)|"
                         r"(?P<id>[A-Za-z_][A-Za-z_0-9]*)|"
                         r"(?P<op>->|==|!=|<=|>=|&&|\|\||[{}():;,.+*/%<>=!\-])")
    tokens = []
    offset = 0
    while offset < len(source):
        match = pattern.match(source, offset)
        if not match:
            raise CompileError("E0001", "Unexpected character", Span(offset, offset + 1))
        if match.lastgroup != "skip":
            text = match.group()
            kind = match.lastgroup if match.lastgroup != "op" else text
            if kind == "id" and text in KEYWORDS:
                kind = text
            tokens.append(Token(kind, text, Span(offset, match.end())))
            if len(tokens) > MAX_TOKENS:
                raise CompileError("E0005", "Source exceeds the prototype token limit", Span(offset, match.end()))
        offset = match.end()
    tokens.append(Token("eof", "", Span(offset, offset)))
    return tokens


@dataclass
class Expr:
    kind: str
    span: Span
    value: str = ""
    args: list[Expr] = field(default_factory=list)
    fields: list[tuple[Token, Expr]] = field(default_factory=list)
    typ: str = ""


@dataclass
class Statement:
    kind: str
    span: Span
    expr: Expr
    name: Token | None = None
    annotation: Token | None = None
    then: list[Statement] = field(default_factory=list)
    otherwise: list[Statement] = field(default_factory=list)


@dataclass
class Record:
    name: Token
    fields: list[tuple[Token, Token]]
    span: Span


@dataclass
class Function:
    name: Token
    params: list[tuple[Token, Token]]
    result: Token
    body: list[Statement]
    span: Span
    calls: set[str] = field(default_factory=set)

    def signature(self) -> str:
        args = ", ".join(f"{n.text}: {t.text}" for n, t in self.params)
        return f"fn {self.name.text}({args}) -> {self.result.text}"


@dataclass
class Program:
    records: list[Record]
    functions: list[Function]


class Parser:
    PRECEDENCE = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, ">": 4,
                  "<=": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}

    def __init__(self, tokens: list[Token]):
        self.tokens, self.index = tokens, 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self, kind: str) -> Token:
        token = self.current
        if token.kind != kind:
            raise CompileError("E0002", f"Expected {kind}, found {token.text or 'end of file'}", token.span)
        self.index += 1
        return token

    def accept(self, kind: str) -> bool:
        if self.current.kind == kind:
            self.index += 1
            return True
        return False

    def pairs(self, end: str) -> list[tuple[Token, Token]]:
        result = []
        while self.current.kind != end:
            name = self.take("id")
            self.take(":")
            result.append((name, self.take("id")))
            if not self.accept(","):
                break
        self.take(end)
        return result

    def program(self) -> Program:
        records, functions = [], []
        while self.current.kind != "eof":
            start = self.current.span.start
            if self.accept("struct"):
                name = self.take("id")
                self.take("{")
                fields = self.pairs("}")
                records.append(Record(name, fields, Span(start, self.tokens[self.index - 1].span.end)))
            else:
                self.take("fn")
                name = self.take("id")
                self.take("(")
                params = self.pairs(")")
                self.take("->")
                result = self.take("id")
                body = self.block()
                functions.append(Function(name, params, result, body,
                                          Span(start, self.tokens[self.index - 1].span.end)))
        return Program(records, functions)

    def block(self) -> list[Statement]:
        self.take("{")
        statements = []
        while self.current.kind != "}":
            start = self.current.span.start
            if self.accept("let"):
                name = self.take("id")
                annotation = self.take("id") if self.accept(":") else None
                self.take("=")
                expr = self.expression()
                end = self.take(";").span.end
                statements.append(Statement("let", Span(start, end), expr, name, annotation))
            elif self.accept("return"):
                expr = self.expression()
                end = self.take(";").span.end
                statements.append(Statement("return", Span(start, end), expr))
            elif self.accept("if"):
                self.take("(")
                expr = self.expression()
                self.take(")")
                then = self.block()
                otherwise = self.block() if self.accept("else") else []
                statements.append(Statement("if", Span(start, self.tokens[self.index - 1].span.end),
                                            expr, then=then, otherwise=otherwise))
            else:
                expr = self.expression()
                end = self.take(";").span.end
                statements.append(Statement("expr", Span(start, end), expr))
        self.take("}")
        return statements

    def expression(self, minimum: int = 0) -> Expr:
        token = self.current
        if token.kind in ("-", "!"):
            self.index += 1
            child = self.expression(7)
            left = Expr("unary", Span(token.span.start, child.span.end), token.text, [child])
        elif self.accept("("):
            left = self.expression()
            self.take(")")
        elif token.kind in ("int", "true", "false"):
            self.index += 1
            left = Expr("int" if token.kind == "int" else "bool", token.span, token.text)
        else:
            name = self.take("id")
            if self.accept("("):
                args = []
                while self.current.kind != ")":
                    args.append(self.expression())
                    if not self.accept(","):
                        break
                end = self.take(")").span.end
                left = Expr("call", Span(name.span.start, end), name.text, args)
            elif self.accept("{"):
                fields = []
                while self.current.kind != "}":
                    key = self.take("id")
                    self.take(":")
                    fields.append((key, self.expression()))
                    if not self.accept(","):
                        break
                end = self.take("}").span.end
                left = Expr("record", Span(name.span.start, end), name.text, fields=fields)
            else:
                left = Expr("name", name.span, name.text)
        while True:
            if self.accept("."):
                name = self.take("id")
                left = Expr("field", Span(left.span.start, name.span.end), name.text, [left])
                continue
            priority = self.PRECEDENCE.get(self.current.kind, -1)
            if priority < minimum:
                break
            op = self.current
            self.index += 1
            right = self.expression(priority + 1)
            left = Expr("binary", Span(left.span.start, right.span.end), op.text, [left, right])
        return left


@dataclass(frozen=True)
class Binding:
    typ: str
    declaration: Span


@dataclass
class State:
    bindings: dict[str, Binding] = field(default_factory=dict)
    moved: set[str] = field(default_factory=set)

    def copy(self) -> State:
        return State(dict(self.bindings), set(self.moved))


@dataclass
class Reference:
    span: Span
    definition: Span
    description: str


@dataclass
class Analysis:
    source: str
    program: Program
    records: dict[str, Record]
    functions: dict[str, Function]
    references: list[Reference]


class Checker:
    def __init__(self, source: str, program: Program):
        self.source, self.program = source, program
        self.records: dict[str, Record] = {}
        self.functions: dict[str, Function] = {}
        self.references: list[Reference] = []
        self.function: Function | None = None

    def error(self, code: str, message: str, span: Span):
        raise CompileError(code, message, span)

    def reference(self, span: Span, definition: Span, description: str):
        self.references.append(Reference(span, definition, description))

    def type_name(self, token: Token):
        if token.text not in SCALARS and token.text not in self.records:
            self.error("E0101", f"Unknown type {token.text}", token.span)
        if token.text in self.records:
            record = self.records[token.text]
            self.reference(token.span, record.name.span, f"struct {token.text} (move-only)")

    def same_type(self, actual: str, expected: str, span: Span):
        if actual != expected:
            self.error("E0201", f"Expected {expected}, found {actual}; implicit conversions are not supported", span)

    def bind(self, name: Token, typ: str, state: State):
        if name.text in state.bindings:
            self.error("E0102", f"Duplicate or shadowed binding {name.text}", name.span)
        state.bindings[name.text] = Binding(typ, name.span)
        self.reference(name.span, name.span, f"{name.text}: {typ}")

    def check(self) -> Analysis:
        names = set(SCALARS)
        for item in [*self.program.records, *self.program.functions]:
            if item.name.text in names:
                self.error("E0102", f"Duplicate or reserved declaration {item.name.text}", item.name.span)
            names.add(item.name.text)
            if isinstance(item, Record):
                self.records[item.name.text] = item
            else:
                self.functions[item.name.text] = item
        for record in self.program.records:
            self.reference(record.name.span, record.name.span, f"struct {record.name.text} (move-only)")
            if not record.fields:
                self.error("E0204", "Prototype records must have at least one scalar field", record.name.span)
            fields = set()
            for name, typ in record.fields:
                if name.text in fields:
                    self.error("E0102", f"Duplicate field {name.text}", name.span)
                fields.add(name.text)
                if typ.text not in SCALARS:
                    self.error("E0204", "Prototype record fields must be i32 or bool", typ.span)
                self.reference(name.span, name.span, f"{name.text}: {typ.text}")
        for fn in self.program.functions:
            self.type_name(fn.result)
            for _, typ in fn.params:
                self.type_name(typ)
            self.reference(fn.name.span, fn.name.span, fn.signature())
        for fn in self.program.functions:
            self.function = fn
            state = State()
            for name, typ in fn.params:
                self.bind(name, typ.text, state)
            if self.block(fn.body, state):
                self.error("E0205", f"Function {fn.name.text} must return {fn.result.text} on every path", fn.name.span)
        return Analysis(self.source, self.program, self.records, self.functions, self.references)

    def block(self, statements: list[Statement], state: State) -> bool:
        """Return whether control can fall through the block."""
        reachable = True
        for stmt in statements:
            if not reachable:
                self.error("E0206", "Unreachable statement", stmt.span)
            typ = self.expr(stmt.expr, state)
            if stmt.kind == "let":
                if stmt.annotation:
                    self.type_name(stmt.annotation)
                    self.same_type(typ, stmt.annotation.text, stmt.expr.span)
                self.bind(stmt.name, typ, state)
            elif stmt.kind == "return":
                self.same_type(typ, self.function.result.text, stmt.expr.span)
                reachable = False
            elif stmt.kind == "if":
                self.same_type(typ, "bool", stmt.expr.span)
                then, otherwise = state.copy(), state.copy()
                then_live = self.block(stmt.then, then)
                else_live = self.block(stmt.otherwise, otherwise)
                survivors = [s for s, live in ((then, then_live), (otherwise, else_live)) if live]
                state.moved.update(name for s in survivors for name in s.moved if name in state.bindings)
                reachable = bool(survivors)
        return reachable

    def expr(self, expr: Expr, state: State, consume: bool = True) -> str:
        kind, value = expr.kind, expr.value
        if kind == "int":
            digits = value.lstrip("0") or "0"
            if len(digits) > 10 or int(digits) > 2147483647:
                self.error("E0202", "Integer literal is outside the i32 range", expr.span)
            typ = "i32"
        elif kind == "bool":
            typ = "bool"
        elif kind == "name":
            if value not in state.bindings:
                self.error("E0101", f"Unknown binding {value}", expr.span)
            binding = state.bindings[value]
            if value in state.moved:
                self.error("E0301", f"{value} was moved on a possible path and cannot be used again", expr.span)
            typ = binding.typ
            self.reference(expr.span, binding.declaration, f"{value}: {typ}")
            if consume and typ not in SCALARS:
                state.moved.add(value)
        elif kind == "field":
            base = self.expr(expr.args[0], state, consume=False)
            record = self.records.get(base)
            fields = {} if record is None else {n.text: (n, t) for n, t in record.fields}
            if value not in fields:
                self.error("E0101", f"Type {base} has no field {value}", expr.span)
            name, type_token = fields[value]
            typ = type_token.text
            self.reference(Span(expr.span.end - len(value), expr.span.end), name.span, f"{value}: {typ}")
        elif kind == "record":
            record = self.records.get(value)
            if record is None:
                self.error("E0101", f"Unknown record {value}", expr.span)
            expected = {n.text: t.text for n, t in record.fields}
            seen = set()
            for name, child in expr.fields:
                if name.text in seen or name.text not in expected:
                    self.error("E0203", f"Duplicate or unknown field {name.text}", name.span)
                seen.add(name.text)
                self.same_type(self.expr(child, state), expected[name.text], child.span)
            if seen != set(expected):
                self.error("E0203", f"Missing fields: {', '.join(sorted(set(expected) - seen))}", expr.span)
            self.reference(Span(expr.span.start, expr.span.start + len(value)), record.name.span,
                           f"struct {value} (move-only)")
            typ = value
        elif kind == "call":
            fn = self.functions.get(value)
            if fn is None:
                self.error("E0101", f"Unknown function {value}", expr.span)
            if len(expr.args) != len(fn.params):
                self.error("E0203", f"{value} expects {len(fn.params)} arguments", expr.span)
            for child, (_, expected) in zip(expr.args, fn.params):
                self.same_type(self.expr(child, state), expected.text, child.span)
            self.function.calls.add(value)
            self.reference(Span(expr.span.start, expr.span.start + len(value)), fn.name.span, fn.signature())
            typ = fn.result.text
        elif kind == "unary":
            child = expr.args[0]
            if value == "-" and child.kind == "int" and (child.value.lstrip("0") or "0") == "2147483648":
                child.typ = typ = "i32"
            else:
                typ = "i32" if value == "-" else "bool"
                self.same_type(self.expr(child, state), typ, child.span)
        elif kind == "binary":
            left = self.expr(expr.args[0], state)
            # The right side of &&/|| may run. Conservatively mark its moves.
            right = self.expr(expr.args[1], state)
            if value in ("&&", "||"):
                self.same_type(left, "bool", expr.args[0].span)
                self.same_type(right, "bool", expr.args[1].span)
                typ = "bool"
            elif value in ("==", "!="):
                if left not in SCALARS:
                    self.error("E0204", "Record equality is not part of this prototype", expr.span)
                self.same_type(right, left, expr.args[1].span)
                typ = "bool"
            else:
                self.same_type(left, "i32", expr.args[0].span)
                self.same_type(right, "i32", expr.args[1].span)
                typ = "bool" if value in ("<", ">", "<=", ">=") else "i32"
        else:
            raise AssertionError(kind)
        expr.typ = typ
        return typ


def analyze(source: str) -> Analysis:
    try:
        program = Parser(lex(source)).program()
        pending = [(stmt, 1) for fn in program.functions for stmt in fn.body]
        while pending:
            node, depth = pending.pop()
            if depth > MAX_AST_DEPTH:
                raise CompileError("E0005", "Syntax tree exceeds the 128-level prototype limit", node.span)
            if isinstance(node, Statement):
                children = [node.expr, *node.then, *node.otherwise]
            else:
                children = [*node.args, *(child for _, child in node.fields)]
            pending.extend((child, depth + 1) for child in children)
        return Checker(source, program).check()
    except RecursionError:
        raise CompileError("E0005", "Expression or block nesting exceeds the prototype limit", Span(0, 0)) from None


def require_entry(analysis: Analysis):
    fn = analysis.functions.get("main")
    if fn is None or fn.params or fn.result.text != "i32":
        raise CompileError("E0401", "A hosted executable requires fn main() -> i32", fn.name.span if fn else Span(0, 0))
