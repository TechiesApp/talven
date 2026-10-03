"""Bounded local modules resolved into the unchanged shared semantic frontend.

The in-memory API never fetches files. The CLI loader opens explicit root-relative
regular files through a pinned directory descriptor without following symlinks.
Neither source identities nor observed rereads replace writer coordination.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import bisect
import os
from pathlib import Path
import re
import stat

from .context import compiler_hash, encode, expressions, function_fact, source_hash
from .frontend import (Analysis, BUILTINS, COPY_TYPES, CompileError, Expr, MAX_SOURCE_BYTES,
                       MAX_TOKENS, Parser, Program, Span, Token, _check_depth, analyze,
                       base_type, lex, source_range, text_literal)

PROFILE = 'm1-local-modules-v1'
MAX_MODULES = 32
MAX_IMPORT_DEPTH = 16
INTERNAL_PREFIX = '__talven_module_'
PATH = re.compile(r'[A-Za-z_0-9-]+(?:/[A-Za-z_0-9-]+)*\.tal\Z')


class ProjectError(CompileError):
    def __init__(self, error: CompileError, path: str, source: str):
        super().__init__(error.code, error.message, error.span)
        self.path, self.source_text = path, source

    def diagnostic(self, source=''):
        return {**super().diagnostic(self.source_text), 'file': self.path}


def failure(code, message, span=Span(0, 0)):
    return CompileError(code, message, span)


def module_path(value):
    if not isinstance(value, str) or len(value) > 128 or not PATH.fullmatch(value):
        raise failure('E1101', 'Module path must be a canonical root-relative ASCII .tal path of at most 128 bytes')
    return value


@dataclass
class Import:
    path: str
    names: list[tuple[Token, Token]]
    span: Span


@dataclass
class Module:
    source: str
    program: Program
    imports: list[Import]
    public: dict[str, int]
    declarations: dict[str, object]
    tokens: int


class ModuleParser(Parser):
    def word(self, text):
        if self.current.kind != 'id' or self.current.text != text:
            raise failure('E0002', f'Expected {text}', self.current.span)
        return self.take('id')

    def module(self, source):
        imports, public, records, functions = [], {}, [], []
        while self.current.kind == 'id' and self.current.text == 'import':
            start = self.word('import').span.start
            path = self.take('text')
            _, decoded = text_literal(path.text, 0)
            try:
                module_path(decoded)
            except CompileError as error:
                raise failure(error.code, error.message, path.span) from None
            self.take('{')
            names = []
            while self.current.kind != '}':
                name = self.take('id')
                alias = name
                if self.current.kind == 'id' and self.current.text == 'as':
                    self.word('as')
                    alias = self.take('id')
                names.append((name, alias))
                if not self.accept(','):
                    break
            self.take('}')
            end = self.take(';').span.end
            if not 1 <= len(names) <= 128:
                raise failure('E1101', 'An import requires 1 through 128 named declarations', Span(start, end))
            imports.append(Import(decoded, names, Span(start, end)))
        while self.current.kind != 'eof':
            start = None
            if self.current.kind == 'id' and self.current.text == 'pub':
                start = self.word('pub').span.start
            before = len(records), len(functions)
            self.declaration(records, functions)
            declaration = records[-1] if len(records) != before[0] else functions[-1]
            if start is not None:
                public[declaration.name.text] = start
        program = Program(records, functions)
        _check_depth(program)
        declarations = {}
        for declaration in sorted([*records, *functions], key=lambda d: d.span.start):
            name = declaration.name.text
            if name in declarations or name in COPY_TYPES | BUILTINS:
                raise failure('E0102', f'Duplicate or reserved global name {name}', declaration.name.span)
            declarations[name] = declaration
        return Module(source, program, imports, public, declarations, len(self.tokens) - 1)


def parse_module(source):
    try:
        tokens = lex(source)
        for token in tokens:
            if token.kind == 'id' and token.text.startswith(INTERNAL_PREFIX):
                raise failure('E1101', f'{INTERNAL_PREFIX} is reserved in the module profile', token.span)
        return ModuleParser(tokens).module(source)
    except RecursionError:
        raise failure('E0005', 'Module syntax exceeds the prototype nesting limit') from None


@dataclass
class Segment:
    start: int
    end: int
    file: str
    original: Span
    replaced: bool


@dataclass
class ProjectReference:
    file: str
    span: Span
    definition: tuple[str, Span] | None
    description: str


@dataclass
class Project:
    entry: str
    modules: dict[str, Module]
    scopes: dict[str, dict[str, str]]
    owners: dict[str, tuple[str, str]]
    flattened: str
    analysis: Analysis
    segments: list[Segment]
    references: list[ProjectReference] = field(default_factory=list)
    segment_starts: tuple[int, ...] = field(init=False)

    def __post_init__(self):
        self.segment_starts = tuple(s.start for s in self.segments)

    def location(self, span):
        index = max(0, bisect.bisect_right(self.segment_starts, span.start) - 1)
        first = self.segments[index]
        last_index = max(index, bisect.bisect_right(self.segment_starts, max(span.start, span.end - 1)) - 1)
        last = self.segments[last_index]
        start = first.original.start if first.replaced else first.original.start + span.start - first.start
        end = (last.original.end if last.replaced else last.original.start + span.end - last.start)
        if first.file != last.file:
            end = len(self.modules[first.file].source)
        size = len(self.modules[first.file].source)
        return first.file, Span(min(size, start), min(size, max(start, end)))

    def name(self, internal):
        return '::'.join(self.owners[internal]) if internal in self.owners else internal

    def description(self, text):
        return re.sub(r'\b__talven_module_[A-Za-z_0-9]+\b', lambda m: self.name(m[0]), text)

    def facts(self, internal):
        if internal in self.analysis.functions:
            fn = self.analysis.functions[internal]
            fact = function_fact(fn)
            fact['signature'] = self.description(fn.signature())
            fact['calls'] = sorted(self.name(n) for n in fn.calls)
            for parameter in fact['parameters']:
                parameter['type'] = self.description(parameter['type'])
            fact['returns'] = self.description(fact['returns'])
        else:
            record = self.analysis.records[internal]
            fact = {'kind': 'record', 'ownership': 'move-only',
                    'fields': [{'name': n.text, 'type': t.text} for n, t in record.fields]}
        file, name = self.owners[internal]
        fact.update(name=self.name(internal), file=file, public=name in self.modules[file].public)
        return fact

    def manifest(self):
        modules = []
        for path, module in self.modules.items():
            imports = [{'file': item.path, 'names': [{'name': n.text, 'alias': a.text,
                        'target': self.name(self.scopes[path][a.text])} for n, a in item.names]}
                       for item in module.imports]
            modules.append({'file': path, 'source_hash': source_hash(module.source), 'imports': imports})
        return {'profile': PROFILE, 'entry': self.entry, 'modules': modules,
                'flattened_hash': source_hash(self.flattened)}

    def identity(self):
        manifest = self.manifest()
        return {**manifest, 'graph_hash': source_hash(encode(manifest)), 'compiler_hash': compiler_hash()}


def resolve_project(entry, provider):
    """Resolve only the reachable closure from an explicit source provider."""
    module_path(entry)
    modules, active = {}, []
    total_bytes, total_tokens = 0, 0

    def visit(path):
        nonlocal total_bytes, total_tokens
        if path in active:
            raise ProjectError(failure('E1102', 'Module import cycle: ' + ' -> '.join([*active, path])), path, '')
        if path in modules:
            return
        if len(active) >= MAX_IMPORT_DEPTH or len(modules) >= MAX_MODULES:
            raise ProjectError(failure('E1104', 'Project exceeds 32 modules or 16 import levels'), path, '')
        source = ''
        try:
            source = provider(path)
            if not isinstance(source, str):
                raise failure('E1101', 'Module source must be UTF-8 text')
            total_bytes += len(source.encode('utf-8'))
            if total_bytes > MAX_SOURCE_BYTES:
                raise failure('E1104', 'Project closure exceeds 256 KiB of UTF-8 source')
            module = parse_module(source)
            total_tokens += module.tokens
            if total_tokens > MAX_TOKENS:
                raise failure('E1104', 'Project closure exceeds 16384 tokens')
        except (OSError, UnicodeError, KeyError) as error:
            raise ProjectError(failure('E1102', f'Module unavailable: {path}'), path, source) from error
        except CompileError as error:
            raise ProjectError(error, path, source) from None
        modules[path] = module
        active.append(path)
        for item in module.imports:
            visit(item.path)
        active.pop()

    visit(entry)
    modules = dict(sorted(modules.items()))
    scopes, owners = {}, {}
    for index, (path, module) in enumerate(modules.items()):
        scopes[path] = {}
        for name, declaration in module.declarations.items():
            internal = ('main' if path == entry and name == 'main' and declaration in module.program.functions
                        else f'{INTERNAL_PREFIX}{index}_{name}')
            scopes[path][name] = internal
            owners[internal] = path, name
    for path, module in modules.items():
        try:
            for item in module.imports:
                target = modules[item.path]
                for original, alias in item.names:
                    if original.text not in target.public:
                        raise failure('E1103', f'{item.path} does not export {original.text}', original.span)
                    if alias.text in scopes[path] or alias.text in COPY_TYPES | BUILTINS:
                        raise failure('E0102', f'Duplicate or reserved module binding {alias.text}', alias.span)
                    scopes[path][alias.text] = scopes[item.path][original.text]
        except CompileError as error:
            raise ProjectError(error, path, module.source) from None
    fragments, segments = [], []
    cursor = 0
    for path, module in modules.items():
        changes = {item.span: '' for item in module.imports}
        for start in module.public.values():
            changes[Span(start, start + 3)] = ''
        scope = scopes[path]

        def resolved(name, span, kind):
            if name not in scope:
                raise failure('E0101', f'Unknown {kind} {name}', span)
            changes[span] = scope[name]

        def typ(token):
            base = base_type(token.text)
            if base not in COPY_TYPES:
                resolved(base, Span(token.span.end - len(base), token.span.end), 'type')

        try:
            for declaration in module.declarations.values():
                changes[declaration.name.span] = scope[declaration.name.text]
            for record in module.program.records:
                for _, token in record.fields:
                    typ(token)
            for fn in module.program.functions:
                for _, token in fn.params:
                    typ(token)
                typ(fn.result)
                if fn.name.text in module.public:
                    for token in [*(t for _, t in fn.params), fn.result]:
                        base = base_type(token.text)
                        if base in module.declarations and base not in module.public:
                            raise failure('E1103', f'Public signature exposes private declaration {base}', token.span)
                pending = list(fn.body)
                while pending:
                    stmt = pending.pop()
                    if stmt.annotation:
                        typ(stmt.annotation)
                    pending.extend([*stmt.then, *stmt.otherwise])
                for expr in expressions(fn.body):
                    if expr.kind in ('call', 'record') and expr.value not in BUILTINS:
                        resolved(expr.value, Span(expr.span.start, expr.span.start + len(expr.value)),
                                 'function' if expr.kind == 'call' else 'record')
        except CompileError as error:
            raise ProjectError(error, path, module.source) from None
        offset = 0
        for span, replacement in sorted(changes.items(), key=lambda c: c[0].start):
            if offset < span.start:
                text = module.source[offset:span.start]
                fragments.append(text)
                segments.append(Segment(cursor, cursor + len(text), path, Span(offset, span.start), False))
                cursor += len(text)
            if replacement:
                fragments.append(replacement)
                segments.append(Segment(cursor, cursor + len(replacement), path, span, True))
                cursor += len(replacement)
            offset = span.end
        text = module.source[offset:]
        fragments.append(text + '\n')
        segments.append(Segment(cursor, cursor + len(text) + 1, path, Span(offset, len(module.source)), False))
        cursor += len(text) + 1
    flattened = ''.join(fragments)
    placeholder = Project(entry, modules, scopes, owners, flattened, None, segments)
    try:
        placeholder.analysis = analyze(flattened)
    except CompileError as error:
        file, span = placeholder.location(error.span)
        raise ProjectError(failure(error.code, placeholder.description(error.message), span),
                           file, modules[file].source) from None
    for reference in placeholder.analysis.references:
        file, span = placeholder.location(reference.span)
        definition = placeholder.location(reference.definition) if reference.definition else None
        placeholder.references.append(ProjectReference(file, span, definition, placeholder.description(reference.description)))
    for path, module in modules.items():
        for item in module.imports:
            for original, alias in item.names:
                declaration = modules[item.path].declarations[original.text]
                internal = scopes[path][alias.text]
                description = (placeholder.description(placeholder.analysis.functions[internal].signature())
                               if internal in placeholder.analysis.functions else f'struct {placeholder.name(internal)} (move-only)')
                for span in dict.fromkeys([original.span, alias.span]):
                    placeholder.references.append(ProjectReference(path, span, (item.path, declaration.name.span), description))
    return placeholder


def analyze_project(entry, sources):
    """Check an explicitly supplied bounded bundle; never load a missing module."""
    if not isinstance(sources, dict) or not 1 <= len(sources) <= MAX_MODULES:
        raise failure('E1104', 'Source bundle requires 1 through 32 modules')
    total = 0
    for path, source in sources.items():
        module_path(path)
        if not isinstance(source, str):
            raise failure('E1101', 'Module source must be UTF-8 text')
        total += len(source.encode('utf-8'))
    if total > MAX_SOURCE_BYTES:
        raise failure('E1104', 'Source bundle exceeds 256 KiB')
    return resolve_project(entry, sources.__getitem__)


class ProjectReader:
    def __init__(self, root):
        if not hasattr(os, 'O_NOFOLLOW') or os.open not in os.supports_dir_fd:
            raise failure('E1102', 'Local module loading requires no-follow directory-relative opens')
        self.root = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.root)

    def verify(self, project):
        for path, module in project.modules.items():
            try:
                if self.read(path) != module.source:
                    raise failure('E0501', 'Module changed during project analysis; request fresh sources')
            except (OSError, UnicodeError, CompileError) as error:
                raise ProjectError(failure('E0501', 'Module changed or became unavailable during project analysis'),
                                   path, module.source) from error

    def read(self, path):
        module_path(path)
        directory = os.dup(self.root)
        try:
            parts = path.split('/')
            for part in parts[:-1]:
                next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(descriptor, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise failure('E1102', 'Module source must be a regular file')
                data = stream.read(MAX_SOURCE_BYTES + 1)
                if len(data) > MAX_SOURCE_BYTES:
                    raise failure('E1104', 'Module exceeds 256 KiB')
                return data.decode('utf-8')
        finally:
            os.close(directory)


def load_project(root, entry):
    reader = ProjectReader(Path(root))
    try:
        project = resolve_project(entry, reader.read)
        reader.verify(project)
        return project
    finally:
        reader.close()


def bounded(value, max_bytes):
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= 1024 * 1024:
        raise failure('E0502', 'Project receipt budget must be between 1 byte and 1 MiB')
    encoded = encode(value)
    if len(encoded.encode('utf-8')) > max_bytes:
        raise failure('E0502', 'Project receipt exceeds byte budget')
    return value


def project_context(project, symbol=None, include_body=False, max_bytes=16384, expected_graph_hash=None):
    identity = project.identity()
    if expected_graph_hash is not None and expected_graph_hash != identity['graph_hash']:
        raise failure('E0501', 'Project revision changed; request fresh sources and context')
    selected = sorted(project.owners)
    if symbol is not None:
        selected = [name for name in selected if project.name(name) == symbol]
        if not selected:
            raise failure('E0101', f'Unknown project symbol {symbol}')
    functions = [name for name in selected if name in project.analysis.functions]
    dependencies = sorted({call for name in functions for call in project.analysis.functions[name].calls}
                          - set(selected) - BUILTINS)
    records = {name for name in selected if name in project.analysis.records}
    for name in functions + dependencies:
        fn = project.analysis.functions[name]
        records.update(base_type(t.text) for _, t in fn.params if base_type(t.text) in project.analysis.records)
        if fn.result.text in project.analysis.records:
            records.add(fn.result.text)
        if name in functions:
            records.update(base_type(e.typ) for e in expressions(fn.body) if base_type(e.typ) in project.analysis.records)
    facts = [project.facts(name) for name in functions]
    if include_body:
        for fact, name in zip(facts, functions):
            path, original = project.owners[name]
            module = project.modules[path]
            fn = module.declarations[original]
            start = module.public.get(original, fn.span.start)
            fact['untrusted_source_text'] = module.source[start:fn.span.end]
    return bounded({'schema': 'talven.project-context.v1', **identity, 'validation': 'frontend-only',
                    'functions': facts, 'dependencies': [project.facts(n) for n in dependencies],
                    'records': [project.facts(n) for n in sorted(records)],
                    'callers': sorted(project.name(n) for n, fn in project.analysis.functions.items()
                                      if any(target in fn.calls for target in selected)),
                    'interfaces': [{'file': path, 'exports': [project.facts(project.scopes[path][n])
                                   for n in sorted(module.public)]} for path, module in project.modules.items()],
                    'required_runtime': ['posix-console'] if any('print' in fn.calls for fn in project.analysis.functions.values()) else []}, max_bytes)


def project_query(project, file, position, kind='definition', max_bytes=16384):
    from .lsp import offset_at
    if file not in project.modules or kind not in ('hover', 'definition', 'references'):
        raise failure('E1101', 'Query requires a checked module and hover, definition or references')
    source = project.modules[file].source
    offset = offset_at(source, position)
    if offset is None:
        raise failure('E1101', 'Invalid UTF-16 project query position')
    refs = [r for r in project.references if r.file == file and r.span.start <= offset < r.span.end]
    ref = min(refs, key=lambda r: r.span.end - r.span.start) if refs else None
    result = None
    def location(path, span):
        return {'file': path, 'range': source_range(project.modules[path].source, span)}
    if ref is not None:
        if kind == 'hover':
            result = {'description': ref.description, **location(file, ref.span)}
        elif kind == 'definition' and ref.definition:
            result = location(*ref.definition)
        elif kind == 'references':
            result = [location(r.file, r.span) for r in project.references if ref.definition is not None and r.definition == ref.definition]
    return bounded({'schema': 'talven.project-query.v1', **project.identity(), 'validation': 'frontend-only',
                    'kind': kind, 'result': result}, max_bytes)
