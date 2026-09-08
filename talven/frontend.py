"""One parser and semantic checker shared by the CLI, context API, and LSP.

The prototype deliberately stops at the first diagnostic. Records contain only
scalars and are affine values. Named records may be borrowed for a call, with
shared reads or exclusive field mutation. References cannot be stored or
returned. There is no heap allocation, destructor, or foreign resource.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

MAX_SOURCE_BYTES = 256 * 1024
MAX_TOKENS = 16384
MAX_AST_DEPTH = 128
SCALARS = {"i32", "bool"}
COPY_TYPES = SCALARS | {"str"}
BUILTINS = {"print"}
PRINT_SIGNATURE = "fn print(text: str) -> i32"
KEYWORDS = {"fn", "struct", "let", "mut", "return", "if", "else", "true", "false"}


def borrow_mode(typ: str) -> str | None:
    if typ.startswith("&mut "):
        return "exclusive"
    return "shared" if typ.startswith("&") else None


def base_type(typ: str) -> str:
    return typ[5:] if typ.startswith("&mut ") else typ[1:] if typ.startswith("&") else typ


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


def text_literal(source: str, start: int) -> tuple[int, str]:
    """Validate and decode one quoted literal without changing its spelling."""
    escapes = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t", "0": "\0"}
    chars = []
    offset = start + 1
    while offset < len(source):
        char = source[offset]
        if char == '"':
            return offset + 1, "".join(chars)
        if ord(char) < 32 or ord(char) == 127:
            raise CompileError("E0006", "Text literals require escapes for control characters and newlines",
                               Span(start, offset + 1))
        if char == "\\":
            offset += 1
            if offset >= len(source):
                break
            if source[offset] not in escapes:
                raise CompileError("E0006", "Unsupported text escape; use \\\", \\\\, \\n, \\r, \\t, or \\0",
                                   Span(start, offset + 1))
            char = escapes[source[offset]]
        chars.append(char)
        offset += 1
    raise CompileError("E0006", "Unterminated text literal", Span(start, offset))


def lex(source: str, *, include_comments: bool = False) -> list[Token]:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise CompileError("E0005", "Source exceeds the 256 KiB prototype limit", Span(0, 0))
    pattern = re.compile(r"(?P<skip>\s+)|(?P<comment>//[^\n]*)|(?P<int>[0-9]+)|"
                         r"(?P<id>[A-Za-z_][A-Za-z_0-9]*)|"
                         r"(?P<op>->|==|!=|<=|>=|&&|\|\||[{}():;,.+*/%<>=!&\-])")
    tokens = []
    offset = 0
    while offset < len(source):
        if source[offset] == '"':
            end, _ = text_literal(source, offset)
            tokens.append(Token("text", source[offset:end], Span(offset, end)))
            if len(tokens) > MAX_TOKENS:
                raise CompileError("E0005", "Source exceeds the prototype token limit", Span(offset, end))
            offset = end
            continue
        match = pattern.match(source, offset)
        if not match:
            raise CompileError("E0001", "Unexpected character", Span(offset, offset + 1))
        if match.lastgroup != "skip" and (include_comments or match.lastgroup != "comment"):
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
    mutable: bool = False
    target: Expr | None = None


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

    def type_token(self) -> Token:
        if self.current.kind != "&":
            return self.take("id")
        start = self.take("&").span.start
        mutable = self.accept("mut")
        name = self.take("id")
        return Token("type", ("&mut " if mutable else "&") + name.text, Span(start, name.span.end))

    def pairs(self, end: str) -> list[tuple[Token, Token]]:
        result = []
        while self.current.kind != end:
            name = self.take("id")
            self.take(":")
            result.append((name, self.type_token()))
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
                result = self.type_token()
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
                mutable = self.accept("mut")
                name = self.take("id")
                annotation = self.type_token() if self.accept(":") else None
                self.take("=")
                expr = self.expression()
                end = self.take(";").span.end
                statements.append(Statement("let", Span(start, end), expr, name, annotation, mutable=mutable))
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
                target = expr if expr.kind == "field" and self.accept("=") else None
                if target is not None:
                    expr = self.expression()
                end = self.take(";").span.end
                statements.append(Statement("assign" if target else "expr", Span(start, end), expr, target=target))
        self.take("}")
        return statements

    def expression(self, minimum: int = 0) -> Expr:
        token = self.current
        if self.accept("&"):
            mode = "exclusive" if self.accept("mut") else "shared"
            child = self.expression(7)
            left = Expr("borrow", Span(token.span.start, child.span.end), mode, [child])
        elif token.kind in ("-", "!"):
            self.index += 1
            child = self.expression(7)
            left = Expr("unary", Span(token.span.start, child.span.end), token.text, [child])
        elif self.accept("("):
            left = self.expression()
            self.take(")")
        elif token.kind == "text":
            self.index += 1
            _, value = text_literal(token.text, 0)
            left = Expr("text", token.span, value)
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
    mutable: bool = False


@dataclass
class State:
    bindings: dict[str, Binding] = field(default_factory=dict)
    moved: set[str] = field(default_factory=set)
    loans: dict[str, str] = field(default_factory=dict)

    def copy(self) -> State:
        return State(dict(self.bindings), set(self.moved), dict(self.loans))


@dataclass
class Reference:
    span: Span
    definition: Span | None
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

    def reference(self, span: Span, definition: Span | None, description: str):
        self.references.append(Reference(span, definition, description))

    def type_name(self, token: Token, parameter: bool = False):
        mode, base = borrow_mode(token.text), base_type(token.text)
        if mode and not parameter:
            self.error("E0304", "Borrowed types are allowed only on function parameters; references cannot escape", token.span)
        if base not in COPY_TYPES and base not in self.records:
            self.error("E0101", f"Unknown type {token.text}", token.span)
        if mode and base not in self.records:
            self.error("E0305", "Only named records can be borrowed in this profile", token.span)
        if base in self.records:
            record = self.records[base]
            description = f"{token.text} ({mode} borrow; call-scoped)" if mode else f"struct {base} (move-only)"
            self.reference(token.span, record.name.span, description)

    def same_type(self, actual: str, expected: str, span: Span):
        if actual != expected:
            self.error("E0201", f"Expected {expected}, found {actual}; implicit conversions are not supported", span)

    def bind(self, name: Token, typ: str, state: State, mutable: bool = False):
        if name.text in state.bindings:
            self.error("E0102", f"Duplicate or shadowed binding {name.text}", name.span)
        if mutable and typ not in self.records:
            self.error("E0305", "let mut currently supports owned records with scalar fields", name.span)
        state.bindings[name.text] = Binding(typ, name.span, mutable)
        self.reference(name.span, name.span, self.binding_description(name.text, state.bindings[name.text]))

    def binding_description(self, name: str, binding: Binding) -> str:
        mode = borrow_mode(binding.typ)
        detail = f" ({mode} borrow; call-scoped)" if mode else " (mutable owner)" if binding.mutable else ""
        return f"{name}: {binding.typ}{detail}"

    def lookup(self, expr: Expr, state: State) -> Binding:
        if expr.value not in state.bindings:
            self.error("E0101", f"Unknown binding {expr.value}", expr.span)
        if expr.value in state.moved:
            self.error("E0301", f"{expr.value} was moved on a possible path and cannot be used again", expr.span)
        binding = state.bindings[expr.value]
        expr.typ = binding.typ
        self.reference(expr.span, binding.declaration, self.binding_description(expr.value, binding))
        return binding

    def access(self, expr: Expr, state: State, action: str = "read"):
        held = state.loans.get(expr.value)
        if held == "exclusive" or (held and action != "read"):
            self.error("E0302", f"Cannot {action} {expr.value}: an earlier argument holds a {held} borrow until its call returns", expr.span)

    def require_mutable(self, expr: Expr, binding: Binding):
        if borrow_mode(binding.typ) != "exclusive" and not binding.mutable:
            self.error("E0303", f"Mutating {expr.value} requires a let mut owner or an &mut parameter", expr.span)

    def borrow(self, expr: Expr, state: State) -> str:
        place = expr.args[0]
        if place.kind != "name":
            self.error("E0305", "Borrow a named record binding; temporaries, fields, and nested references are unsupported", place.span)
        binding = self.lookup(place, state)
        base = base_type(binding.typ)
        if base not in self.records:
            self.error("E0305", "Only named records can be borrowed in this profile", place.span)
        if expr.value == "exclusive":
            self.require_mutable(place, binding)
        self.access(place, state, "borrow exclusively" if expr.value == "exclusive" else "read")
        state.loans[place.value] = expr.value
        expr.typ = ("&mut " if expr.value == "exclusive" else "&") + base
        return expr.typ

    def assignment(self, stmt: Statement, state: State):
        target = stmt.target
        if target.kind != "field" or target.args[0].kind != "name":
            self.error("E0305", "Assignment requires a scalar field of a named record binding", target.span)
        typ = self.expr(target, state, consume=False)
        place = target.args[0]
        self.require_mutable(place, state.bindings[place.value])
        self.access(place, state, "write")
        self.same_type(self.expr(stmt.expr, state), typ, stmt.expr.span)
        # The right side can move an owned record. The final store is still
        # a use of its destination and must not revive a moved binding.
        self.lookup(place, state)
        self.access(place, state, "write")

    def check(self) -> Analysis:
        names = COPY_TYPES | BUILTINS
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
                self.type_name(typ, parameter=True)
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
            if stmt.kind == "assign":
                self.assignment(stmt, state)
                continue
            typ = self.expr(stmt.expr, state)
            if stmt.kind == "let":
                if stmt.annotation:
                    self.type_name(stmt.annotation)
                    self.same_type(typ, stmt.annotation.text, stmt.expr.span)
                self.bind(stmt.name, typ, state, mutable=stmt.mutable)
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
        elif kind == "text":
            typ = "str"
        elif kind == "name":
            binding = self.lookup(expr, state)
            typ = binding.typ
            if consume and borrow_mode(typ):
                self.error("E0304", "Borrowed parameters cannot be used as owned values; reborrow explicitly in a call", expr.span)
            self.access(expr, state, "move" if consume and typ not in COPY_TYPES else "read")
            if consume and typ not in COPY_TYPES:
                state.moved.add(value)
        elif kind == "field":
            base = self.expr(expr.args[0], state, consume=False)
            record = self.records.get(base_type(base))
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
        elif kind == "call" and value == "print":
            if len(expr.args) != 1:
                self.error("E0203", "print expects 1 argument", expr.span)
            child = expr.args[0]
            actual = self.borrow(child, state) if child.kind == "borrow" else self.expr(child, state)
            self.same_type(actual, "str", child.span)
            self.function.calls.add(value)
            self.reference(Span(expr.span.start, expr.span.start + len(value)), None,
                           PRINT_SIGNATURE + " (requires --console; writes exact bytes; 0 success, 1 write failure)")
            typ = "i32"
        elif kind == "call":
            fn = self.functions.get(value)
            if fn is None:
                self.error("E0101", f"Unknown function {value}", expr.span)
            if len(expr.args) != len(fn.params):
                self.error("E0203", f"{value} expects {len(fn.params)} arguments", expr.span)
            outer_loans = dict(state.loans)
            try:
                for child, (_, expected) in zip(expr.args, fn.params):
                    if child.kind == "borrow":
                        actual = self.borrow(child, state)
                    elif borrow_mode(expected.text):
                        self.error("E0304", f"Pass {expected.text} explicitly with &name or &mut name", child.span)
                    else:
                        actual = self.expr(child, state)
                    self.same_type(actual, expected.text, child.span)
            finally:
                # Nested calls release only their loans. Any loans already
                # held by an enclosing call's earlier arguments remain live.
                state.loans = outer_loans
            self.function.calls.add(value)
            self.reference(Span(expr.span.start, expr.span.start + len(value)), fn.name.span, fn.signature())
            typ = fn.result.text
        elif kind == "borrow":
            self.error("E0304", "Borrow expressions are allowed only as direct call arguments; references cannot be stored or returned", expr.span)
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
                    self.error("E0204", "Equality currently supports only i32 and bool", expr.span)
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


def parse(source: str) -> Program:
    """Parse with the same input/depth limits, without requiring valid types."""
    try:
        program = Parser(lex(source)).program()
        pending = [(stmt, 1) for fn in program.functions for stmt in fn.body]
        while pending:
            node, depth = pending.pop()
            if depth > MAX_AST_DEPTH:
                raise CompileError("E0005", "Syntax tree exceeds the 128-level prototype limit", node.span)
            if isinstance(node, Statement):
                children = [node.expr, *node.then, *node.otherwise]
                if node.target is not None:
                    children.append(node.target)
            else:
                children = [*node.args, *(child for _, child in node.fields)]
            pending.extend((child, depth + 1) for child in children)
        return program
    except RecursionError:
        raise CompileError("E0005", "Expression or block nesting exceeds the prototype limit", Span(0, 0)) from None


def analyze(source: str) -> Analysis:
    try:
        return Checker(source, parse(source)).check()
    except RecursionError:
        raise CompileError("E0005", "Expression or block nesting exceeds the prototype limit", Span(0, 0)) from None


def require_entry(analysis: Analysis):
    fn = analysis.functions.get("main")
    if fn is None or fn.params or fn.result.text != "i32":
        raise CompileError("E0401", "A hosted executable requires fn main() -> i32", fn.name.span if fn else Span(0, 0))
