#!/usr/bin/env python3
"""Retain a narrow native/reference CLI comparison with independent acceptance."""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("tooling_measurement", ROOT / "scripts/measure-tooling.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from experiments.tooling_workloads import workloads


def selected_workloads():
    return [{"id": "hello", "origin": "examples/hello.tal", "source": (ROOT / "examples/hello.tal").read_bytes(),
             "oracle": None, "console": True, "stdout": b"Hello, world!\n",
             "criteria": "Exact greeting stdout, empty stderr, exit zero."},
            *[{**w, "console": False, "stdout": b""} for w in workloads() if w["id"] in ("chain-32", "chain-128")]]


def validate_output(operation, implementation, output):
    if operation == "check":
        expected = {"schema": "talven.diagnostics.v1", "ok": True, "diagnostics": []}
        if implementation == "native":
            expected["profile"] = "native-scalar-text-v1"
        base.require(json.loads(output) == expected, "incorrect diagnostic receipt")
    else:
        base.require(bool(output.strip()), "empty emitted C")


def verify_c(recorder, cc, directory, generated, workload):
    cfile, binary = directory / "generated.c", directory / "acceptance"
    cfile.write_bytes(generated)
    if workload["oracle"] is None:
        recorder.command([cc, *base.FLAGS, str(cfile), "-o", str(binary)])
    else:
        oracle, subject = directory / "oracle.c", directory / "subject.o"
        oracle.write_bytes(workload["oracle"])
        recorder.command([cc, *base.FLAGS, "-fno-lto", "-Dmain=talven_benchmark_main", "-c", str(cfile), "-o", str(subject)])
        recorder.command([cc, *base.FLAGS, "-fno-lto", str(subject), str(oracle), "-o", str(binary)])
    output, entry = recorder.command([str(binary)])
    base.require(output == workload["stdout"] and entry["stderr"]["bytes"] == 0, "native acceptance output mismatch")
    return {"generated_c": base.fingerprint(cfile), "executable": base.fingerprint(binary)}


def summarize(commands, repetitions):
    rows = []
    for workload in ("hello", "chain-32", "chain-128"):
        for implementation in ("reference", "native"):
            for operation in ("check", "emit-c"):
                group = [c for c in commands if c["phase"] == "measured" and c["workload"] == workload
                         and c.get("implementation") == implementation and c["operation"] == operation]
                base.require(len(group) == repetitions and all(c["verified"] for c in group), "incomplete verified samples")
                values = [c["elapsed_ns"] for c in group]
                rows.append({"workload": workload, "implementation": implementation, "operation": operation,
                             "samples": len(group), "min_ns": min(values), "median_ns": statistics.median(values), "max_ns": max(values)})
    return rows


def verify_build_sources(info, native_root):
    names = {"Cargo.toml", "Cargo.lock", "build.rs", "src/main.rs", "src/lib.rs", "src/runtime.c", "src/console.c"}
    sources = info.get("source_files", {})
    base.require(set(sources) == names, "native build source manifest is missing or unexpected")
    for name in names:
        base.require(isinstance(sources[name], str) and sources[name].encode() == (native_root / name).read_bytes(),
                     f"native executable was built from different source: {name}")
    base.require(isinstance(info.get("settings"), dict) and "CARGO_ENCODED_RUSTFLAGS" in info["settings"], "native build settings missing")


def run(args):
    out, cc, arch = base.preflight(args.out, args.repetitions, args.warmups, args.timeout, args.cc, args.expect_arch)
    binary = Path(args.native).resolve()
    base.require(binary.is_file(), "--native must name a built compiler executable")
    out.mkdir(parents=True)
    (out / "commands").mkdir()
    report = {"schema": "talven.native-comparison.v1", "complete": False, "passed": False,
              "summary": None, "commands": [], "workloads": [], "inputs": {},
              "started_at": datetime.now(timezone.utc).isoformat(), "repetitions": args.repetitions,
              "warmups": args.warmups, "timeout_seconds": args.timeout, "c_flags": base.FLAGS,
              "environment_overrides": base.ENVIRONMENT, "machine": arch, "system": platform.system(),
              "os_release": platform.release(), "python": platform.python_version(),
              "environment_note": args.environment_note, "native": base.fingerprint(binary),
              "native_path": str(binary), "python_executable": base.fingerprint(Path(sys.executable)),
              "c_executable": base.fingerprint(Path(cc)), "compiler_hash": base.compiler_hash(),
              "unmeasured": ["incremental compilation", "full build comparison", "cold caches", "memory", "tokens", "dollar cost"]}
    recorder = base.Recorder(out, report, args.timeout)
    recorder.save()
    try:
        native = ROOT / "experiments/native-compiler"
        inputs = sorted([*ROOT.joinpath("talven").glob("*.py"), *native.joinpath("src").glob("*"),
                         *native.joinpath("tests").glob("*.py"), native / "build.rs", native / "Cargo.toml", native / "Cargo.lock",
                         Path(__file__).resolve(), ROOT / "scripts/measure-tooling.py", ROOT / "experiments/tooling_workloads.py",
                         ROOT / "examples/hello.tal"])
        for path in inputs:
            relative = path.relative_to(ROOT)
            archived = out / "inputs" / relative
            archived.parent.mkdir(parents=True, exist_ok=True)
            data = path.read_bytes()
            archived.write_bytes(data)
            report["inputs"][str(relative)] = base.fingerprint(archived)
        archived_binary = out / "inputs" / "native-executable"
        archived_binary.write_bytes(binary.read_bytes())
        archived_binary.chmod(0o755)
        base.require(base.fingerprint(archived_binary) == report["native"], "native executable changed during archive")
        for field, command in {
            "git_revision": ["git", "rev-parse", "HEAD"], "git_status": ["git", "status", "--porcelain"],
            "c_version": [cc, "--version"], "c_target": [cc, "-dumpmachine"],
            "native_build_info": [str(binary), "--build-info"], "native_version": [str(binary), "--version"],
        }.items():
            output, _ = recorder.command(command, phase="provenance")
            report[field] = json.loads(output) if field == "native_build_info" else output.decode().strip()
        verify_build_sources(report["native_build_info"], native)
        base.require(report["native_build_info"]["target"].split("-")[0] == arch, "native binary target does not match measurement host")
        report["native_build_sources_verified"] = True
        report["cpu_model"] = base.cpu_model(recorder)
        report["clock"] = {"implementation": base.time.get_clock_info("perf_counter").implementation,
                           "resolution_seconds": base.time.get_clock_info("perf_counter").resolution}
        for workload in selected_workloads():
            directory = out / "workloads" / workload["id"]
            directory.mkdir(parents=True)
            source = directory / "source.tal"
            source.write_bytes(workload["source"])
            references = {}
            commands = {}
            row = {key: workload[key] for key in ("id", "origin", "criteria")}
            row.update(source=base.fingerprint(source), native_acceptance={})
            report["workloads"].append(row)
            for implementation, prefix in (("reference", [sys.executable, "-B", "-m", "talven"]), ("native", [str(binary)])):
                emitted = None
                for operation in ("check", "emit-c"):
                    argv = [*prefix, operation, str(source)]
                    argv += ["--json"] if operation == "check" else (["--console"] if workload["console"] else [])
                    commands[implementation, operation] = argv
                    output, entry = recorder.command(argv, phase="preflight", workload=workload["id"], operation=operation)
                    entry["implementation"] = implementation
                    validate_output(operation, implementation, output)
                    references[implementation, operation] = output
                    entry["verified"] = True
                    if operation == "emit-c":
                        emitted = output
                target = directory / implementation
                target.mkdir()
                row["native_acceptance"][implementation] = verify_c(recorder, cc, target, emitted, workload)
            for phase, count in (("warmup", args.warmups), ("measured", args.repetitions)):
                for repetition in range(count):
                    # Alternate order per repetition to reduce fixed first/second bias.
                    order = ("reference", "native") if repetition % 2 == 0 else ("native", "reference")
                    for operation in ("check", "emit-c"):
                        for implementation in order:
                            output, entry = recorder.command(commands[implementation, operation], phase=phase,
                                                              workload=workload["id"], operation=operation)
                            entry.update(implementation=implementation, repetition=repetition + 1)
                            base.require(output == references[implementation, operation], "output differs from independently accepted preflight")
                            entry["verified"] = True
                            recorder.save()
        for relative, identity in report["inputs"].items():
            base.require(base.fingerprint(ROOT / relative) == identity, f"input changed: {relative}")
        for path, identity in ((binary, report["native"]), (Path(sys.executable), report["python_executable"]), (Path(cc), report["c_executable"])):
            base.require(base.fingerprint(path) == identity, f"executable changed: {path}")
        report["summary"] = summarize(report["commands"], args.repetitions)
        report.update(complete=True, passed=True)
        return 0
    except (base.MeasurementError, OSError, ValueError) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        recorder.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--expect-arch", choices=("aarch64", "x86_64"))
    parser.add_argument("--environment-note", default="unspecified")
    try:
        return run(parser.parse_args())
    except (base.MeasurementError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
