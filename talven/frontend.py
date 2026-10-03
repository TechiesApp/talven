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
# Active block/expression parses, counting a function body as 1. Parentheses
# count here but not in the syntax tree. Keeping this well below Python's
# recursion limit makes the diagnostic independent of the interpreter version.
MAX_NESTING = 256
# Diagnostics reported by one check; later errors are dropped to keep output bounded.
MAX_DIAGNOSTICS = 20
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
    # Bidirectional controls can make displayed code differ from compiled code.
    hidden = re.search(r"[\u202a-\u202e\u2066-\u2069]", source)
    if hidden:
        raise CompileError("E0001", "Bidirectional control characters are not allowed in source",
                           Span(hidden.start(), hidden.end()))
    pattern = re.compile(r"(?P<skip>(?:[ \t\n]|\r\n)+)|(?P<comment>//[^\r\n]*)|(?P<int>[0-9]+)|"
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
            # Comments stop at any CR, so a lone CR (a line break to editors and
            # LSP) cannot hide the code after it inside a comment.
            message = ("Carriage return must be followed by a line feed" if source[offset] == "\r"
                       else "Unexpected character")
            raise CompileError("E0001", message, Span(offset, offset + 1))
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
    origin: str | None = None


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
    arms: list[MatchArm] = field(default_factory=list)


@dataclass
class MatchArm:
    outcome: Token
    variant: Token
    binding: Token | None
    body: list[Statement]


@dataclass
class Record:
    name: Token
    fields: list[tuple[Token, Token]]
    span: Span


@dataclass
class Outcome(Record):
    variants: list[tuple[Token, Token | None]]


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

    def __init__(self, tokens: list[Token], recover: bool = False, *, outcomes: bool = False, resources: bool = False):
        self.tokens, self.index, self.nesting = tokens, 0, 0
        self.outcomes = outcomes or resources
        self.resources = resources
        # With recovery, a syntax error is recorded and parsing resumes at the
        # next statement or declaration, so one check reports several errors.
        self.recover, self.errors = recover, []
        self.declaration_errors, self.broken = False, set()

    def recovered(self, error: CompileError, stop: set[str]) -> None:
        """Record error, then skip to a boundary; limits and a full list end the parse."""
        if not self.recover or error.code == "E0005" or len(self.errors) >= MAX_DIAGNOSTICS - 1:
            raise error
        self.errors.append(error)
        depth = 0
        while self.current.kind != "eof":
            kind = self.current.kind
            if depth == 0 and kind in stop:
                if kind == ";":
                    self.index += 1
                return
            if kind == "{":
                depth += 1
            elif kind == "}":
                if depth == 0:
                    return
                depth -= 1
            self.index += 1

    def enter(self):
        self.nesting += 1
        if self.nesting > MAX_NESTING:
            raise CompileError("E0005", f"Expression or block nesting exceeds the {MAX_NESTING}-level prototype limit",
                               self.current.span)

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
            before = self.index
            try:
                self.declaration(records, functions)
            except CompileError as error:
                self.recovered(error, {"fn", "struct"})
                self.declaration_errors = True
                if self.index == before:
                    self.index += 1
                while self.current.kind == "}":
                    self.index += 1
        return Program(records, functions)

    def declaration(self, records: list[Record], functions: list[Function]):
        start = self.current.span.start
        if self.outcomes and self.accept("outcome"):
            name = self.take("id")
            self.take("{")
            variants = []
            while self.current.kind != "}":
                variant = self.take("id")
                payload = None
                if self.accept("("):
                    payload = self.type_token()
                    self.take(")")
                variants.append((variant, payload))
                if not self.accept(","):
                    break
            end = self.take("}").span.end
            records.append(Outcome(name, [], Span(start, end), variants))
            return
        if self.accept("struct"):
            name = self.take("id")
            self.take("{")
            fields = self.pairs("}")
            records.append(Record(name, fields, Span(start, self.tokens[self.index - 1].span.end)))
            return
        self.take("fn")
        name = self.take("id")
        self.take("(")
        params = self.pairs(")")
        self.take("->")
        result = self.type_token()
        errors = len(self.errors)
        body = self.function_body(name.text)
        if len(self.errors) > errors:
            self.broken.add(name.text)
        functions.append(Function(name, params, result, body, Span(start, self.tokens[self.index - 1].span.end)))

    def function_body(self, name: str) -> list[Statement]:
        return self.block()

    def block(self) -> list[Statement]:
        self.enter()
        try:
            return self.block_body()
        finally:
            self.nesting -= 1

    def block_body(self) -> list[Statement]:
        self.take("{")
        statements = []
        while self.current.kind != "}":
            before = self.index
            try:
                statements.append(self.statement())
            except CompileError as error:
                self.recovered(error, {";"})
                if self.current.kind == "eof":
                    return statements
                if self.index == before and self.current.kind != "}":
                    self.index += 1
        self.take("}")
        return statements

    def statement(self) -> Statement:
        start = self.current.span.start
        if self.resources and self.accept("region"):
            name = self.take("id")
            self.take("(")
            capacity = self.take("int")
            self.take(")")
            body = self.block()
            return Statement("region", Span(start, self.tokens[self.index - 1].span.end),
                             Expr("int", capacity.span, capacity.text), name=name, then=body)
        if self.outcomes and self.accept("match"):
            self.take("(")
            expr = self.expression()
            self.take(")")
            self.take("{")
            arms = []
            while self.current.kind != "}":
                outcome = self.take("id")
                self.take(":")
                self.take(":")
                variant = self.take("id")
                binding = None
                if self.accept("("):
                    binding = self.take("id")
                    self.take(")")
                arms.append(MatchArm(outcome, variant, binding, self.block()))
            end = self.take("}").span.end
            return Statement("match", Span(start, end), expr, arms=arms)
        if self.accept("let"):
            mutable = self.accept("mut")
            name = self.take("id")
            annotation = self.type_token() if self.accept(":") else None
            self.take("=")
            expr = self.expression()
            end = self.take(";").span.end
            return Statement("let", Span(start, end), expr, name, annotation, mutable=mutable)
        if self.accept("return"):
            expr = self.expression()
            end = self.take(";").span.end
            return Statement("return", Span(start, end), expr)
        if self.accept("if"):
            self.take("(")
            expr = self.expression()
            self.take(")")
            then = self.block()
            otherwise = self.block() if self.accept("else") else []
            return Statement("if", Span(start, self.tokens[self.index - 1].span.end),
                             expr, then=then, otherwise=otherwise)
        expr = self.expression()
        target = expr if self.accept("=") else None
        if target is not None:
            expr = self.expression()
        end = self.take(";").span.end
        return Statement("assign" if target else "expr", Span(start, end), expr, target=target)

    def expression(self, minimum: int = 0) -> Expr:
        self.enter()
        try:
            return self.expression_body(minimum)
        finally:
            self.nesting -= 1

    def expression_body(self, minimum: int) -> Expr:
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
            if self.outcomes and self.accept(":"):
                self.take(":")
                variant = self.take("id")
                args = []
                if self.accept("("):
                    args.append(self.expression())
                    self.take(")")
                left = Expr("outcome", Span(name.span.start, self.tokens[self.index - 1].span.end),
                            name.text + "::" + variant.text, args)
            elif self.accept("("):
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
            if priority in (3, 4) and self.PRECEDENCE.get(self.current.kind) == priority:
                raise CompileError("E0002", "Comparisons do not chain; add parentheses",
                                   Span(left.span.start, self.current.span.end))
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

    resources: dict[str, str] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)

    def copy(self) -> State:
        return State(dict(self.bindings), set(self.moved), dict(self.loans),
                     dict(self.resources), dict(self.origins), dict(self.regions))


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
    resources: bool = False


