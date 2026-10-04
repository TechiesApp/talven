#!/usr/bin/env python3
"""Retain verified supplied-block production batch costs on the actual host."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_script("resource_cost_tooling", "measure-tooling.py")
native_checker = load_script("resource_cost_native", "measure-native-prototype.py")
# The validator imports its own tooling module; share the error/recorder types too.
native_checker.base = base
source_gate = load_script("resource_cost_gate", "check-resource-sanitizers.py")
from talven.resources import PROFILE, runtime_identity

CAPACITIES = (1, 32, 4096)
OPTIMIZATIONS = ("-O0", "-O2")
SHAPES = ("cycle", "reuse", "sequential")
SYMBOLS = tuple("tv_f_" + shape for shape in SHAPES)
FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", "-fno-lto"]
PERMITTED = {"abort", "memset", "bzero", "memcpy", "memmove", "stack_chk_fail",
             "stack_chk_guard", "chkstk_darwin", "GLOBAL_OFFSET_TABLE_"}
FIXTURES = ROOT / "experiments/resource-costs"


class Recorder(base.Recorder):
    """Use the shared raw recorder; only mark commands after semantic validation."""
    def command(self, argv, *, phase="verification", workload=None, operation=None):
        output, entry = super().command(argv, phase="captured", workload=workload, operation=operation)
        entry["phase"] = phase
        base.require(entry["stderr"]["bytes"] == 0, "command emitted stderr; see archived output")
        self.save()
        return output, entry


def accept(recorder, entry):
    entry["verified"] = True
    recorder.save()


def command(recorder, argv, *, validator=None, **metadata):
    output, entry = recorder.command([str(x) for x in argv], **metadata)
    if validator is None:
        base.require(output == b"", "unexpected command stdout")
        value = None
    else:
        value = validator(output)
    accept(recorder, entry)
    return value, entry


def strict_json(output):
    def pairs(items):
        result = {}
        for key, value in items:
            base.require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(output, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError) as error:
        raise base.MeasurementError("malformed JSON receipt") from error


def validate_iterations(iterations):
    base.require(type(iterations) is int and 4 <= iterations <= 10_000_000 and iterations % 4 == 0,
                 "iterations must be a multiple of four within 4..10000000")


def validate_timing(output, workload, iterations):
    value = strict_json(output)
    base.require(isinstance(value, dict) and set(value) == {
        "workload", "iterations", "checksum", "elapsed_ns", "resolution_ns"}, "incorrect timing receipt keys")
    base.require(all(type(item) is int for item in value.values()), "timing receipt requires integer fields")
    base.require(value["workload"] == workload and value["iterations"] == iterations,
                 "timing workload or iteration count mismatch")
    base.require(value["checksum"] == 10 * (iterations // 4), "timing checksum mismatch")
    base.require(value["resolution_ns"] > 0 and value["elapsed_ns"] >= 100 * value["resolution_ns"],
                 "batch duration must be at least 100 clock resolutions; increase --iterations")
    return value


def parse_stack_usage(output, selected=SYMBOLS):
    """GCC and Clang .su labels differ; the final colon component names C functions."""
    result = {}
    for line in output.decode("utf-8").splitlines():
        fields = line.split("\t")
        base.require(len(fields) == 3 and fields[2] == "static" and re.fullmatch(r"[0-9]+", fields[1]) is not None,
                     "malformed or dynamic compiler stack-usage record")
        label = fields[0]
        base.require(re.fullmatch(r".+:[0-9]+(?::[0-9]+)?:[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_0-9]+)*", label) is not None,
                     "malformed compiler stack-usage label")
        symbol = label.rsplit(":", 1)[-1]
        if symbol in selected:
            base.require(symbol not in result, "duplicate selected compiler stack record")
            result[symbol] = int(fields[1])
    base.require(set(result) == set(selected), "missing selected compiler stack-usage records")
    return result


def production_symbols(output):
    symbols = []
    for line in output.decode().splitlines():
        parts = line.split()
        base.require((len(parts) == 2 and parts[0] == "U" and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", parts[1]))
                     or (len(parts) == 1 and re.fullmatch(r"_[A-Za-z_0-9]+", parts[0])),
                     "malformed undefined-symbol inspection")
        symbols.append(parts[-1].lstrip("_"))
    base.require(not set(symbols) - PERMITTED, "unapproved production object dependency")
    return sorted(symbols)


def semantic_counts(capacity, shape, iterations):
    validate_iterations(iterations)
    base.require(capacity in CAPACITIES and shape in SHAPES, "invalid cost workload")
    multiplier = 1 if shape == "cycle" else 2
    rows = [{"size": 1, "alignment": 1, "index": 0},
            {"size": capacity, "alignment": 16, "index": capacity - 1},
            {"size": (capacity + 1) // 2, "alignment": 2, "index": (capacity + 1) // 2 - 1},
            {"size": capacity, "alignment": 8, "index": 0}]
    counts = {"calls": iterations,
              "region_initializations": iterations * (2 if shape == "sequential" else 1),
              "successful_reservations": iterations * multiplier,
              "reads": iterations * multiplier, "releases": iterations * multiplier,
              "writes": iterations if shape == "reuse" else 0,
              "initialized_visible_bytes": sum(row["size"] for row in rows) * (iterations // 4) * multiplier}
    return {"basis": "source-derived successful-path semantic counts; not measured memory traffic",
            "rows": rows, "batch": counts}


def summarize(samples, repetitions):
    result = []
    measured = [entry for entry in samples if entry["phase"] == "measured"]
    expected_count = len(CAPACITIES) * len(OPTIMIZATIONS) * len(SHAPES) * repetitions
    base.require(len(measured) == expected_count, "incomplete measured suite")
    for capacity in CAPACITIES:
        for optimization in OPTIMIZATIONS:
            for shape in SHAPES:
                group = [entry for entry in measured if entry.get("capacity") == capacity
                         and entry.get("optimization") == optimization and entry.get("shape") == shape]
                base.require(len(group) == repetitions and all(entry.get("verified") is True for entry in group),
                             "incomplete verified resource samples")
                base.require({entry.get("repetition") for entry in group} == set(range(1, repetitions + 1)),
                             "missing or duplicate measured repetition")
                durations = [entry["batch"]["elapsed_ns"] for entry in group]
                iterations = group[0]["batch"]["iterations"]
                base.require(all(entry["batch"]["iterations"] == iterations for entry in group), "mixed batch sizes")
                result.append({"capacity": capacity, "optimization": optimization, "shape": shape,
                               "samples": repetitions, "iterations_per_batch": iterations,
                               "min_batch_ns": min(durations), "median_batch_ns": statistics.median(durations),
                               "max_batch_ns": max(durations),
                               "min_ns_per_workload_iteration": min(durations) / iterations,
                               "median_ns_per_workload_iteration": statistics.median(durations) / iterations,
                               "max_ns_per_workload_iteration": max(durations) / iterations,
                               "resolution_ns": [entry["batch"]["resolution_ns"] for entry in group]})
    return result


def input_files():
    native = ROOT / "experiments/native-compiler"
    return sorted(set([*ROOT.joinpath("talven").glob("*.py"),
                       *[(native / name).resolve() for name in source_gate.NATIVE_SOURCES],
                       *[FIXTURES / name for name in ("workload.tal", "driver.c", "layout.c")],
                       *[ROOT / name for name in source_gate.SOURCES],
                       Path(__file__).resolve(), ROOT / "scripts/measure-tooling.py",
                       ROOT / "scripts/measure-native-prototype.py", ROOT / "experiments/tooling_workloads.py",
                       ROOT / "experiments/__init__.py", ROOT / "tests/test_resource_costs.py",
                       ROOT / "tests/test_resource_cost_fixture.py"]))


def verify_inputs(files, captured, current_files=None):
    base.require((input_files() if current_files is None else current_files) == files,
                 "measurement input set changed during run")
    base.require(all(path.read_bytes() == captured[path] for path in files),
                 "measurement input bytes changed during run")


def verify_artifacts(report, out):
    records = []
    for unit in report["units"]:
        records += [unit["source"], unit["generated_c"], *unit["artifacts"].values()]
    for entry in report["commands"]:
        records += [entry["stdout"], entry["stderr"]]
    records += [report[key] for key in ("reference_source_gate", "native_source_gate")]
    for record in records:
        base.require(base.fingerprint(out / record["path"]) == {key: record[key] for key in ("bytes", "sha256")},
                     "retained measurement artifact changed: " + record["path"])


def verify_native(info, binary, identity, initial_info=None):
    base.require(isinstance(info, dict), "native build identity must be an object")
    native_checker.verify_build_sources(info, ROOT / "experiments/native-compiler")
    base.require(isinstance(info.get("compiler_hash"), str) and bool(info["compiler_hash"]),
                 "missing native compiler identity")
    base.require(base.fingerprint(binary) == identity, "native executable changed during run")
    base.require(initial_info is None or info == initial_info, "native build identity changed during run")


def validate_check(output, native=False):
    value = strict_json(output)
    expected = {"schema": "talven.diagnostics.v1", "ok": True, "diagnostics": []}
    if native:
        expected["profile"] = "m2-supplied-blocks-v1"
    else:
        expected["language_profile"] = "m2-supplied-blocks-v1"
    base.require(isinstance(value, dict) and value == expected and value.get("ok") is True,
                 "producer did not accept original resource source")
    return value


def nonempty(output):
    base.require(bool(output.strip()), "empty tool identity or artifact output")
    return output.decode().strip()


def archive_artifact(path, out):
    base.require(path.is_file(), "missing compiled artifact: " + str(path))
    return {"path": str(path.relative_to(out)), **base.fingerprint(path)}


LAYOUT_FIELDS = {
    "tv_region": {"storage", "capacity", "instance", "live_size", "live_alignment", "occupied"},
    "tv_block": {"origin", "instance", "length", "alignment"},
    "tv_allocation": {"tag", "payload", "payload.block"},
    "tv_str": {"data", "len"},
    "tv_s_Allocation": {"tv_tag", "tv_payload", "tv_payload.tv_m_Granted"},
    "tv_s_ByteRead": {"tv_tag", "tv_payload", "tv_payload.tv_m_Value"},
    "tv_s_ByteWrite": {"tv_tag", "tv_payload", "tv_payload.tv_empty"},
}


def validate_layout(output):
    value = strict_json(output)
    base.require(isinstance(value, dict) and set(value) == set(LAYOUT_FIELDS), "incorrect layout structures")
    for name, fields in LAYOUT_FIELDS.items():
        record = value[name]
        base.require(isinstance(record, dict) and set(record) == {"size", "alignment", "offsets"}, "incorrect layout record")
        size, alignment, offsets = record["size"], record["alignment"], record["offsets"]
        base.require(type(size) is int and type(alignment) is int and 0 < size <= 4096
                     and 0 < alignment <= 4096 and alignment & (alignment - 1) == 0 and size % alignment == 0,
                     "invalid target layout size or alignment")
        base.require(isinstance(offsets, dict) and set(offsets) == fields
                     and all(type(offset) is int and 0 <= offset < size for offset in offsets.values()),
                     "invalid target layout fields or offsets")
        for field in fields:
            if "." in field:
                base.require(offsets[field] == offsets[field.split(".")[0]], "union payload offset mismatch")
    return value


def validate_size(output, system):
    text = nonempty(output)
    if system == "Darwin":
        base.require(re.search(r"^Segment(?:[ \t]+[A-Za-z_0-9]+)?[ \t]*:[ \t]*[0-9]+", text, re.MULTILINE) is not None
                     and re.search(r"^[ \t]*Section[ \t]+(?:\([A-Za-z_0-9]+,[ \t]*[A-Za-z_0-9]+\)|[A-Za-z_0-9]+):[ \t]*[0-9]+", text, re.MULTILINE) is not None
                     and re.search(r"^[ \t]*total[ \t]+[0-9]+", text, re.MULTILINE | re.IGNORECASE) is not None,
                     "unrecognized Darwin size -m section report")
    else:
        base.require(re.search(r"^section\s+size\s+addr\s*$", text, re.MULTILINE) is not None
                     and re.search(r"^Total\s+[0-9]+", text, re.MULTILINE) is not None,
                     "unrecognized Linux size -A section report")
    return text


def verify_bytes(path, expected):
    base.require(path.read_bytes() == expected, "source or fixture changed before/after use: " + str(path))


def verify_file(record, out):
    base.require(base.fingerprint(out / record["path"]) == {key: record[key] for key in ("bytes", "sha256")},
                 "compiled artifact changed before/after use: " + record["path"])


def effective_tool(output):
    value = nonempty(output)
    path = Path(value)
    base.require("\n" not in value and path.is_absolute() and path.is_file() and os.access(path, os.X_OK),
                 "dispatcher did not identify an executable tool")
    return path.resolve()


def sdk_path(output):
    value = nonempty(output)
    path = Path(value)
    base.require("\n" not in value and path.is_absolute() and path.is_dir(), "missing Darwin SDK directory")
    return path.resolve()


def measure_unit(recorder, args, cc, tools, directory, capacity, optimization, stable):
    settings = [*FLAGS, *getattr(args, "platform_flags", []), optimization, f"-DTEST_CAPACITY={capacity}"]
    ledger, probe = directory / "ledger", directory / "layout"
    generated, driver = directory / "generated.c", directory / "driver.c"
    subject, driver_object, program = directory / "generated.o", directory / "driver.o", directory / "program"
    unit = {"capacity": capacity, "optimization": optimization, "flags": settings,
            "source": archive_artifact(directory.parent / "workload.tal", recorder.out),
            "generated_c": archive_artifact(generated, recorder.out), "ledger_passed": False,
            "layout": None, "artifacts": {},
            "semantic_counts": {shape: semantic_counts(capacity, shape, args.iterations) for shape in SHAPES}}
    recorder.report["units"].append(unit)
    def remember(path):
        unit["artifacts"][path.name] = archive_artifact(path, recorder.out)
        recorder.save()
    def fixture_inputs():
        for path, data in stable.items():
            verify_bytes(path, data)
    def unchanged(path):
        verify_file(unit["artifacts"][path.name], recorder.out)
    fixture_inputs()
    remember(driver)
    remember(directory / "layout.c")
    command(recorder, [cc, *settings, "-DCOST_LEDGER", "-DTV_REGION_SOURCE_TEST",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all", driver, "-o", ledger],
            operation="cost-ledger-build")
    remember(ledger)
    fixture_inputs()
    unchanged(ledger)
    command(recorder, [ledger], operation="cost-ledger-acceptance")
    unchanged(ledger)
    unit["ledger_passed"] = True
    fixture_inputs()
    command(recorder, [cc, *settings, directory / "layout.c", "-o", probe], operation="layout-build")
    remember(probe)
    fixture_inputs()
    unchanged(probe)
    unit["layout"], _ = command(recorder, [probe], validator=validate_layout, operation="target-layout")
    unchanged(probe)
    fixture_inputs()
    command(recorder, [cc, *settings, "-Dmain=tv_generated_main", "-fstack-usage", "-c", generated, "-o", subject],
            operation="production-generated-object")
    remember(subject)
    stack_file = directory / "object-stack.su"
    (directory / "generated.su").replace(stack_file)
    remember(stack_file)
    unit["compiler_reported_static_stack_bytes"] = parse_stack_usage(stack_file.read_bytes())
    unit["stack_scope"] = "compiler-reported per-function static bytes; excludes callers, startup and recursive accumulation"
    fixture_inputs()
    command(recorder, [cc, *settings, "-c", driver, "-o", driver_object], operation="production-driver-object")
    remember(driver_object)
    fixture_inputs()
    unchanged(subject)
    unchanged(driver_object)
    command(recorder, [cc, *settings, subject, driver_object, "-o", program], operation="production-link")
    remember(program)
    unchanged(subject)
    unchanged(driver_object)
    assembly = directory / "generated.s"
    fixture_inputs()
    command(recorder, [cc, *settings, "-Dmain=tv_generated_main", "-fstack-usage", "-S", generated, "-o", assembly],
            operation="production-assembly")
    remember(assembly)
    remember(directory / "generated.su")
    fixture_inputs()
    base.require(parse_stack_usage((directory / "generated.su").read_bytes()) == unit["compiler_reported_static_stack_bytes"],
                 "object and assembly compiler stack reports differ")
    unchanged(subject)
    unit["production_undefined_symbols"], _ = command(recorder, [tools["nm"], "-u", subject],
                                                     validator=production_symbols, operation="production-dependencies")
    unchanged(subject)
    unit["dependency_scope"] = "generated production workload object; excludes hosted startup and driver"
    unit["permitted_undefined_symbols"] = sorted(PERMITTED)
    unit["section_reports"] = {}
    for artifact in (subject, driver_object, program):
        unchanged(artifact)
        size_flag = "-m" if platform.system() == "Darwin" else "-A"
        _, entry = command(recorder, [tools["size"], size_flag, artifact],
                           validator=lambda output: validate_size(output, platform.system()), operation="section-report")
        unchanged(artifact)
        unit["section_reports"][artifact.name] = {"format": "Darwin size -m" if size_flag == "-m" else "Linux size -A",
                                                 "raw_stdout": entry["stdout"], "summation": "not performed"}
    for phase, count in (("warmup", args.warmups), ("measured", args.repetitions)):
        for repetition in range(1, count + 1):
            for workload, shape in enumerate(SHAPES):
                unchanged(program)
                fixture_inputs()
                output, entry = recorder.command([str(program), str(workload), str(args.iterations)],
                                                 phase=phase, workload=shape, operation="production-batch")
                entry.update(capacity=capacity, optimization=optimization, shape=shape, repetition=repetition)
                entry["batch"] = validate_timing(output, workload, args.iterations)
                unchanged(program)
                fixture_inputs()
                accept(recorder, entry)
    base.require(all(path.read_bytes() == data for path, data in stable.items()),
                 "expanded source, generated C or driver changed during execution")
    for record in unit["artifacts"].values():
        base.require(base.fingerprint(recorder.out / record["path"]) == {key: record[key] for key in ("bytes", "sha256")},
                     "compiled production or acceptance artifact changed during execution")


def validate_source_gate(output, producer, identity, runtime):
    value = strict_json(output)
    base.require(isinstance(value, dict) and value.get("schema") == "talven.resource-source-check.v1"
                 and value.get("ok") is True and value.get("profile") == PROFILE
                 and value.get("producer") == producer and value.get("compiler_hash") == identity
                 and value.get("runtime_inputs") == runtime, "source sanitizer acceptance identity mismatch")
    base.require(value.get("production", {}).get("permitted_symbols") == sorted(PERMITTED),
                 "source acceptance permitted dependencies changed")
    base.require(value.get("positive_executions") == 12 and len(value.get("executions", [])) == 12
                 and all(entry.get("ledger_passed") is True for entry in value["executions"]),
                 "incomplete source sanitizer acceptance")
    return value


def run(args):
    out, cc, arch = base.preflight(args.out, args.repetitions, args.warmups, args.timeout, args.cc, args.expect_arch)
    validate_iterations(args.iterations)
    base.require(platform.system() in ("Linux", "Darwin") and arch in ("x86_64", "aarch64"),
                 "resource costs require an actual Linux/macOS x86-64/ARM64 host")
    binary = Path(args.native).expanduser().resolve()
    base.require(binary.is_file() and os.access(binary, os.X_OK), "--native must name an already-built executable")
    tool_paths = {"cc": Path(cc), "python": Path(sys.executable).resolve(), "native": binary}
    for name in ("nm", "size", "git"):
        resolved = shutil.which(name)
        base.require(resolved is not None, name + " is required; no skipped inspections")
        tool_paths[name] = Path(resolved).resolve()
    out.mkdir(parents=True)
    (out / "commands").mkdir()
    report = {"schema": "talven.resource-cost.v1", "profile": PROFILE,
              "complete": False, "passed": False, "summary": None, "error": None,
              "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
              "commands": [], "units": [], "inputs": {}, "tools": {},
              "environment_note": args.environment_note,
              "settings": {"capacities": list(CAPACITIES), "optimizations": list(OPTIMIZATIONS),
                           "iterations": args.iterations, "repetitions": args.repetitions,
                           "warmups": args.warmups, "timeout_seconds": args.timeout,
                           "production_flags": FLAGS, "lto": False,
                           "environment_overrides": base.ENVIRONMENT,
                           "order": "capacity, optimization, phase, repetition, shape; fixed sequential order",
                           "timing": "driver monotonic clock around successful complete-call batch; parsing and process launch excluded",
                           "minimum_batch_clock_resolutions": 100},
              "limits": ["OS caches and CPU frequency uncontrolled; no cold-cache claim",
                         "compiler-reported per-function static stack bytes are not whole-stack usage or physical total RAM",
                         "section sizes remain tool-native reports; no cross-format section total",
                         "source-derived initialization counts are not measured memory traffic",
                         "no isolated reserve/release latency, p99, RSS, agent benefit or broader M2 completion"]}
    recorder = Recorder(out, report, args.timeout)
    recorder.save()
    try:
        sdk_bytes = None
        sdk_settings = None
        args.platform_flags = []
        report["darwin_dispatch"] = {}
        if platform.system() == "Darwin":
            for name in ("cc", "nm", "size"):
                invocation = tool_paths[name]
                if invocation == Path("/usr/bin") / name:
                    dispatcher = Path("/usr/bin/xcrun")
                    base.require(dispatcher.is_file(), "Darwin dispatch resolver missing")
                    tool_paths["xcrun"] = dispatcher
                    resolved, _ = command(recorder, [dispatcher, "--find", invocation.name],
                                           validator=effective_tool, phase="provenance", operation="resolve-effective-tool")
                    report["darwin_dispatch"][name] = {"invocation": str(invocation), "effective": str(resolved)}
                    tool_paths[name + "_dispatch_wrapper"] = invocation
                    tool_paths[name] = resolved
            if "cc" in report["darwin_dispatch"]:
                sdk, _ = command(recorder, [tool_paths["xcrun"], "--sdk", "macosx", "--show-sdk-path"],
                                 validator=sdk_path, phase="provenance", operation="resolve-sdk-path")
                version, _ = command(recorder, [tool_paths["xcrun"], "--sdk", "macosx", "--show-sdk-version"],
                                     validator=nonempty, phase="provenance", operation="resolve-sdk-version")
                args.platform_flags = ["-isysroot", str(sdk)]
                report["sdk"] = {"path": str(sdk), "version": version, "settings": None,
                                 "closure_note": "SDKSettings.json identifies public SDK settings; the full SDK headers and linker closure are not archived or verified"}
                sdk_settings = sdk / "SDKSettings.json"
                if sdk_settings.is_file():
                    sdk_bytes = sdk_settings.read_bytes()
                    archived = out / "sdk" / "SDKSettings.json"
                    archived.parent.mkdir()
                    archived.write_bytes(sdk_bytes)
                    report["sdk"]["settings"] = {"source_path": str(sdk_settings),
                                                 **archive_artifact(archived, out), "text": sdk_bytes.decode("utf-8")}
                else:
                    report["sdk"]["settings_note"] = "SDKSettings.json is unavailable in this selected SDK"
        cc = str(tool_paths["cc"])
        report["settings"]["requested_cc"] = args.cc
        report["settings"]["platform_flags"] = args.platform_flags
        files = input_files()
        captured = {path: path.read_bytes() for path in files}
        for path, data in captured.items():
            relative = path.relative_to(ROOT)
            archived = out / "inputs" / relative
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(data)
            report["inputs"][str(relative)] = base.fingerprint(archived)
        for name, path in tool_paths.items():
            identity = base.fingerprint(path)
            archived = out / "tools" / name
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(path.read_bytes())
            base.require(base.fingerprint(archived) == identity, "tool executable changed while archiving")
            report["tools"][name] = {"path": str(path), "archive": str(archived.relative_to(out)), **identity}
        for name, argv in {"cc": [cc, "--version"], "python": [sys.executable, "--version"],
                           "native": [binary, "--version"], "git": [tool_paths["git"], "--version"],
                           "nm": [tool_paths["nm"], "--version"], "size": [tool_paths["size"], "--version"]}.items():
            if platform.system() == "Darwin" and name == "size":
                report["tools"][name]["version"] = None
                report["tools"][name]["version_note"] = "Apple size has no version query; executable bytes identify this tool"
                continue
            report["tools"][name]["version"], _ = command(recorder, argv, validator=nonempty, phase="provenance")
        if "xcrun" in tool_paths:
            report["tools"]["xcrun"]["version"], _ = command(recorder, [tool_paths["xcrun"], "--version"],
                                                                validator=nonempty, phase="provenance")
            for name in report["darwin_dispatch"]:
                report["tools"][name + "_dispatch_wrapper"]["version_note"] = "dispatch wrapper; effective tool identity recorded separately"
        for field, argv in {"git_revision": [tool_paths["git"], "rev-parse", "HEAD"],
                            "c_target": [cc, "-dumpmachine"]}.items():
            report[field], _ = command(recorder, argv, validator=nonempty, phase="provenance")
        c_arch = report["c_target"].split("-")[0].lower()
        c_arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(c_arch, c_arch)
        base.require(c_arch == arch, "selected C compiler target does not match actual host")
        status, entry = recorder.command([str(tool_paths["git"]), "status", "--porcelain", "--untracked-files=all"], phase="provenance")
        report["git_dirty"] = bool(status.strip())
        accept(recorder, entry)
        report["host"] = {"system": platform.system(), "release": platform.release(), "arch": arch,
                          "logical_cpus": os.cpu_count(), "python_version": platform.python_version(),
                          "cpu_model": base.cpu_model(recorder)}
        # cpu_model's Darwin identity command returns a string after empty-stderr validation.
        for entry in report["commands"]:
            if entry["argv"][0] == "/usr/sbin/sysctl":
                accept(recorder, entry)
        report["harness_clock"] = vars(base.time.get_clock_info("perf_counter"))
        info, info_entry = recorder.command([str(binary), "--build-info"], phase="provenance")
        info = strict_json(info)
        verify_native(info, binary, {key: report["tools"]["native"][key] for key in ("bytes", "sha256")})
        base.require(info.get("target", "").split("-")[0] == arch, "native target does not match actual host")
        accept(recorder, info_entry)
        report["native_build_info"] = info
        report["reference_compiler_hash"] = base.compiler_hash()
        report["runtime_inputs"] = runtime_identity()
        for producer in ("reference", "native"):
            gate_path = out / (producer + "-source-acceptance.json")
            argv = [sys.executable, "-B", str(ROOT / "scripts/check-resource-sanitizers.py")]
            if producer == "native":
                argv += ["--native", str(binary)]
            value, entry = command(recorder, argv,
                                   validator=lambda output, p=producer: validate_source_gate(
                                       output, p, info["compiler_hash"] if p == "native" else report["reference_compiler_hash"],
                                       report["runtime_inputs"]), phase="preflight", operation="source-sanitizer-gate")
            gate_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            report[producer + "_source_gate"] = archive_artifact(gate_path, out)
        template = captured[FIXTURES / "workload.tal"]
        base.require(b"storage(32)" in template, "resource capacity template missing")
        for capacity in CAPACITIES:
            capacity_dir = out / "workloads" / str(capacity)
            capacity_dir.mkdir(parents=True)
            source = template.replace(b"storage(32)", f"storage({capacity})".encode())
            source_path = capacity_dir / "workload.tal"
            source_path.write_bytes(source)
            generated_outputs = []
            for producer, prefix in (("reference", [sys.executable, "-B", "-m", "talven"]),
                                     ("native", [str(binary)])):
                verify_bytes(source_path, source)
                command(recorder, [*prefix, "check", str(source_path), "--resources", "--json"],
                        validator=lambda output, p=producer: validate_check(output, p == "native"),
                        phase="preflight", operation=producer + "-check")
                verify_bytes(source_path, source)
                output, entry = recorder.command([*prefix, "fmt", str(source_path), "--resources"], phase="preflight", operation=producer + "-format")
                base.require(output == source, "resource fixture is not canonical or producer format differs")
                verify_bytes(source_path, source)
                accept(recorder, entry)
                output, entry = recorder.command([*prefix, "emit-c", str(source_path), "--resources"], phase="preflight", operation=producer + "-emit")
                base.require(bool(output.strip()), "empty generated C")
                verify_bytes(source_path, source)
                generated_outputs.append(output)
                if producer == "native":
                    base.require(output == generated_outputs[0], "independent original-source producers emitted different C")
                accept(recorder, entry)
            for optimization in OPTIMIZATIONS:
                directory = capacity_dir / optimization.removeprefix("-")
                directory.mkdir()
                for name, data in (("generated.c", generated_outputs[0]), ("driver.c", captured[FIXTURES / "driver.c"]),
                                   ("layout.c", captured[FIXTURES / "layout.c"])):
                    (directory / name).write_bytes(data)
                stable = {directory / "generated.c": generated_outputs[0],
                          directory / "driver.c": captured[FIXTURES / "driver.c"],
                          directory / "layout.c": captured[FIXTURES / "layout.c"], source_path: source}
                measure_unit(recorder, args, cc, tool_paths, directory, capacity, optimization, stable)
        verify_inputs(files, captured)
        base.require(all((out / "inputs" / path.relative_to(ROOT)).read_bytes() == data for path, data in captured.items()),
                     "retained input archive changed during run")
        base.require(base.compiler_hash() == report["reference_compiler_hash"] and runtime_identity() == report["runtime_inputs"],
                     "reference compiler or runtime identity changed")
        final_info, entry = recorder.command([str(binary), "--build-info"], phase="provenance")
        verify_native(strict_json(final_info), binary,
                      {key: report["tools"]["native"][key] for key in ("bytes", "sha256")}, info)
        accept(recorder, entry)
        for name, dispatch in report["darwin_dispatch"].items():
            resolved, _ = command(recorder, [tool_paths["xcrun"], "--find", Path(dispatch["invocation"]).name],
                                   validator=effective_tool, phase="provenance", operation="recheck-effective-tool")
            base.require(str(resolved) == dispatch["effective"], "Darwin effective tool selection changed during run")
        if "sdk" in report:
            current_sdk, _ = command(recorder, [tool_paths["xcrun"], "--sdk", "macosx", "--show-sdk-path"],
                                         validator=sdk_path, phase="provenance", operation="recheck-sdk-path")
            current_version, _ = command(recorder, [tool_paths["xcrun"], "--sdk", "macosx", "--show-sdk-version"],
                                             validator=nonempty, phase="provenance", operation="recheck-sdk-version")
            base.require(str(current_sdk) == report["sdk"]["path"] and current_version == report["sdk"]["version"],
                         "Darwin SDK selection changed during run")
            if sdk_bytes is not None:
                base.require(sdk_settings.read_bytes() == sdk_bytes and (out / "sdk/SDKSettings.json").read_bytes() == sdk_bytes,
                             "Darwin SDK settings or retained settings archive changed during run")
            else:
                base.require(not sdk_settings.is_file(), "Darwin SDK settings appeared during run")
        base.require(all(base.fingerprint(path) == {key: report["tools"][name][key] for key in ("bytes", "sha256")}
                         for name, path in tool_paths.items()), "tool executable changed during run")
        base.require(all(base.fingerprint(out / report["tools"][name]["archive"]) ==
                         {key: report["tools"][name][key] for key in ("bytes", "sha256")} for name in tool_paths),
                     "retained tool executable changed during run")
        verify_artifacts(report, out)
        report["summary"] = summarize(report["commands"], args.repetitions)
        report.update(complete=True, passed=True)
    except (base.MeasurementError, OSError, ValueError, KeyError, TypeError) as error:
        report["error"] = str(error)
    except BaseException as error:
        report["error"] = type(error).__name__
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        recorder.save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="fresh artifact directory; never overwritten")
    parser.add_argument("--native", required=True, help="independent already-built Rust producer")
    parser.add_argument("--cc", default="cc")
    # Give small optimized batches headroom on hosts whose monotonic resolution is 1 us.
    # Explicit shorter batches still must satisfy the same clock-adequacy gate.
    parser.add_argument("--iterations", type=int, default=100000)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--expect-arch", choices=("x86_64", "aarch64"))
    parser.add_argument("--environment-note", default="unspecified")
    try:
        report = run(parser.parse_args(argv))
    except (base.MeasurementError, OSError, ValueError) as error:
        print("measurement error: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in ("schema", "complete", "passed", "error", "summary")}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
