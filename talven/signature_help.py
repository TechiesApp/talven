"""Current-document call contracts from shared syntax and checked facts."""

import json

from .context import function_fact
from .frontend import PRINT_SIGNATURE, CompileError, Parser, _check_depth, lex

MAX_SIGNATURE_BYTES = 64 * 1024


def signature_help(source, offset, analysis=None):
    if type(offset) is not int or not 0 <= offset <= len(source):
        raise ValueError('Invalid signature-help position')
    try:
        tokens = lex(source, include_comments=True)
        if any(t.kind == 'text' and t.span.start < offset < t.span.end
               or t.kind == 'comment' and t.span.start <= offset <= t.span.end for t in tokens):
            return None
        tokens = [t for t in tokens if t.kind != 'comment']
        if analysis is not None and analysis.source != source:
            analysis = None
        program = analysis.program if analysis is not None else Parser(tokens, recover=True).program()
        _check_depth(program)
    except (CompileError, RecursionError, UnicodeError):
        return None

    # Only commas belonging directly to a call's parentheses advance its
    # argument. Record initializers, grouping and nested calls have own frames.
    stack = []
    for index, token in enumerate(tokens):
        if token.kind == 'eof' or token.span.end > offset:
            break
        if token.kind in ('(', '{'):
            callee = None
            if token.kind == '(' and index and tokens[index - 1].kind == 'id':
                prior = tokens[index - 2].kind if index >= 2 else None
                if prior != 'fn':
                    # Member calls are outside the implemented language.
                    callee = '' if prior == '.' else tokens[index - 1].text
            stack.append([token.kind, callee, 0])
        elif token.kind in (')', '}'):
            expected = '(' if token.kind == ')' else '{'
            if not stack or stack[-1][0] != expected:
                return None
            stack.pop()
        elif token.kind == ',' and stack and stack[-1][0] == '(':
            stack[-1][2] += 1
    call = next((frame for frame in reversed(stack) if frame[1] is not None), None)
    if call is None:
        return None
    name, argument = call[1:]
    if name == 'print':
        signature = {'label': PRINT_SIGNATURE,
                     'documentation': 'Built-in contract; requires --console. The current call is not validated by signature help.',
                     'parameters': [{'label': 'text: str', 'documentation': 'Copied static UTF-8 text view.'}]}
    else:
        matches = [fn for fn in program.functions if fn.name.text == name]
        if len(matches) != 1:
            return None
        fn = matches[0]
        checked = analysis is not None
        signature = {'label': fn.signature(), 'parameters': [],
                     'documentation': ('Checked current declaration; the current call still requires type/move/loan validation.'
                                       if checked else 'Unchecked current source declaration; no type/move/loan validation.')}
        for (param, typ), fact in zip(fn.params, function_fact(fn)['parameters']):
            if not checked:
                detail = 'Unchecked current source: declared parameter type only.'
            elif fact['passing'].startswith('borrow-'):
                mode = 'Exclusive' if fact['may_write'] else 'Shared'
                permission = 'write' if fact['may_write'] else 'read'
                detail = f'{mode} borrow; {permission} permission; call-scoped; cannot escape.'
            else:
                detail = 'Copied value.' if fact['passing'] == 'copy' else 'Moved record value.'
            signature['parameters'].append({'label': f'{param.text}: {typ.text}', 'documentation': detail})
    # Zero parameters have no active index. For extra/trailing arguments keep
    # the last declared parameter visible without claiming argument validity.
    result = {'signatures': [signature], 'activeSignature': 0}
    if signature['parameters']:
        result['activeParameter'] = min(argument, len(signature['parameters']) - 1)
    if len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()) > MAX_SIGNATURE_BYTES:
        return None
    return result