class Checker:
    def __init__(self, source: str, program: Program, skip: set[str] | None = None, *, resources: bool = False):
        # With skip given, function bodies are checked independently: errors are
        # collected in self.errors and the functions named in skip are not checked.
        self.source, self.program = source, program
        self.skip, self.errors = skip, []
        self.records: dict[str, Record] = {}
        self.functions: dict[str, Function] = {}
        self.references: list[Reference] = []
        self.function: Function | None = None
        self.resources = resources
        if resources:
            from .resources import builtin_types
            self.records.update(builtin_types())

    def error(self, code: str, message: str, span: Span):
        raise CompileError(code, message, span)

    def reference(self, span: Span, definition: Span | None, description: str):
        if self.resources and definition == Span(0, 0):
            definition = None  # Compiler facts have no source declaration to rename.
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
            if mode and isinstance(record, Outcome):
                self.error("E0305", "Outcomes cannot be borrowed", token.span)
            description = f"{token.text} ({mode} borrow; call-scoped)" if mode else f"struct {base} (move-only)"
            self.reference(token.span, record.name.span, description)

    def same_type(self, actual: str, expected: str, span: Span):
        if actual != expected:
            self.error("E0201", f"Expected {expected}, found {actual}; implicit conversions are not supported", span)

    def bind(self, name: Token, typ: str, state: State, mutable: bool = False):
        if name.text in state.bindings or (self.resources and name.text in state.regions):
            self.error("E0102", f"Duplicate or shadowed binding {name.text}", name.span)
        if mutable and (isinstance(self.records.get(typ), Outcome) or
                        (typ not in SCALARS and typ not in self.records)):
            self.error("E0305", "let mut supports i32, bool, or owned records with scalar fields", name.span)
        state.bindings[name.text] = Binding(typ, name.span, mutable)
        self.reference(name.span, name.span, self.binding_description(name.text, state.bindings[name.text]))

    def binding_description(self, name: str, binding: Binding) -> str:
        mode = borrow_mode(binding.typ)
        detail = (f" ({mode} borrow; call-scoped)" if mode else
                  " (mutable local)" if binding.mutable and binding.typ in SCALARS else
                  " (mutable owner)" if binding.mutable else "")
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
            self.error("E0302", f"Cannot {action} {expr.value}: an earlier argument holds {'an' if held == 'exclusive' else 'a'} {held} borrow until its call returns", expr.span)

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
        if isinstance(self.records[base], Outcome):
            self.error("E0305", "Outcomes cannot be borrowed", place.span)
        if expr.value == "exclusive":
            self.require_mutable(place, binding)
        self.access(place, state, "borrow exclusively" if expr.value == "exclusive" else "read")
        state.loans[place.value] = expr.value
        expr.typ = ("&mut " if expr.value == "exclusive" else "&") + base
        return expr.typ

    def assignment(self, stmt: Statement, state: State):
        target = stmt.target
        if target.kind == "name":
            binding = self.lookup(target, state)
            if binding.typ not in SCALARS:
                self.error("E0305", "Whole-binding assignment supports only i32 or bool locals", target.span)
            self.require_mutable(target, binding)
            self.same_type(self.expr(stmt.expr, state), binding.typ, stmt.expr.span)
            return
        if target.kind != "field" or target.args[0].kind != "name":
            self.error("E0305", "Assignment requires a named scalar local or a scalar field of a named record binding", target.span)
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
        if self.resources:
            from .resources import BUILTIN_NAMES
            names = names | BUILTIN_NAMES
        for item in [*self.program.records, *self.program.functions]:
            if item.name.text in names:
                self.error("E0102", f"Duplicate or reserved declaration {item.name.text}", item.name.span)
            names.add(item.name.text)
            if isinstance(item, Record):
                self.records[item.name.text] = item
            else:
                self.functions[item.name.text] = item
        for record in self.program.records:
            if isinstance(record, Outcome):
                self.reference(record.name.span, record.name.span, f"outcome {record.name.text} (must-handle; move-only)")
                if not record.variants:
                    self.error("E0310", "Outcomes require at least one variant", record.name.span)
                seen = set()
                for name, payload in record.variants:
                    if name.text in seen:
                        self.error("E0102", f"Duplicate variant {name.text}", name.span)
                    seen.add(name.text)
                    self.reference(name.span, name.span, f"{record.name.text}::{name.text}")
                    if payload:
                        if self.resources and base_type(payload.text) in ("Block", "Allocation"):
                            self.error("E0320", "User outcomes cannot contain Block or Allocation", payload.span)
                        if payload.text not in SCALARS and (payload.text not in self.records or
                                isinstance(self.records[payload.text], Outcome)):
                            self.error("E0310", "Outcome payloads must be i32, bool, or owned scalar records", payload.span)
                        self.type_name(payload)
                continue
            self.reference(record.name.span, record.name.span, f"struct {record.name.text} (move-only)")
            if not record.fields:
                self.error("E0204", "Prototype records must have at least one scalar field", record.name.span)
            fields = set()
            for name, typ in record.fields:
                if name.text in fields:
                    self.error("E0102", f"Duplicate field {name.text}", name.span)
                fields.add(name.text)
                if self.resources and base_type(typ.text) in ("Block", "Allocation"):
                    self.error("E0320", "User records cannot contain Block or Allocation", typ.span)
                if typ.text not in SCALARS:
                    self.error("E0204", "Prototype record fields must be i32 or bool", typ.span)
                self.reference(name.span, name.span, f"{name.text}: {typ.text}")
        for fn in self.program.functions:
            if self.resources:
                if base_type(fn.result.text) in ("Block", "Allocation"):
                    self.error("E0320", "Resource owners and regions cannot escape through function results", fn.result.span)
                for _, typ in fn.params:
                    if base_type(typ.text) in ("Allocation",):
                        self.error("E0320", "Allocation and regions cannot be function parameters", typ.span)
            self.type_name(fn.result)
            for _, typ in fn.params:
                self.type_name(typ, parameter=True)
            self.reference(fn.name.span, fn.name.span, fn.signature())
        for fn in self.program.functions:
            if self.skip is not None and fn.name.text in self.skip:
                continue
            try:
                self.check_function(fn)
            except CompileError as error:
                if self.skip is None:
                    raise
                self.errors.append(error)
        return Analysis(self.source, self.program, self.records, self.functions, self.references, self.resources)

    def check_function(self, fn: Function):
        """Check one body after every declaration and public contract is validated."""
        self.function = fn
        state = State()
        self.region_count = 0
        if self.resources:
            pending = list(reversed(fn.body))
            while pending:
                stmt = pending.pop()
                if stmt.kind == "region":
                    self.region_count += 1
                    digits = stmt.expr.value.lstrip("0") or "0"
                    if len(digits) > 4 or not 1 <= int(digits) <= 4096:
                        self.error("E0320", "Region capacity must be 1..4096 bytes", stmt.expr.span)
                    if self.region_count > 8:
                        self.error("E0320", "At most eight regions are allowed per function", stmt.name.span)
                children = [*stmt.then, *stmt.otherwise, *(child for arm in stmt.arms for child in arm.body)]
                pending.extend(reversed(children))
        for name, typ in fn.params:
            self.bind(name, typ.text, state)
            if self.resources and typ.text == "Block":
                origin = f"{fn.name.text}:parameter:{name.span.start}"
                state.origins[name.text] = origin
                state.resources[origin] = "live"
        if self.block(fn.body, state):
            self.error("E0205", f"Function {fn.name.text} must return {fn.result.text} on every path", fn.name.span)

    def block(self, statements: list[Statement], state: State) -> bool:
        """Return whether control can fall through the block."""
        initial = set(state.bindings)
        reachable = True
        for stmt in statements:
            if not reachable:
                self.error("E0206", "Unreachable statement", stmt.span)
            if self.resources and stmt.kind == "region":
                if stmt.name.text in state.bindings or stmt.name.text in state.regions:
                    self.error("E0102", f"Duplicate or shadowed binding {stmt.name.text}", stmt.name.span)
                origin = f"{self.function.name.text}:region:{stmt.name.span.start}"
                state.regions[stmt.name.text] = origin
                state.resources[origin] = "free"
                self.reference(stmt.name.span, stmt.name.span, f"region {stmt.name.text} ({int(stmt.expr.value.lstrip('0') or '0')} bytes; lexical)")
                reachable = self.block(stmt.then, state)
                if reachable and state.resources[origin] != "free":
                    self.error("E0321", "Region leaves scope with an outstanding owner or reservation", stmt.name.span)
                del state.regions[stmt.name.text]
                del state.resources[origin]
                continue
            if stmt.kind == "assign":
                self.assignment(stmt, state)
                continue
            typ = self.expr(stmt.expr, state)
            if stmt.kind == "let":
                if stmt.annotation:
                    self.type_name(stmt.annotation)
                    self.same_type(typ, stmt.annotation.text, stmt.expr.span)
                self.bind(stmt.name, typ, state, mutable=stmt.mutable)
                if self.resources and stmt.expr.origin is not None:
                    state.origins[stmt.name.text] = stmt.expr.origin
            elif stmt.kind == "return":
                self.same_type(typ, self.function.result.text, stmt.expr.span)
                self.handled(state, state.bindings)
                if self.resources and any(slot != "free" for slot in state.resources.values()):
                    self.error("E0321", "Normal return requires every resource obligation to be released", stmt.span)
                reachable = False
            elif stmt.kind == "if":
                self.same_type(typ, "bool", stmt.expr.span)
                then, otherwise = state.copy(), state.copy()
                then_live = self.block(stmt.then, then)
                else_live = self.block(stmt.otherwise, otherwise)
                survivors = [s for s, live in ((then, then_live), (otherwise, else_live)) if live]
                self.join(state, survivors, stmt.span)
                reachable = bool(survivors)
            elif stmt.kind == "match":
                outcome = self.records.get(typ)
                if not isinstance(outcome, Outcome):
                    self.error("E0310", "match requires an owned outcome", stmt.expr.span)
                variants = {n.text: (n, p) for n, p in outcome.variants}
                seen, survivors = set(), []
                for arm in stmt.arms:
                    self.same_type(arm.outcome.text, typ, arm.outcome.span)
                    if arm.variant.text in seen or arm.variant.text not in variants:
                        self.error("E0310", f"Duplicate or unknown variant {arm.variant.text}", arm.variant.span)
                    seen.add(arm.variant.text)
                    name, payload = variants[arm.variant.text]
                    self.reference(arm.outcome.span, outcome.name.span, f"outcome {typ} (move-only)")
                    self.reference(arm.variant.span, name.span, f"{typ}::{name.text}")
                    if bool(payload) != bool(arm.binding):
                        self.error("E0310", "Match payload binding must agree with its variant", arm.variant.span)
                    branch = state.copy()
                    if self.resources and typ == "Allocation":
                        branch.resources[stmt.expr.origin] = "live" if payload else "free"
                    if payload:
                        self.bind(arm.binding, payload.text, branch)
                        if self.resources and payload.text == "Block":
                            branch.origins[arm.binding.text] = stmt.expr.origin
                    if self.block(arm.body, branch):
                        if self.resources and payload:
                            self.handled(branch, [arm.binding.text])
                        survivors.append(branch)
                if seen != set(variants):
                    self.error("E0310", "Match must handle every variant exactly once", stmt.span)
                self.join(state, survivors, stmt.span)
                reachable = bool(survivors)
            elif self.resources and stmt.kind == "expr" and typ in ("Block", "Allocation"):
                self.error("E0321", "Resource owner or reservation cannot be discarded", stmt.expr.span)
            elif stmt.kind == "expr" and isinstance(self.records.get(typ), Outcome):
                self.error("E0311", "An outcome must be matched, returned, or transferred to an owning parameter", stmt.expr.span)
        if reachable:
            self.handled(state, set(state.bindings) - initial)
        if self.resources:
            for name in set(state.bindings) - initial:
                del state.bindings[name]
                state.origins.pop(name, None)
                state.moved.discard(name)
        return reachable

    def handled(self, state: State, names):
        for name in sorted(names):
            if self.resources and name not in state.moved and state.bindings[name].typ in ("Block", "Allocation"):
                self.error("E0321", f"Resource {name} leaves scope unreleased", state.bindings[name].declaration)
            if name not in state.moved and isinstance(self.records.get(state.bindings[name].typ), Outcome):
                self.error("E0311", f"Outcome {name} leaves scope unhandled", state.bindings[name].declaration)

    def join(self, state: State, survivors: list[State], span: Span):
        if self.resources and survivors:
            for origin in state.resources:
                if len({s.resources.get(origin) for s in survivors}) > 1:
                    self.error("E0321", "Resource obligations must agree on continuing branches", span)
            for name, binding in state.bindings.items():
                if binding.typ in ("Block", "Allocation") and len({name in s.moved for s in survivors}) > 1:
                    self.error("E0321", f"Resource {name} must be consumed consistently on continuing branches", span)
            state.resources = dict(survivors[0].resources)
        for name, binding in state.bindings.items():
            if isinstance(self.records.get(binding.typ), Outcome) and survivors:
                if len({name in s.moved for s in survivors}) > 1:
                    self.error("E0311", f"Outcome {name} must be handled consistently on continuing branches", span)
        state.moved.update(name for s in survivors for name in s.moved if name in state.bindings)

    def expr(self, expr: Expr, state: State, consume: bool = True) -> str:
        kind, value = expr.kind, expr.value
        if self.resources:
            from .resources import check_resource_expr
            resource_type = check_resource_expr(self, expr, state)
            if resource_type is not None:
                expr.typ = resource_type
                return resource_type
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
            if self.resources:
                expr.origin = state.origins.get(value)
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
            if record is None or isinstance(record, Outcome):
                self.error("E0101", f"Unknown record {value}", expr.span)
            expected = {n.text: t.text for n, t in record.fields}
            declarations = {n.text: n.span for n, _ in record.fields}
            seen = set()
            for name, child in expr.fields:
                if name.text in seen or name.text not in expected:
                    self.error("E0203", f"Duplicate or unknown field {name.text}", name.span)
                seen.add(name.text)
                self.reference(name.span, declarations[name.text], f"{name.text}: {expected[name.text]}")
                self.same_type(self.expr(child, state), expected[name.text], child.span)
            if seen != set(expected):
                self.error("E0203", f"Missing fields: {', '.join(sorted(set(expected) - seen))}", expr.span)
            self.reference(Span(expr.span.start, expr.span.start + len(value)), record.name.span,
                           f"struct {value} (move-only)")
            typ = value
        elif kind == "outcome":
            owner, variant = value.split("::")
            outcome = self.records.get(owner)
            if not isinstance(outcome, Outcome):
                self.error("E0310", f"Unknown outcome {owner}", expr.span)
            variants = {n.text: (n, p) for n, p in outcome.variants}
            if variant not in variants:
                self.error("E0310", f"Unknown variant {variant}", expr.span)
            name, payload = variants[variant]
            if len(expr.args) != int(payload is not None):
                self.error("E0310", "Constructor payload must agree with its variant", expr.span)
            if payload:
                self.same_type(self.expr(expr.args[0], state), payload.text, expr.args[0].span)
            self.reference(Span(expr.span.start, expr.span.start + len(owner)), outcome.name.span,
                           f"outcome {owner} (must-handle; move-only)")
            self.reference(Span(expr.span.start + len(owner) + 2, expr.span.start + len(value)), name.span, value)
            typ = owner
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
            transferred = []
            try:
                for child, (_, expected) in zip(expr.args, fn.params):
                    if child.kind == "borrow":
                        actual = self.borrow(child, state)
                    elif borrow_mode(expected.text):
                        self.error("E0304", f"Pass {expected.text} explicitly with &name or &mut name", child.span)
                    else:
                        actual = self.expr(child, state)
                    self.same_type(actual, expected.text, child.span)
                    if self.resources and expected.text == "Block":
                        transferred.append(child.origin)
            finally:
                # Nested calls release only their loans. Any loans already
                # held by an enclosing call's earlier arguments remain live.
                state.loans = outer_loans
            if self.resources:
                for origin in transferred:
                    state.resources[origin] = "free"
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
            before_right = state.copy() if value in ("&&", "||") else None
            right = self.expr(expr.args[1], state)
            if value in ("&&", "||"):
                self.join(state, [before_right, state.copy()], expr.args[1].span)
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


