"""Revision-checked, read-only source snapshots and candidate previews."""

from pathlib import Path
import platform
import re
import unicodedata

from . import PROFILE
from .context import compiler_hash, encode, function_fact, source_hash
from .frontend import Analysis, CompileError, MAX_SOURCE_BYTES, Span, analyze

SNAPSHOT_SCHEMA = "talven.edit-snapshot.v1"
VALIDATION_SCHEMA = "talven.edit-validation.v1"
MAX_OUTPUT_BYTES = 1024 * 1024
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _runtime() -> dict:
    return {"implementation": platform.python_implementation(),
            "version": platform.python_version(), "unicode": unicodedata.unidata_version}


def _diagnostic(code: str, message: str, input_name: str, source: str = "") -> dict:
    result = CompileError(code, message, Span(0, 0)).diagnostic(source)
    result["input"] = input_name
    return result


def _read(path: Path, input_name: str) -> tuple[bytes | None, str | None, dict | None]:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            return None, None, _diagnostic("E0005", "Source exceeds the 256 KiB prototype limit", input_name)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None, None, _diagnostic("E0901", f"{input_name.capitalize()} is not valid UTF-8", input_name)
        return data, text, None
    except OSError as error:
        message = str(error)
        if len(message) > 240:
            message = message[:237] + "..."
        return None, None, _diagnostic("E0901", message, input_name)


def _valid_budget(max_bytes: object) -> bool:
    return isinstance(max_bytes, int) and not isinstance(max_bytes, bool) and 1 <= max_bytes <= MAX_OUTPUT_BYTES


def _compiler_identity() -> tuple[str | None, dict | None]:
    try:
        return compiler_hash(), None
    except (OSError, UnicodeError) as error:
        message = str(error)
        if len(message) > 240:
            message = message[:237] + "..."
        return None, _diagnostic("E0901", message, "compiler")


def _snapshot_failure(*, diagnostic: dict, revision: str | None = None,
                      compiler: str | None = None, source_bytes: int | None = None) -> dict:
    return {"schema": SNAPSHOT_SCHEMA, "ok": False, "validation": "not-run",
            "source_hash": revision, "compiler_hash": compiler, "profile": PROFILE,
            "bootstrap_runtime": _runtime(), "source_bytes": source_bytes,
            "diagnostics": [diagnostic]}


def snapshot_source(source_path: Path, *, include_source: bool = False,
                    max_bytes: int = 16384) -> dict:
    """Return a deterministic identity receipt without parsing the source."""
    if not _valid_budget(max_bytes):
        return _snapshot_failure(diagnostic=_diagnostic(
            "E0701", "Output budget must be an integer between 1 byte and 1 MiB", "request"))
    initial_compiler, compiler_error = _compiler_identity()
    if compiler_error:
        return _snapshot_failure(diagnostic=compiler_error)
    data, text, error = _read(source_path, "source")
    if error:
        return _snapshot_failure(diagnostic=error, compiler=initial_compiler)
    revision = source_hash(text)
    current, _, error = _read(source_path, "source")
    if error:
        return _snapshot_failure(diagnostic=error, revision=revision,
                                 compiler=initial_compiler, source_bytes=len(data))
    if current != data:
        return _snapshot_failure(diagnostic=_diagnostic(
            "E0501", "Source changed before snapshot could be returned", "source"),
            revision=revision, compiler=initial_compiler, source_bytes=len(data))
    current_compiler, compiler_error = _compiler_identity()
    if compiler_error:
        return _snapshot_failure(diagnostic=compiler_error, revision=revision,
                                 compiler=initial_compiler, source_bytes=len(data))
    if current_compiler != initial_compiler:
        return _snapshot_failure(diagnostic=_diagnostic(
            "E0702", "Compiler revision changed before snapshot could be returned", "compiler"),
            revision=revision, compiler=current_compiler, source_bytes=len(data))
    result = {"schema": SNAPSHOT_SCHEMA, "ok": True, "validation": "not-run",
              "source_hash": revision, "compiler_hash": initial_compiler, "profile": PROFILE,
              "bootstrap_runtime": _runtime(), "source_bytes": len(data), "diagnostics": []}
    if include_source:
        result["untrusted_source_text"] = text
    if len(encode(result).encode("utf-8")) > max_bytes:
        return _snapshot_failure(diagnostic=_diagnostic(
            "E0703", "Snapshot exceeds byte budget", "request"), revision=revision,
            compiler=initial_compiler, source_bytes=len(data))
    return result


def _validation_base(expected_source_hash: str | None,
                     expected_compiler_hash: str | None) -> dict:
    return {"schema": VALIDATION_SCHEMA, "ok": False, "validation": "frontend-only",
            "source_hash": None, "candidate_hash": None, "compiler_hash": None,
            "expected_source_hash": expected_source_hash,
            "expected_compiler_hash": expected_compiler_hash, "profile": PROFILE,
            "bootstrap_runtime": _runtime(), "source_bytes": None, "candidate_bytes": None,
            "candidate_changed": None, "base": None, "candidate": None, "changes": None,
            "diagnostics": []}


