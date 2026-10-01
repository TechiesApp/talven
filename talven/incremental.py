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
        return None if fn is None else fn.signature()
    record = checker.records.get(name)
    return None if record is None else tuple((n.text, t.text) for n, t in record.fields)


@dataclass(frozen=True)
class Entry:
    source: str
    types: tuple
    calls: tuple
    dependencies: tuple
    references: tuple


class ReusingChecker(Checker):
    def __init__(self, source, program, previous):
        super().__init__(source, program)
        self.previous = previous
        self.next = {}
        self.checked = []
        self.reused = []
        self.locations = None

    def check_function(self, fn):
        name = fn.name.text
        raw = self.source[fn.span.start:fn.span.end]
        entry = self.previous.get(name)
        if self.locations is None:
            self.locations = declarations(self)
        locations = self.locations
        nodes = list(expressions(fn.body))
        if (entry and entry.source == raw and len(entry.types) == len(nodes)
                and all(contract(self, key) == value for key, value in entry.dependencies)):
            for expr, typ in zip(nodes, entry.types):
                expr.typ = typ
            fn.calls.update(entry.calls)
            for relative, destination, description in entry.references:
                span = Span(relative.start + fn.span.start, relative.end + fn.span.start)
                if destination is None:
                    definition = None
                elif isinstance(destination, tuple):
                    definition = locations[destination]
                else:
                    definition = Span(destination.start + fn.span.start, destination.end + fn.span.start)
                self.references.append(Reference(span, definition, description))
            self.next[name] = entry
            self.reused.append(name)
            return

        start = len(self.references)
        super().check_function(fn)
        keys = {('function', called) for called in fn.calls if called in self.functions}
        types = [fn.result.text, *(t.text for _, t in fn.params), *(expr.typ for expr in nodes)]
        keys.update(('record', base_type(typ)) for typ in types if base_type(typ) in self.records)
        destinations = {span: key for key, span in locations.items()}
        saved = []
        for ref in self.references[start:]:
            relative = Span(ref.span.start - fn.span.start, ref.span.end - fn.span.start)
            destination = destinations.get(ref.definition)
            if ref.definition is not None and destination is None:
                destination = Span(ref.definition.start - fn.span.start, ref.definition.end - fn.span.start)
            saved.append((relative, destination, ref.description))
        self.next[name] = Entry(raw, tuple(expr.typ for expr in nodes), tuple(sorted(fn.calls)),
                                tuple((key, contract(self, key)) for key in sorted(keys)), tuple(saved))
        self.checked.append(name)


class IncrementalFrontend:
    """Bounded to one successful revision; callers receive a fresh current Analysis."""

    def __init__(self):
        self.identity = compiler_hash()
        self.entries = {}
        self.stats = {'checked': [], 'reused': []}

    def analyze(self, source):
        self.stats = {'checked': [], 'reused': []}
        if compiler_hash() != self.identity:
            raise CompileError('E0501', 'Compiler inputs changed; restart the persistent frontend session', Span(0, 0))
        checker = ReusingChecker(source, parse(source), self.entries)
        try:
            result = checker.check()
        except RecursionError:
            raise _recursion_limit() from None
        finally:
            self.stats = {'checked': checker.checked, 'reused': checker.reused}
        # Invalid revisions never replace the last successful cache or return its Analysis.
        self.entries = checker.next
        return result
