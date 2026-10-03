"""Explicit concrete-outcome profile on the shared parser and ownership checker."""
from .context import compiler_hash, encode, function_fact, source_hash
from .frontend import (Checker, CompileError, Outcome, Parser, Span, Token,
                       _check_depth, _recursion_limit, lex)

PROFILE = 'm2-concrete-outcomes-v1'


def outcome_tokens(tokens):
    return [Token(t.text, t.text, t.span) if t.kind == 'id' and t.text in ('outcome', 'match') else t
            for t in tokens]


def parse_outcomes(source):
    try:
        program = Parser(outcome_tokens(lex(source)), outcomes=True).program()
        _check_depth(program)
        return program
    except RecursionError:
        raise _recursion_limit() from None


def analyze_outcomes(source):
    try:
        return Checker(source, parse_outcomes(source)).check()
    except RecursionError:
        raise _recursion_limit() from None


def outcome_context(analysis, max_bytes=16384, expected_source_hash=None):
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
        raise CompileError('E0502', 'Context budget must be 1..1048576 bytes', Span(0, 0))
    if expected_source_hash not in (None, source_hash(analysis.source)):
        raise CompileError('E0501', 'Source revision changed; request fresh context', Span(0, 0))
    records, outcomes = [], []
    for name, record in sorted(analysis.records.items()):
        if isinstance(record, Outcome):
            outcomes.append({'name': name, 'identity': name, 'passing': 'move', 'must_handle': True,
                             'variants': [{'name': v.text, 'payload': p.text if p else None, 'tag': i}
                                          for i, (v, p) in enumerate(record.variants)]})
        else:
            records.append({'name': name, 'fields': [{'name': n.text, 'type': t.text} for n, t in record.fields]})
    result = {'schema': 'talven.outcome-context.v1', 'language_profile': PROFILE,
              'source_hash': source_hash(analysis.source), 'compiler_hash': compiler_hash(),
              'validation': 'frontend-only', 'outcomes': outcomes, 'records': records,
              'functions': [function_fact(fn) for _, fn in sorted(analysis.functions.items())],
              'rules': {'match': 'consumes; exhaustive; selected payload only',
                        'must_handle': 'match, return, or owning-parameter transfer on every path',
                        'arithmetic_failure': 'trap; no unwinding', 'outcome_borrowing': False}}
    if len(encode(result).encode('utf-8')) > max_bytes:
        raise CompileError('E0502', 'Outcome context exceeds requested byte budget', Span(0, 0))
    return result
