"""Immutable last-successful body grammar with fresh shared lexing/headers."""

from dataclasses import dataclass

from .frontend import Expr, Parser, Span, Statement, Token, _check_depth, _recursion_limit, lex


@dataclass(frozen=True)
class ExprSyntax:
    kind: str
    span: Span
    value: str
    args: tuple
    fields: tuple


@dataclass(frozen=True)
class StatementSyntax:
    kind: str
    span: Span
    expr: int
    name: Token | None
    annotation: Token | None
    then: tuple
    otherwise: tuple
    mutable: bool
    target: int | None


def children(node):
    if isinstance(node, Expr):
        return [*node.args, *(child for _, child in node.fields)]
    return [node.expr, *node.then, *node.otherwise, *([node.target] if node.target is not None else [])]


@dataclass(frozen=True)
class BodySyntax:
    source: str
    origin: int
    tokens: int
    nodes: tuple
    roots: tuple

    @classmethod
    def freeze(cls, source, origin, tokens, body):
        nodes, indexes = [], {}
        pending = [(stmt, False) for stmt in reversed(body)]
        while pending:
            node, expanded = pending.pop()
            if id(node) in indexes:
                continue
            if not expanded:
                pending.append((node, True))
                pending.extend((child, False) for child in reversed(children(node)))
                continue
            if isinstance(node, Expr):
                fact = ExprSyntax(node.kind, node.span, node.value,
                                  tuple(indexes[id(child)] for child in node.args),
                                  tuple((token, indexes[id(child)]) for token, child in node.fields))
            else:
                fact = StatementSyntax(node.kind, node.span, indexes[id(node.expr)], node.name, node.annotation,
                                       tuple(indexes[id(child)] for child in node.then),
                                       tuple(indexes[id(child)] for child in node.otherwise), node.mutable,
                                       indexes[id(node.target)] if node.target is not None else None)
            indexes[id(node)] = len(nodes)
            nodes.append(fact)
        return cls(source, origin, tokens, tuple(nodes), tuple(indexes[id(stmt)] for stmt in body))

    def restore(self, origin):
        shift = origin - self.origin

        def span(original):
            return Span(original.start + shift, original.end + shift) if shift else original

        def token(original):
            return Token(original.kind, original.text, span(original.span)) if original is not None and shift else original

        nodes = []
        # Facts are postorder: every child is already reconstructed. Expression
        # types and all mutable AST/list objects are fresh, even at zero shift.
        for fact in self.nodes:
            if isinstance(fact, ExprSyntax):
                node = Expr(fact.kind, span(fact.span), fact.value, [nodes[i] for i in fact.args],
                            [(token(label), nodes[i]) for label, i in fact.fields])
            else:
                node = Statement(fact.kind, span(fact.span), nodes[fact.expr], token(fact.name), token(fact.annotation),
                                 [nodes[i] for i in fact.then], [nodes[i] for i in fact.otherwise], fact.mutable,
                                 nodes[fact.target] if fact.target is not None else None)
            nodes.append(node)
        return [nodes[i] for i in self.roots]


class BodyParser(Parser):
    def __init__(self, source, previous, stats):
        super().__init__(lex(source))
        self.source, self.previous, self.stats = source, previous, stats
        self.fragments = {}

    def function_body(self, name):
        start, index = self.current.span.start, self.index
        old = self.previous.get(name)
        if old is not None and self.current.kind == '{' and self.source.startswith(old.source, start):
            last = index + old.tokens - 1
            if (last < len(self.tokens) and self.tokens[last].kind == '}'
                    and self.tokens[last].span.end == start + len(old.source)):
                body = old.restore(start)
                self.index = last + 1
                self.fragments[name] = old
                self.stats['reused'].append(name)
                return body
        body = super().function_body(name)
        end = self.tokens[self.index - 1].span.end
        self.fragments[name] = (self.source[start:end], start, self.index - index, body)
        self.stats['parsed'].append(name)
        return body

    def successful_facts(self):
        return {name: fragment if isinstance(fragment, BodySyntax) else BodySyntax.freeze(*fragment)
                for name, fragment in self.fragments.items()}


def parse_bodies(source, previous, stats):
    try:
        parser = BodyParser(source, previous, stats)
        program = parser.program()
        _check_depth(program)
        return program, parser
    except RecursionError:
        raise _recursion_limit() from None
