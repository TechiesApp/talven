"""Strict adapter boundary; only source replacements can cross it."""

import hashlib
import json
from pathlib import Path
import shutil

from talven.frontend import MAX_SOURCE_BYTES
from .metrics import validate_usage


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
        # JSON escapes can contain lone surrogates that cannot be recorded as
        # UTF-8 prompts or source. Reject them at the protocol boundary.
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return result
    except (RecursionError, UnicodeError) as error:
        raise ValueError("Invalid or excessively nested JSON") from error


def read_config(path):
    path = Path(path).resolve()
    config = strict_json(path.read_text(encoding="utf-8"))
    required = {"schema", "kind", "provider", "model", "tokenizer", "settings", "command", "artifacts"}
    if not isinstance(config, dict) or set(config) != required or config["schema"] != "talven.eval.adapter.v1":
        raise ValueError("Adapter config must match talven.eval.adapter.v1")
    if config["kind"] not in ("live", "fixture"):
        raise ValueError("Adapter kind must be live or fixture")
    for key in ("provider", "model", "tokenizer"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f"Adapter requires an explicit {key} version/identity")
    if not isinstance(config["settings"], dict):
        raise ValueError("settings must be an object")
    command = config["command"]
    if not isinstance(command, list) or not command or any(not isinstance(p, str) or not p for p in command):
        raise ValueError("command must be a nonempty argv array")
    executable = shutil.which(command[0])
    if executable is None:
        raise ValueError(f"Adapter executable not found: {command[0]}")
    command[0] = str(Path(executable).resolve())
    artifacts = config["artifacts"]
    if not isinstance(artifacts, list) or any(not isinstance(p, str) for p in artifacts):
        raise ValueError("artifacts must list adapter code/configuration files to fingerprint")
    config["artifact_hashes"] = {}
    for entry in [command[0], *artifacts]:
        artifact = Path(entry)
        if not artifact.is_absolute():
            artifact = path.parent / artifact
        artifact = artifact.resolve(strict=True)
        config["artifact_hashes"][str(artifact)] = digest(artifact.read_bytes())
    # Arguments remain literal. Use absolute paths because every call has a fresh cwd.
    config["config_sha256"] = digest(path.read_bytes())
    return config


def parse_response(text):
    value = strict_json(text)
    if not isinstance(value, dict) or value.get("schema") != "talven.eval.response.v1":
        raise ValueError("Response must match talven.eval.response.v1")
    if value.keys() - {"schema", "edits", "usage", "provider_metadata"}:
        raise ValueError("Unrecognized response fields")
    usage = validate_usage(value.get("usage"))
    metadata = value.get("provider_metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("provider_metadata must be an object or null")
    return value, usage


def candidate_source(response):
    edits = response.get("edits")
    if not isinstance(edits, dict) or set(edits) != {"task.tal"}:
        raise ValueError("Only one complete replacement of task.tal is allowed")
    source = edits["task.tal"]
    if not isinstance(source, str):
        raise ValueError("task.tal replacement must be UTF-8 source text")
    try:
        size = len(source.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError("task.tal contains invalid Unicode") from error
    if size > MAX_SOURCE_BYTES:
        raise ValueError("task.tal exceeds the compiler's 256 KiB source limit")
    return source
