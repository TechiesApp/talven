"""Explicit supplied-block profile and exact embedded runtime inputs."""
import hashlib
from pathlib import Path

from .context import compiler_hash, encode, function_fact, source_hash
from .frontend import (Checker, CompileError, Outcome, Parser, Record, Span, Token,
                       _check_depth, _recursion_limit, base_type, borrow_mode, lex,
                       source_range)

PROFILE = "m2-supplied-blocks-v1"
BUILTIN_NAMES = {"Block", "Allocation", "ByteRead", "ByteWrite", "reserve", "release", "read_byte", "write_byte"}
RUNTIME_PATHS = ("experiments/supplied-storage/runtime.h", "experiments/supplied-storage/source-runtime.c")


def runtime_sources():
    root = Path(__file__).resolve().parent.parent
    return tuple((root / path).read_bytes().decode("utf-8") for path in RUNTIME_PATHS)


def runtime_identity():
    root = Path(__file__).resolve().parent.parent
    return [{"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
            for path in RUNTIME_PATHS]


def builtin_types():
    def token(name):
        return Token("id", name, Span(0, 0))
    def outcome(name, variants):
        return Outcome(token(name), [], Span(0, 0),
                       [(token(v), token(p) if p else None) for v, p in variants])
    return {"Block": Record(token("Block"), [], Span(0, 0)),
            "Allocation": outcome("Allocation", [("Granted", "Block"), ("InvalidRequest", None), ("Exhausted", None)]),
            "ByteRead": outcome("ByteRead", [("Value", "i32"), ("OutOfBounds", None)]),
            "ByteWrite": outcome("ByteWrite", [("Written", None), ("OutOfBounds", None), ("InvalidByte", None)])}


def intrinsic_facts():
    """Public contracts of compiler operations, independent of observed execution."""
    contracts = (
        ("reserve", ("region", "size", "alignment"), ("region", "i32", "i32"), "Allocation"),
        ("release", ("block",), ("Block",), "i32"),
        ("read_byte", ("block", "index"), ("&Block", "i32"), "ByteRead"),
        ("write_byte", ("block", "index", "value"), ("&mut Block", "i32", "i32"), "ByteWrite"),
    )
    types = builtin_types()
    facts = []
    for name, names, params, result in contracts:
        parameters = []
        for parameter_name, typ in zip(names, params):
            mode = borrow_mode(typ)
            parameter = {"name": parameter_name, "type": typ,
                         "passing": f"borrow-{mode}" if mode else
                                    "lexical-capability" if typ == "region" else
                                    "move-linear" if typ == "Block" else "copy"}
            if mode:
                parameter.update(borrow_scope="call", may_write=mode == "exclusive", escapes=False)
            elif typ == "Block":
                parameter.update(effect="consume-and-release", escapes=False)
            elif typ == "region":
                parameter.update(escapes=False)
            parameters.append(parameter)
        signature_parameters = ", ".join(n if t == "region" else f"{n}: {t}" for n, t in zip(names, params))
        fact = {"name": name, "signature": f"fn {name}({signature_parameters}) -> {result}",
                "parameters": parameters, "returns": result,
                "typed_variants": [v.text for v, _ in types[result].variants] if result in types else []}
        if name == "reserve":
            fact.update(requires={"origin_state": "free"}, effect="pending origin obligation")
        elif name == "release":
            fact.update(effect="consume-and-release", normal_return=0)
        else:
            fact.update(borrow_scope="call", effect="read bytes" if name == "read_byte" else "write bytes")
        facts.append(fact)
    return facts


def resource_tokens(tokens):
    return [Token(t.text, t.text, t.span) if t.kind == "id" and t.text in ("outcome", "match", "region") else t
            for t in tokens]


def parse_resources(source):
    try:
        program = Parser(resource_tokens(lex(source)), resources=True).program()
        _check_depth(program)
        return program
    except RecursionError:
        raise _recursion_limit() from None


def analyze_resources(source):
    try:
        return Checker(source, parse_resources(source), resources=True).check()
    except RecursionError:
        raise _recursion_limit() from None


def check_resource_expr(checker, expr, state):
    """Resource cases of the shared expression checker; ordinary cases fall through."""
    kind, value = expr.kind, expr.value
    if kind == "name" and value in state.regions:
        checker.error("E0320", "Region names are accepted only as the first argument to reserve", expr.span)
    if kind == "record" and value in ("Block", "Allocation"):
        checker.error("E0320", "Resource owners and reservations cannot be forged with record literals", expr.span)
    if kind == "call" and value in ("Block", "Allocation"):
        checker.error("E0320", "Resource owners and reservations have no callable constructor", expr.span)
    if kind == "field":
        place = expr.args[0]
        if place.kind == "name" and place.value in state.bindings and base_type(state.bindings[place.value].typ) == "Block":
            checker.lookup(place, state)
            checker.error("E0320", "Block is opaque and has no source fields", expr.span)
    if kind == "outcome" and value.startswith("Allocation::"):
        variant = value.split("::")[1]
        if variant in ("InvalidRequest", "Exhausted"):
            checker.error("E0320", "Allocation failures are produced only by reserve", expr.span)
        if variant != "Granted" or len(expr.args) != 1:
            checker.error("E0310", "Constructor payload must agree with its variant" if variant == "Granted" else f"Unknown variant {variant}", expr.span)
        child = expr.args[0]
        checker.same_type(checker.expr(child, state), "Block", child.span)
        expr.origin = child.origin
        state.resources[expr.origin] = "pending"
        checker.reference(Span(expr.span.start, expr.span.start + 10), None, "outcome Allocation (linear; origin-preserving)")
        checker.reference(Span(expr.span.start + 12, expr.span.start + len(value)), None, value)
        return "Allocation"
    if kind != "call" or value not in ("reserve", "release", "read_byte", "write_byte"):
        return None
    contracts = {"reserve": (["region", "i32", "i32"], "Allocation"),
                 "release": (["Block"], "i32"),
                 "read_byte": (["&Block", "i32"], "ByteRead"),
                 "write_byte": (["&mut Block", "i32", "i32"], "ByteWrite")}
    params, result = contracts[value]
    if len(expr.args) != len(params):
        checker.error("E0203", f"{value} expects {len(params)} arguments", expr.span)
    outer_loans = dict(state.loans)
    transferred = None
    try:
        for child, expected in zip(expr.args, params):
            if expected == "region":
                if child.kind != "name" or child.value not in state.regions:
                    checker.error("E0320", "reserve requires a lexical region name as its first argument", child.span)
                transferred = state.regions[child.value]
                if state.resources[transferred] != "free":
                    checker.error("E0321", "Region already has an outstanding owner or reservation", child.span)
                child.typ = "region"
                child.origin = transferred
                declaration_start = int(transferred.rsplit(":", 1)[1])
                checker.reference(child.span, Span(declaration_start, declaration_start + len(child.value)),
                                  f"region {child.value} (lexical)")
                continue
            if child.kind == "borrow":
                actual = checker.borrow(child, state)
            elif borrow_mode(expected):
                checker.error("E0304", f"Pass {expected} explicitly with &name or &mut name", child.span)
            else:
                actual = checker.expr(child, state)
            checker.same_type(actual, expected, child.span)
            if expected == "Block":
                transferred = child.origin
    finally:
        state.loans = outer_loans
    if value == "reserve":
        expr.origin = transferred
        state.resources[transferred] = "pending"
    elif value == "release":
        state.resources[transferred] = "free"
    checker.function.calls.add(value)
    checker.reference(Span(expr.span.start, expr.span.start + len(value)), None,
                      f"fn {value}({', '.join(params)}) -> {result} (supplied-block intrinsic)")
    return result


def resource_context(analysis, max_bytes=16384, expected_source_hash=None):
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576:
        raise CompileError("E0502", "Context budget must be 1..1048576 bytes", Span(0, 0))
    revision = source_hash(analysis.source)
    if expected_source_hash not in (None, revision):
        raise CompileError("E0501", "Source revision changed; request fresh context", Span(0, 0))
    records, outcomes, functions, origins = [], [], [], []
    for name, record in sorted(analysis.records.items()):
        if name == "Block":
            continue
        if isinstance(record, Outcome):
            outcomes.append({"name": name, "identity": name, "passing": "move", "must_handle": True,
                             "linear": name == "Allocation", "builtin": name in BUILTIN_NAMES,
                             "variants": [{"name": v.text, "payload": p.text if p else None, "tag": i}
                                          for i, (v, p) in enumerate(record.variants)]})
        else:
            records.append({"name": name, "fields": [{"name": n.text, "type": t.text} for n, t in record.fields]})
    for name, fn in sorted(analysis.functions.items()):
        fact = function_fact(fn)
        owning = []
        for parameter, (token, typ) in zip(fact["parameters"], fn.params):
            if typ.text == "Block":
                parameter.update(passing="move-linear", effect="consume-and-release", escapes=False)
                owning.append(token.text)
                origins.append({"identity": f"{name}:parameter:{token.span.start}", "function": name,
                                "name": token.text, "kind": "owning-parameter", "capacity": None,
                                "range": source_range(analysis.source, token.span)})
        fact["resource_effects"] = {"consume_and_release": owning, "normal_return_obligations": "all discharged"}
        functions.append(fact)
        pending = list(reversed(fn.body))
        while pending:
            stmt = pending.pop()
            if stmt.kind == "region":
                origins.append({"identity": f"{name}:region:{stmt.name.span.start}", "function": name,
                                "name": stmt.name.text, "kind": "lexical-region", "capacity": int(stmt.expr.value.lstrip("0") or "0"),
                                "range": source_range(analysis.source, stmt.name.span)})
            children = [*stmt.then, *stmt.otherwise, *(child for arm in stmt.arms for child in arm.body)]
            pending.extend(reversed(children))
    identities = runtime_identity()
    result = {"schema": "talven.resource-context.v1", "language_profile": PROFILE,
              "source_hash": revision, "compiler_hash": compiler_hash(), "validation": "frontend-only",
              "runtime_inputs": identities, "runtime_hash": source_hash(encode(identities)),
              "opaque_types": [{"name": "Block", "passing": "move-linear", "fields": [], "escapes": False}],
              "outcomes": outcomes, "records": records, "functions": functions, "origins": origins,
              "intrinsics": intrinsic_facts(),
              "bounds": {"regions_per_function": 8, "capacity_min": 1, "capacity_max": 4096, "alignment_max": 16,
                         "allowed_alignments": [1, 2, 4, 8, 16]},
              "rules": {"slots": "free, pending Allocation, live Block", "normal_exit": "release or checked delegation",
                        "match": "consumes; exhaustive; selected payload; preserves origin",
                        "borrow_scope": "call", "block_results": False, "allocation_parameters": False,
                        "allocation_results": False, "arithmetic_failure": "trap; no unwinding"}}
    if len(encode(result).encode("utf-8")) > max_bytes:
        raise CompileError("E0502", "Resource context exceeds requested byte budget", Span(0, 0))
    return result