def _frontend(source: str) -> tuple[Analysis | None, dict]:
    try:
        return analyze(source), {"ok": True, "diagnostics": []}
    except CompileError as error:
        return None, {"ok": False, "diagnostics": [error.diagnostic(source)]}


def _contract_facts(analysis: Analysis) -> dict[tuple[str, str], dict]:
    facts = {}
    for name, fn in analysis.functions.items():
        fact = function_fact(fn)
        fact.pop("calls", None)
        facts[("function", name)] = fact
    for name, record in analysis.records.items():
        facts[("record", name)] = {"kind": "record", "name": name, "ownership": "move-only",
                                    "fields": [{"name": field.text, "type": typ.text}
                                               for field, typ in record.fields]}
    return facts


def _changes(before: Analysis, after: Analysis) -> dict:
    base, candidate = _contract_facts(before), _contract_facts(after)
    shared = sorted(base.keys() & candidate.keys())
    return {
        "added": [candidate[key] for key in sorted(candidate.keys() - base.keys())],
        "removed": [base[key] for key in sorted(base.keys() - candidate.keys())],
        "contracts_changed": [{"kind": key[0], "name": key[1],
                               "before": base[key], "after": candidate[key]}
                              for key in shared if base[key] != candidate[key]],
        "calls_changed": [{"name": name, "before": sorted(before.functions[name].calls),
                           "after": sorted(after.functions[name].calls)}
                          for name in sorted(before.functions.keys() & after.functions.keys())
                          if before.functions[name].calls != after.functions[name].calls]}


def validate_edit(source_path: Path, candidate_path: Path, *, expected_source_hash: str,
                  expected_compiler_hash: str, max_bytes: int = 16384) -> dict:
    """Check pinned revisions and preview a candidate through the shared frontend."""
    valid_source_hash = isinstance(expected_source_hash, str) and HASH_PATTERN.fullmatch(expected_source_hash)
    valid_compiler_hash = isinstance(expected_compiler_hash, str) and HASH_PATTERN.fullmatch(expected_compiler_hash)
    result = _validation_base(expected_source_hash if valid_source_hash else None,
                              expected_compiler_hash if valid_compiler_hash else None)
    if not valid_source_hash or not valid_compiler_hash or not _valid_budget(max_bytes):
        result["diagnostics"] = [_diagnostic(
            "E0701", "Expected hashes must be 64 lowercase hexadecimal characters and output budget must be between 1 byte and 1 MiB",
            "request")]
        return result
    observed_compiler, compiler_error = _compiler_identity()
    if compiler_error:
        result["diagnostics"] = [compiler_error]
        return result
    result["compiler_hash"] = observed_compiler
    if observed_compiler != expected_compiler_hash:
        result["diagnostics"] = [_diagnostic("E0702", "Compiler revision changed; request a fresh snapshot", "compiler")]
        return result
    source_data, source, error = _read(source_path, "source")
    if error:
        result["diagnostics"] = [error]
        return result
    result.update(source_hash=source_hash(source), source_bytes=len(source_data))
    if result["source_hash"] != expected_source_hash:
        result["diagnostics"] = [_diagnostic("E0501", "Source revision changed; request a fresh snapshot", "source")]
        return result
    candidate_data, candidate, error = _read(candidate_path, "candidate")
    if error:
        result["diagnostics"] = [error]
        return result
    result.update(candidate_hash=source_hash(candidate), candidate_bytes=len(candidate_data),
                  candidate_changed=candidate_data != source_data)
    base_analysis, result["base"] = _frontend(source)
    candidate_analysis, result["candidate"] = _frontend(candidate)
    if base_analysis is not None and candidate_analysis is not None:
        result["changes"] = _changes(base_analysis, candidate_analysis)
    current_source, _, source_error = _read(source_path, "source")
    current_candidate, _, candidate_error = _read(candidate_path, "candidate")
    if source_error or candidate_error:
        result["base"] = result["candidate"] = result["changes"] = None
        result["diagnostics"] = [source_error or candidate_error]
        return result
    if current_source != source_data or current_candidate != candidate_data:
        result["base"] = result["candidate"] = result["changes"] = None
        changed_input = "source" if current_source != source_data else "candidate"
        result["diagnostics"] = [_diagnostic("E0501", f"{changed_input.capitalize()} changed during validation", changed_input)]
        return result
    current_compiler, compiler_error = _compiler_identity()
    if compiler_error:
        result["base"] = result["candidate"] = result["changes"] = None
        result["diagnostics"] = [compiler_error]
        return result
    if current_compiler != observed_compiler:
        result["compiler_hash"] = current_compiler
        result["base"] = result["candidate"] = result["changes"] = None
        result["diagnostics"] = [_diagnostic("E0702", "Compiler revision changed during validation", "compiler")]
        return result
    result["ok"] = result["candidate"]["ok"]
    if len(encode(result).encode("utf-8")) > max_bytes:
        result.update(ok=False, base=None, candidate=None, changes=None)
        result["diagnostics"] = [_diagnostic("E0703", "Validation receipt exceeds byte budget", "request")]
    return result