def _check_depth(program: Program) -> None:
    pending = [(stmt, 1) for fn in program.functions for stmt in fn.body]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_AST_DEPTH:
            raise CompileError("E0005", "Syntax tree exceeds the 128-level prototype limit", node.span)
        if isinstance(node, Statement):
            children = [node.expr, *node.then, *node.otherwise]
            children.extend(stmt for arm in node.arms for stmt in arm.body)
            if node.target is not None:
                children.append(node.target)
        else:
            children = [*node.args, *(child for _, child in node.fields)]
        pending.extend((child, depth + 1) for child in children)


def _recursion_limit() -> CompileError:
    return CompileError("E0005", "Expression or block nesting exceeds the prototype limit", Span(0, 0))


def parse(source: str) -> Program:
    """Parse with the same input/depth limits, without requiring valid types."""
    try:
        program = Parser(lex(source)).program()
        _check_depth(program)
        return program
    except RecursionError:
        raise _recursion_limit() from None


def analyze(source: str) -> Analysis:
    """Check source, raising the first error."""
    try:
        return Checker(source, parse(source)).check()
    except RecursionError:
        raise _recursion_limit() from None


def check_source(source: str) -> tuple[Analysis | None, list[CompileError]]:
    """Check source and return up to MAX_DIAGNOSTICS errors.

    The first error is always the one analyze() raises. Syntax errors are
    recovered at statement and declaration boundaries, and each function body
    is checked independently. Semantic checking is skipped when a declaration
    failed to parse, and for function bodies with syntax errors, so it does not
    report errors that are only consequences of earlier ones.
    """
    errors: list[CompileError] = []
    try:
        parser = Parser(lex(source), recover=True)
        try:
            program = parser.program()
            _check_depth(program)
        finally:
            errors.extend(parser.errors)
        if parser.declaration_errors:
            return None, errors
        checker = Checker(source, program, skip=parser.broken)
        analysis = checker.check()
        errors.extend(checker.errors)
    except CompileError as error:
        errors.append(error)
        return None, errors[:MAX_DIAGNOSTICS]
    except RecursionError:
        errors.append(_recursion_limit())
        return None, errors[:MAX_DIAGNOSTICS]
    return (None if errors else analysis), errors[:MAX_DIAGNOSTICS]


def require_entry(analysis: Analysis):
    fn = analysis.functions.get("main")
    if fn is None or fn.params or fn.result.text != "i32":
        raise CompileError("E0401", "A hosted executable requires fn main() -> i32", fn.name.span if fn else Span(0, 0))
