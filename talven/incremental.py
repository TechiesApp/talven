"""Session-local reuse of successful function checks over freshly parsed source.

Every revision still validates all declarations. No disk cache, stale Analysis,
incremental parser, native build cache, or application state is retained.
"""

from dataclasses import dataclass

from .context import compiler_hash
from .frontend import Checker, CompileError, Expr, Reference, Span, _recursion_limit, base_type, parse


def expressions(body):
    """Stable iterative expression order, including assignment destinations."""
    pending = list(reversed(body))
    while pending:
        node = pending.pop()
        if isinstance(node, Expr):
            yield node
            children = [*node.args, *(child for _, child in node.fields)]
        else:
            children = [node.expr, *node.then, *node.otherwise]
            if node.target is not None:
                children.append(node.target)
        pending.extend(reversed(children))


def declarations(checker):
    result = {('function', name): fn.name.span for name, fn in checker.functions.items()}
    for name, record in checker.records.items():
        result['record', name] = record.name.span
        for field, _ in record.fields:
            result['field', name, field.text] = field.span
    return result


def contract(checker, key):
    kind, name = key
    if kind == 'function':
        fn = checker.functions.get(name)
        if fn is None:
            return None
        return (tuple(typ.text for _, typ in fn.params), fn.result.text) if checker.call_type_contracts else fn.signature()
    record = checker.records.get(name)
    return None if record is None else tuple((n.text, t.text) for n, t in record.fields)


@dataclass(frozen=True)
class Entry:
    source: str
    origin: int
    types: tuple
    calls: tuple
    dependencies: tuple
    references: tuple


class ReusingChecker(Checker):
    def __init__(self, source, program, previous, *, call_type_contracts=False):
        super().__init__(source, program)
        self.previous = previous
        self.call_type_contracts = call_type_contracts
        self.next = {}
        self.checked = []
        self.reused = []
        self.locations = None
        self.destinations = None

    def check_function(self, fn):
        name = fn.name.text
        raw = self.source[fn.span.start:fn.span.end]
        entry = self.previous.get(name)
        if self.locations is None:
            self.locations = declarations(self)
            self.destinations = {span: key for key, span in self.locations.items()}
        locations = self.locations
        if (entry and entry.source == raw
                and all(contract(self, key) == value for key, value in entry.dependencies)):
            # Exact function text and pinned compiler inputs imply the same
            # parsed expression order; walk it once without a temporary list.
            for expr, typ in zip(expressions(fn.body), entry.types, strict=True):
                expr.typ = typ
            fn.calls.update(entry.calls)
            shift = fn.span.start - entry.origin
            local_definitions = {}
            for original, destination, description in entry.references:
                span = Span(original.start + shift, original.end + shift) if shift else original
                if destination is None:
                    definition = None
                elif isinstance(destination, tuple):
                    definition = locations[destination]
                    if self.call_type_contracts and destination[0] == 'function':
                        description = self.functions[destination[1]].signature()
                else:
                    if destination not in local_definitions:
                        local_definitions[destination] = (Span(destination.start + shift, destination.end + shift)
                                                          if shift else destination)
                    definition = local_definitions[destination]
                self.references.append(Reference(span, definition, description))
            self.next[name] = entry
            self.reused.append(name)
            return

        start = len(self.references)
        super().check_function(fn)
        nodes = list(expressions(fn.body))
        keys = {('function', called) for called in fn.calls if called in self.functions}
        types = [fn.result.text, *(t.text for _, t in fn.params), *(expr.typ for expr in nodes)]
        keys.update(('record', base_type(typ)) for typ in types if base_type(typ) in self.records)
        saved = []
        for ref in self.references[start:]:
            destination = self.destinations.get(ref.definition)
            if ref.definition is not None and destination is None:
                destination = ref.definition
            saved.append((ref.span, destination, ref.description))
        self.next[name] = Entry(raw, fn.span.start, tuple(expr.typ for expr in nodes), tuple(sorted(fn.calls)),
                                tuple((key, contract(self, key)) for key in sorted(keys)), tuple(saved))
        self.checked.append(name)


class IncrementalFrontend:
    """Bounded to one successful revision; callers receive a fresh current Analysis."""

    def __init__(self, *, call_type_contracts=False, reuse_body_syntax=False):
        if type(call_type_contracts) is not bool:
            raise ValueError('Call type contracts must be an explicit boolean')
        self.call_type_contracts = call_type_contracts
        if type(reuse_body_syntax) is not bool:
            raise ValueError('Body syntax reuse must be an explicit boolean')
        self.reuse_body_syntax = reuse_body_syntax
        self._syntax = {}
        self.parse_stats = {'parsed': [], 'reused': []}
        self.identity = compiler_hash()
        self.entries = {}
        self.stats = {'checked': [], 'reused': []}

    def analyze(self, source):
        if type(self.call_type_contracts) is not bool:
            raise ValueError('Call type contracts must be an explicit boolean')
        if type(self.reuse_body_syntax) is not bool:
            raise ValueError('Body syntax reuse must be an explicit boolean')
        self.stats = {'checked': [], 'reused': []}
        self.parse_stats = {'parsed': [], 'reused': []}
        if compiler_hash() != self.identity:
            raise CompileError('E0501', 'Compiler inputs changed; restart the persistent frontend session', Span(0, 0))
        parser = None
        if self.reuse_body_syntax:
            from .body_syntax import parse_bodies
            program, parser = parse_bodies(source, self._syntax, self.parse_stats)
        else:
            program = parse(source)
            self.parse_stats['parsed'] = [fn.name.text for fn in program.functions]
        checker = ReusingChecker(source, program, self.entries, call_type_contracts=self.call_type_contracts)
        try:
            result = checker.check()
        except RecursionError:
            raise _recursion_limit() from None
        finally:
            self.stats = {'checked': checker.checked, 'reused': checker.reused}
        # Invalid revisions never replace the last successful cache or return its Analysis.
        syntax = parser.successful_facts() if parser is not None else {}
        self.entries, self._syntax = checker.next, syntax
        return result
