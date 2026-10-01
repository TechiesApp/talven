"""Full current-document semantic tokens from shared lexing and checked references.

No token-result cache, alternate resolver, file access, or source execution. Invalid
documents retain lexical colors but never inherit an older semantic classification.
"""

from .frontend import KEYWORDS, SCALARS, CompileError, lex

TOKEN_TYPES = ['keyword', 'number', 'string', 'comment', 'operator', 'type',
               'function', 'variable', 'parameter', 'property']
TOKEN_MODIFIERS = ['declaration', 'modification', 'defaultLibrary']
TYPE = {name: index for index, name in enumerate(TOKEN_TYPES)}
DECLARATION, MODIFICATION, DEFAULT_LIBRARY = 1, 2, 4
OPERATORS = {'->', '=', '+', '-', '*', '/', '%', '!', '&', '==', '!=', '<', '>', '<=', '>=', '&&', '||'}


def semantic_tokens(source, analysis=None):
    try:
        tokens = lex(source, include_comments=True)
    except (CompileError, UnicodeError):
        return {'data': []}
    if analysis is not None and analysis.source != source:
        analysis = None
    roles, writes = {}, set()
    if analysis is not None:
        definitions = {}
        for record in analysis.program.records:
            definitions[record.name.span] = 'type'
            definitions.update((name.span, 'property') for name, _ in record.fields)
        for fn in analysis.program.functions:
            definitions[fn.name.span] = 'function'
            definitions.update((name.span, 'parameter') for name, _ in fn.params)
            pending = list(fn.body)
            while pending:
                stmt = pending.pop()
                pending.extend([*stmt.then, *stmt.otherwise])
                if stmt.kind == 'let':
                    definitions[stmt.name.span] = 'variable'
                elif stmt.kind == 'assign':
                    writes.add(stmt.target.span.end)
        # Borrowed type reference ranges also include &/mut. Classify only the
        # trailing identifier, leaving operator/keyword tokens separate.
        identifiers = {t.span.end: t for t in tokens if t.kind == 'id'}
        for ref in analysis.references:
            token = identifiers.get(ref.span.end)
            if token is None or token.span.start < ref.span.start:
                continue
            role = definitions.get(ref.definition)
            if role:
                mask = DECLARATION if token.span == ref.definition else 0
                roles[token.span] = (role, mask)
            elif ref.definition is None and token.text == 'print':
                roles[token.span] = ('function', DEFAULT_LIBRARY)

    data = []
    line = character = previous_line = previous_character = consumed = 0
    for token in tokens:
        gap = source[consumed:token.span.start]
        if '\n' in gap:
            line += gap.count('\n')
            character = len(gap.rsplit('\n', 1)[-1].encode('utf-16-le')) // 2
        else:
            character += len(gap.encode('utf-16-le')) // 2
        length = len(token.text.encode('utf-16-le')) // 2
        role, mask = roles.get(token.span, (None, 0))
        if role is None:
            if token.kind in KEYWORDS:
                role = 'keyword'
            elif token.kind in ('int', 'text', 'comment'):
                role = {'int': 'number', 'text': 'string', 'comment': 'comment'}[token.kind]
            elif token.kind in OPERATORS:
                role = 'operator'
            elif token.kind == 'id' and token.text in SCALARS | {'str'}:
                role, mask = 'type', DEFAULT_LIBRARY
        if role is not None:
            if token.kind == 'id' and token.span.end in writes:
                mask |= MODIFICATION
            data.extend([line - previous_line,
                         character - previous_character if line == previous_line else character,
                         length, TYPE[role], mask])
            previous_line, previous_character = line, character
        character += length
        consumed = token.span.end
    return {'data': data}
