"""Deterministic compiler-derived facts; no disk cache or model-provider calls."""

import hashlib
import json
from pathlib import Path
import platform
import unicodedata

from . import FORMAT_PROFILE, PROFILE, VERSION
from .frontend import Analysis, BUILTINS, COPY_TYPES, PRINT_SIGNATURE, CompileError, Expr, Function, Span, Statement, base_type, borrow_mode

SCHEMA = "talven.context.v2"


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def compiler_hash() -> str:
    root = Path(__file__).parent
    entries = [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in sorted(root.glob("*.py"))]
    return hashlib.sha256(encode(entries).encode("utf-8")).hexdigest()


def function_fact(fn: Function) -> dict:
    parameters = []
    for name, typ in fn.params:
        mode = borrow_mode(typ.text)
        parameter = {"name": name.text, "type": typ.text,
                     "passing": f"borrow-{mode}" if mode else "copy" if typ.text in COPY_TYPES else "move"}
        if mode:
            parameter.update(scope="call", may_write=mode == "exclusive", escapes=False)
        parameters.append(parameter)
    return {"kind": "function", "name": fn.name.text, "signature": fn.signature(),
            "parameters": parameters, "returns": fn.result.text,
            "calls": sorted(fn.calls)}


def expressions(body: list[Statement]):
    def walk(expr: Expr):
        yield expr
        for child in expr.args:
            yield from walk(child)
        for _, child in expr.fields:
            yield from walk(child)
    for statement in body:
        yield from walk(statement.expr)
        if statement.target is not None:
            yield from walk(statement.target)
        yield from expressions(statement.then)
        yield from expressions(statement.otherwise)


def context(analysis: Analysis, symbol: str | None = None, max_bytes: int = 16384,
            expected_source_hash: str | None = None, freestanding: bool = False,
            include_body: bool = False) -> str:
    revision = source_hash(analysis.source)
    if expected_source_hash is not None and expected_source_hash != revision:
        raise CompileError("E0501", "Source revision changed; request fresh context before editing", Span(0, 0))
    if max_bytes < 1 or max_bytes > 1024 * 1024:
        raise CompileError("E0502", "Context budget must be between 1 byte and 1 MiB", Span(0, 0))
    if symbol is not None and symbol not in analysis.functions and symbol not in analysis.records:
        raise CompileError("E0101", f"Unknown symbol {symbol}", Span(0, 0))
    selected = sorted(analysis.functions if symbol is None else [symbol] if symbol in analysis.functions else [])
    dependencies = sorted({call for name in selected for call in analysis.functions[name].calls} - set(selected) - BUILTINS)
    builtin_names = {call for name in selected + dependencies for call in analysis.functions[name].calls} & BUILTINS
    builtins = ([{"kind": "builtin", "name": "print", "signature": PRINT_SIGNATURE,
                  "parameters": [{"name": "text", "type": "str", "passing": "copy"}], "returns": "i32",
                  "requires": "posix-console", "result": "0 after all bytes written; 1 on returned write failure or zero progress",
                  "effects": "blocking stdout writes; partial output possible; host signals unchanged"}]
                if "print" in builtin_names else [])
    used_records = set(analysis.records) if symbol is None else {symbol} if symbol in analysis.records else set()
    for name in selected + dependencies:
        fn = analysis.functions[name]
        used_records.update(base_type(t.text) for _, t in fn.params if base_type(t.text) in analysis.records)
        if fn.result.text in analysis.records:
            used_records.add(fn.result.text)
        if name in selected:
            used_records.update(base_type(expr.typ) for expr in expressions(fn.body) if base_type(expr.typ) in analysis.records)
    records = [{"kind": "record", "name": name, "ownership": "move-only",
                "fields": [{"name": n.text, "type": t.text} for n, t in analysis.records[name].fields]}
               for name in sorted(used_records)]
    inputs = {"schema": SCHEMA, "compiler_version": VERSION, "compiler_hash": compiler_hash(),
              "bootstrap_runtime": {"implementation": platform.python_implementation(),
                                    "version": platform.python_version(), "unicode": unicodedata.unidata_version},
              "source_hash": revision, "profile": PROFILE, "formatter_profile": FORMAT_PROFILE,
              "target": "c11-freestanding" if freestanding else "c11-hosted",
              "symbol": symbol, "include_body": include_body}
    result = {**inputs, "cache_key": hashlib.sha256(encode(inputs).encode("utf-8")).hexdigest(),
              "validation": "frontend-only", "functions": [function_fact(analysis.functions[n]) for n in selected],
              "dependencies": [function_fact(analysis.functions[n]) for n in dependencies],
              "builtins": builtins,
              "required_runtime": ["posix-console"] if any("print" in fn.calls for fn in analysis.functions.values()) else [],
              "records": records,
              "callers": sorted(name for name, fn in analysis.functions.items() if symbol in fn.calls),
              "rules": {"integers": "checked signed i32; divide and remainder truncate toward zero",
                        "evaluation": "left-to-right; && and || short-circuit",
                        "resources": "affine scalar-field records; call-scoped borrows; no heap, destructors, or FFI",
                        "text": "str copies a static immutable UTF-8 byte view; embedded NUL is data; no text operators",
                        "borrows": "explicit named-record arguments; shared reads or one exclusive writer; references cannot escape",
                        "mutation": "scalar fields of let mut owners or &mut parameters; assignment evaluates its value before storing",
                        "trust": "hashes identify inputs; they do not authenticate stored or remote content"}}
    if include_body:
        for fact in result["functions"]:
            fn = analysis.functions[fact["name"]]
            fact["untrusted_source_text"] = analysis.source[fn.span.start:fn.span.end]
    encoded = encode(result)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise CompileError("E0502", "Context exceeds byte budget; select one symbol or increase the budget", Span(0, 0))
    return encoded
