#!/usr/bin/env python3
"""Offline CLI/build measurements, with retained inputs and correctness gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.tooling_workloads import CANDIDATE_SUFFIX, VERSION, workloads
from talven import PROFILE
from talven.context import compiler_hash

SCHEMA = "talven.tooling-baseline.v1"
FLAGS = ["-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic-errors"]
ENVIRONMENT = {"LC_ALL": "C", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
OPERATIONS = ("check", "format", "context", "snapshot", "validate", "emit-c", "c-build", "build")


class MeasurementError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": digest(data)}


def summarize(samples: list[dict], repetitions: int) -> list[dict]:
    """Never summarize a partial suite or include preflight/warmup/verification time."""
    measured = [s for s in samples if s["phase"] == "measured"]
    result = []
    for workload in (w["id"] for w in workloads()):
        for operation in OPERATIONS:
            group = [s for s in measured if s["workload"] == workload and s["operation"] == operation]
            if len(group) != repetitions or any(not s.get("verified") for s in group):
                raise MeasurementError(f"incomplete verified samples: {workload}/{operation}")
            durations = [s["elapsed_ns"] for s in group]
            result.append({"workload": workload, "operation": operation, "samples": len(group),
                           "min_ns": min(durations), "median_ns": statistics.median(durations),
                           "max_ns": max(durations),
                           "stdout_bytes": [s["stdout"]["bytes"] for s in group],
                           "artifact_bytes": [s["artifact"]["bytes"] for s in group] if operation in ("c-build", "build") else None})
    return result


class Recorder:
    def __init__(self, out: Path, report: dict, timeout: float):
        self.out, self.report, self.timeout = out, report, timeout

    def save(self):
        pending = self.out / "report.pending.json"
        pending.write_text(json.dumps(self.report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pending.replace(self.out / "report.json")

    def command(self, argv: list[str], *, phase="verification", workload=None, operation=None):
        index = len(self.report["commands"])
        entry = {"index": index, "argv": argv, "phase": phase, "workload": workload,
                 "operation": operation, "verified": False, "returncode": None, "error": None}
        self.report["commands"].append(entry)
        self.save()
        started = time.perf_counter_ns()
        stdout, stderr, process = b"", b"", None
        try:
            process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env={**os.environ, **ENVIRONMENT}, start_new_session=os.name == "posix")
            stdout, stderr = process.communicate(timeout=self.timeout)
            entry["returncode"] = process.returncode
        except (subprocess.TimeoutExpired, OSError) as error:
            entry["error"] = "timeout" if isinstance(error, subprocess.TimeoutExpired) else f"launch: {error}"
        except BaseException:
            entry["error"] = "interrupted"
            raise
        finally:
            if process is not None and (entry["error"] or process.poll() is None):
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    elif process.poll() is None:
                        process.kill()
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
                entry["returncode"] = process.returncode
            entry["elapsed_ns"] = time.perf_counter_ns() - started
            for label, data in (("stdout", stdout), ("stderr", stderr)):
                target = self.out / "commands" / f"{index:04d}.{label}"
                target.write_bytes(data)
                entry[label] = {"path": str(target.relative_to(self.out)), **fingerprint(target)}
            self.save()
        if entry["error"] or entry["returncode"] != 0:
            raise MeasurementError(f"command {index} failed ({entry['error'] or entry['returncode']}); see archived output")
        if phase in ("verification", "provenance"):
            entry["verified"] = True
        return stdout, entry


def require(condition: bool, message: str):
    if not condition:
        raise MeasurementError(message)


def input_files() -> list[Path]:
    return sorted([*ROOT.joinpath("talven").glob("*.py"), Path(__file__).resolve(),
                   ROOT / "experiments/tooling_workloads.py", ROOT / "experiments/__init__.py",
                   ROOT / "examples/vectors.tal", ROOT / "examples/borrowing.tal"])


def cpu_model(recorder: Recorder) -> str | None:
    if platform.system() == "Linux":
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    elif platform.system() == "Darwin":
        text, _ = recorder.command(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], phase="provenance")
        return text.decode().strip()
    return None


def preflight(out: str, repetitions: int, warmups: int, timeout: float, cc: str, expect_arch: str | None):
    require(bool(out.strip()), "--out must not be empty")
    target = Path(out).expanduser().resolve()
    require(not target.exists(), "output path already exists; choose a fresh directory")
    require(type(repetitions) is int and 1 <= repetitions <= 100, "repetitions must be 1..100")
    require(type(warmups) is int and 0 <= warmups <= 10, "warmups must be 0..10")
    require(math.isfinite(timeout) and 0 < timeout <= 300, "timeout must be finite and within (0, 300]")
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    require(expect_arch is None or arch == expect_arch, f"expected {expect_arch}, actual {arch}")
    resolved = shutil.which(cc)
    require(resolved is not None, f"C compiler not found: {cc}")
    require(shutil.which("git") is not None, "Git is required for provenance")
    return target, str(Path(resolved).absolute()), arch


def check_output(operation: str, output: bytes, source: bytes, candidate: bytes, identity: str,
                 reference: bytes | None = None):
    if reference is not None:
        require(output == reference, f"{operation}: output changed between invocations")
    if operation == "format":
        require(output == source, "formatter output differs from canonical workload")
    elif operation in ("check", "context", "snapshot", "validate"):
        value = json.loads(output)
        if operation == "check":
            require(value == {"schema": "talven.diagnostics.v1", "ok": True, "diagnostics": []}, "check did not accept workload")
        else:
            require(value.get("source_hash") == digest(source) and value.get("compiler_hash") == identity,
                    f"{operation}: wrong revision identities")
            if operation == "context":
                require(value.get("schema") == "talven.context.v2" and value.get("symbol") == "main"
                        and value.get("validation") == "frontend-only"
                        and [f["name"] for f in value.get("functions", [])] == ["main"], "wrong selected context")
            elif operation == "snapshot":
                require(value.get("schema") == "talven.edit-snapshot.v1" and value.get("ok") is True
                        and value.get("validation") == "not-run" and "untrusted_source_text" not in value, "wrong snapshot")
            else:
                changes = value.get("changes") or {}
                require(value.get("schema") == "talven.edit-validation.v1" and value.get("ok") is True
                        and value.get("validation") == "frontend-only"
                        and value.get("candidate_hash") == digest(candidate)
                        and value.get("candidate_changed") is True
                        and [f["name"] for f in changes.get("added", [])] == ["baseline_added"]
                        and all(changes.get(key) == [] for key in ("removed", "contracts_changed", "calls_changed")),
                        "edit preview did not report the added helper")
    elif operation == "emit-c":
        require(bool(output.strip()), "empty generated C")


def measure_workload(recorder: Recorder, workload: dict, cc: str, identity: str, repetitions: int, warmups: int):
    out = recorder.out / "workloads" / workload["id"]
    out.mkdir(parents=True)
    source, candidate = workload["source"], workload["source"] + CANDIDATE_SUFFIX
    source_file, candidate_file, generated = out / "source.tal", out / "candidate.tal", out / "generated.c"
    oracle, subject, checker = out / "oracle.c", out / "subject.o", out / "oracle"
    source_file.write_bytes(source)
    candidate_file.write_bytes(candidate)
    oracle.write_bytes(workload["oracle"])
    row = {key: workload[key] for key in ("id", "origin", "criteria")}
    row.update(source=fingerprint(source_file), candidate=fingerprint(candidate_file), oracle=fingerprint(oracle),
               native_verified=False)
    recorder.report["workloads"].append(row)
    python = [sys.executable, "-B", "-m", "talven"]
    cli = {
        "check": [*python, "check", str(source_file), "--json"],
        "format": [*python, "fmt", str(source_file)],
        "context": [*python, "context", str(source_file), "--symbol", "main", "--include-body", "--max-bytes", "16384"],
        "snapshot": [*python, "edit", "snapshot", str(source_file)],
        "validate": [*python, "edit", "validate", str(source_file), "--candidate", str(candidate_file),
                     "--expect-source-hash", digest(source), "--expect-compiler-hash", identity],
        "emit-c": [*python, "emit-c", str(source_file)],
    }
    references = {}
    for operation, argv in cli.items():
        output, entry = recorder.command(argv, phase="preflight", workload=workload["id"], operation=operation)
        check_output(operation, output, source, candidate, identity)
        references[operation] = output
        entry["verified"] = True
    generated.write_bytes(references["emit-c"])
    row["generated_c"] = fingerprint(generated)
    # Separate translation units and no LTO keep the native oracle independent
    # of the generated implementation and preserve full-i32 comparisons.
    recorder.command([cc, *FLAGS, "-fno-lto", "-Dmain=talven_benchmark_main", "-c", str(generated), "-o", str(subject)])
    recorder.command([cc, *FLAGS, "-fno-lto", str(subject), str(oracle), "-o", str(checker)])
    recorder.command([str(checker)])
    row["native_verified"] = True
    for phase, count in (("warmup", warmups), ("measured", repetitions)):
        for repetition in range(1, count + 1):
            for operation in OPERATIONS:
                artifact = out / f"{phase}-{repetition}-{operation}"
                if operation == "c-build":
                    argv = [cc, *FLAGS, str(generated), "-o", str(artifact)]
                elif operation == "build":
                    argv = [*python, "build", str(source_file), "--cc", cc, "-o", str(artifact)]
                else:
                    argv = cli[operation]
                output, entry = recorder.command(argv, phase=phase, workload=workload["id"], operation=operation)
                entry["repetition"] = repetition
                if operation in ("c-build", "build"):
                    require(artifact.is_file(), "build did not produce executable")
                    entry["artifact"] = {"path": str(artifact.relative_to(recorder.out)), **fingerprint(artifact)}
                    recorder.command([str(artifact)])
                else:
                    check_output(operation, output, source, candidate, identity, references[operation])
                entry["verified"] = True
            recorder.save()
    require(source_file.read_bytes() == source and candidate_file.read_bytes() == candidate
            and generated.read_bytes() == references["emit-c"] and oracle.read_bytes() == workload["oracle"],
            "workload inputs changed during measurement")


def run(out: str, *, repetitions=5, warmups=1, timeout=60.0, cc="cc", expect_arch=None, environment_note=None) -> dict:
    target, cc, arch = preflight(out, repetitions, warmups, timeout, cc, expect_arch)
    target.mkdir(parents=True)
    (target / "commands").mkdir()
    report = {"schema": SCHEMA, "suite": VERSION, "complete": False, "passed": False,
              "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
              "operator_environment_note": environment_note,
              "error": None, "commands": [], "workloads": [], "summary": None,
              "settings": {"repetitions": repetitions, "warmups": warmups, "timeout_seconds": timeout,
                           "environment_overrides": ENVIRONMENT, "c_flags": FLAGS,
                           "order": "workload, phase, repetition, operation; fixed sequential order",
                           "timing": "perf_counter_ns around process launch/communicate; output verification and receipt writes excluded",
                           "cache_policy": "fresh processes; no bytecode writes; existing bytecode and OS caches uncontrolled"},
              "unmeasured": ["model/tokens/cost (no provider)", "memory/allocations", "LSP latency", "native throughput", "cold-cache performance"]}
    recorder = Recorder(target, report, timeout)
    recorder.save()
    try:
        files = input_files()
        inputs = {str(path.relative_to(ROOT)): fingerprint(path) for path in files}
        for path in files:
            copy = target / "inputs" / path.relative_to(ROOT)
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(path.read_bytes())
            require(fingerprint(copy) == inputs[str(path.relative_to(ROOT))], "input changed while archiving")
        report["inputs"] = inputs
        identity = compiler_hash()
        report.update(compiler_hash=identity, profile=PROFILE)
        revision, _ = recorder.command(["git", "rev-parse", "HEAD"], phase="provenance")
        status, _ = recorder.command(["git", "status", "--porcelain", "--untracked-files=all"], phase="provenance")
        version, _ = recorder.command([cc, "--version"], phase="provenance")
        triple, _ = recorder.command([cc, "-dumpmachine"], phase="provenance")
        require(bool(triple.strip()) and bool(version.strip()), "missing C toolchain identity")
        report["git"] = {"revision": revision.decode().strip(), "dirty": bool(status.strip())}
        report["host"] = {"system": platform.system(), "release": platform.release(), "arch": arch,
                          "cpu_model": cpu_model(recorder), "logical_cpus": os.cpu_count(),
                          "python_implementation": platform.python_implementation(), "python_version": platform.python_version(),
                          "python": {"path": sys.executable, **fingerprint(Path(sys.executable))},
                          "cc": {"path": cc, "version": version.decode().strip(), "target": triple.decode().strip(),
                                 **fingerprint(Path(cc))}}
        report["clock"] = vars(time.get_clock_info("perf_counter"))
        for workload in workloads():
            measure_workload(recorder, workload, cc, identity, repetitions, warmups)
        require(input_files() == files and all(fingerprint(path) == inputs[str(path.relative_to(ROOT))] for path in files)
                and compiler_hash() == identity, "compiler or benchmark inputs changed during measurement")
        require(fingerprint(Path(cc))["sha256"] == report["host"]["cc"]["sha256"]
                and fingerprint(Path(sys.executable))["sha256"] == report["host"]["python"]["sha256"], "tool executable changed")
        report["summary"] = summarize(report["commands"], repetitions)
        report.update(complete=True, passed=True)
    except (MeasurementError, OSError, ValueError) as error:
        report["error"] = str(error)
    except BaseException as error:
        report["error"] = type(error).__name__
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        recorder.save()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="fresh artifact directory")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--cc", default="cc", help="trusted native C compiler executable")
    parser.add_argument("--expect-arch", choices=("aarch64", "x86_64"))
    parser.add_argument("--environment-note", help="operator-supplied container/hardware/run conditions; not independently verified")
    args = parser.parse_args(argv)
    try:
        report = run(args.out, repetitions=args.repetitions, warmups=args.warmups,
                     timeout=args.timeout, cc=args.cc, expect_arch=args.expect_arch, environment_note=args.environment_note)
    except (MeasurementError, OSError) as error:
        print(f"measurement error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in ("schema", "complete", "passed", "error", "summary")}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
