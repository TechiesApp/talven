"""Bounded current-document name completion through the shared lexer/parser.

Recovered syntax supplies names, never successful semantic validation. Suggestions
do not validate an edit or execute source; the ordinary checker remains authoritative.
"""

import json
import string

from .frontend import (KEYWORDS, PRINT_SIGNATURE, SCALARS, CompileError, Parser,
                       Span, _check_depth, base_type, lex, source_range)

MAX_COMPLETIONS = 128
MAX_COMPLETION_BYTES = 64 * 1024
IDENTIFIER_CHARS = string.ascii_letters + string.digits + '_'


def completion_items(source, offset, analysis=None, version=None):
    empty = {"isIncomplete": False, "items": []}
    if type(offset) is not int or not 0 <= offset <= len(source):
        raise ValueError("Invalid completion position")
    start = end = offset
    while start and source[start - 1] in IDENTIFIER_CHARS:
        start -= 1
    while end < len(source) and source[end] in IDENTIFIER_CHARS:
        end += 1
    if start != end and source[start] not in string.ascii_letters + '_':
        return empty
    prefix = source[start:offset]
    try:
        tokens = lex(source, include_comments=True)
        if any(t.kind in ('comment', 'text') and t.span.start <= offset < t.span.end
               or t.kind == 'comment' and offset == t.span.end for t in tokens):
            return empty
        tokens = [t for t in tokens if t.kind != 'comment']
        if analysis is not None and analysis.source != source:
            analysis = None
        if analysis is None:
            program = Parser(tokens, recover=True).program()
            _check_depth(program)
        else:
            program = analysis.program
    except (CompileError, RecursionError, UnicodeError):
        return empty

    # Brace paths identify lexical scopes without repeating ownership/type rules.
    paths, stack, cursor_path = {}, [], None
    for token in tokens:
        if cursor_path is None and token.span.start >= offset:
            cursor_path = tuple(stack)
        paths[token.span.start] = tuple(stack)
        if token.kind == '{':
            stack.append(token.span.start)
        elif token.kind == '}' and stack:
            stack.pop()
    if cursor_path is None:
        cursor_path = tuple(stack)
    checked = analysis is not None
    descriptions = ({r.definition: r.description for r in analysis.references
                     if r.span == r.definition} if checked else {})
    locals = {}
    for fn in program.functions:
        if not fn.span.start <= offset <= fn.span.end:
            continue
        opening = next((t.span.start for t in tokens if t.kind == '{'
                        and fn.result.span.end <= t.span.start < fn.span.end), None)
        if opening not in cursor_path:
            continue
        for name, typ in fn.params:
            locals[name.text] = (typ.text, descriptions.get(name.span, f"{name.text}: {typ.text}"))
        pending = list(fn.body)
        while pending:
            stmt = pending.pop()
            pending.extend([*stmt.then, *stmt.otherwise])
            if stmt.kind != 'let' or stmt.span.end > offset:
                continue
            path = paths.get(stmt.name.span.start, ())
            if not path or cursor_path[:len(path)] != path:
                continue
            typ = (stmt.expr.typ if checked else stmt.annotation.text if stmt.annotation else
                   stmt.expr.value if stmt.expr.kind == 'record' else '')
            locals[stmt.name.text] = (typ, descriptions.get(stmt.name.span, f"let {stmt.name.text}"))

    candidates = {}

    def add(name, kind, detail, semantic=False):
        if name.startswith(prefix):
            if semantic and not checked:
                detail += " (unchecked source)"
            candidates[name, kind] = {"label": name, "kind": kind, "detail": detail}

    before = [t for t in tokens if t.kind != 'eof' and t.span.end <= start]
    records = {r.name.text: r for r in program.records}
    if before and before[-1].kind == '.':
        # Restrict field suggestions to a named local/parameter receiver.
        # Chained fields and temporary/call receivers need richer queries later.
        receiver = before[-2] if len(before) >= 2 else None
        if receiver and receiver.kind == 'id' and not (len(before) >= 3 and before[-3].kind == '.'):
            typ = locals.get(receiver.text, ('', ''))[0]
            record = records.get(base_type(typ))
            if record:
                for name, typ in record.fields:
                    add(name.text, 5, f"{name.text}: {typ.text}", semantic=True)
    else:
        for name in KEYWORDS:
            add(name, 14, "Talven keyword")
        for name in SCALARS | {'str'}:
            add(name, 7, f"type {name}")
        add('print', 3, PRINT_SIGNATURE + " (requires --console)")
        for record in program.records:
            add(record.name.text, 7, f"struct {record.name.text} (move-only)", semantic=True)
        for fn in program.functions:
            add(fn.name.text, 3, fn.signature(), semantic=True)
        for name, (_, detail) in locals.items():
            add(name, 6, detail, semantic=True)

    result = {"isIncomplete": False, "items": []}
    used = len(json.dumps(result, separators=(',', ':')).encode('utf-8'))
    edit_range = source_range(source, Span(start, end))
    for item in sorted(candidates.values(), key=lambda v: (v['label'], v['kind'])):
        item.update(filterText=item['label'], insertTextFormat=1,
                    textEdit={"range": edit_range, "newText": item['label']},
                    data={"documentVersion": version})
        size = len(json.dumps(item, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 1
        if len(result['items']) >= MAX_COMPLETIONS or used + size > MAX_COMPLETION_BYTES:
            result['isIncomplete'] = True
            continue
        result['items'].append(item)
        used += size
    return result
