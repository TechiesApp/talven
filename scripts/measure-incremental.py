#!/usr/bin/env python3
"""Compare in-process full and persistent checks over retained edit sequences."""

import argparse
from datetime import datetime, timezone
import gc
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("tooling_measurement", ROOT / "scripts/measure-tooling.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from experiments.tooling_workloads import chain_source, driver
from talven import PROFILE, VERSION
from talven.backend import emit_c
from talven.context import context, source_hash
from talven.frontend import CompileError, analyze
from talven.incremental import IncrementalFrontend


def workloads():
    result = []
    for workload_id, count, stores in (("chain-32", 32, 0), ("chain-128", 128, 0), ("stores-128", 128, 12)):
        if stores:
            helpers = []
            for index in range(count):
                value = f"acc - {stores - 1}" if index == 0 else f"step_{index - 1}(acc - {stores}) + 1"
                helpers.append(f"fn step_{index}(value: i32) -> i32 {{\n    let mut acc = value;\n"
                               + "    acc = acc + 1;\n" * stores + f"    return {value};\n}}")
            original = "\n\n".join(helpers) + "\n\nfn main()" + chain_source(count).split("fn main()", 1)[1]
            before, after = f"return acc - {stores - 1};", f"return acc - {stores - 2};"
        else:
            original = chain_source(count)
            before, after = "return value + 1;", "return value + 2;"
        body = original.replace(before, after, 1)
        # Keep main's independent zero-status acceptance in sync with the edit.
        body = body.replace(f"== {count + 7}", f"== {count + 8}")
        contract = body.replace("step_0(value: i32)", "step_0(input: i32)")
        contract = contract.replace("let mut acc = value;", "let mut acc = input;", 1) if stores else contract.replace(
            "return value + 2;", "return input + 2;", 1)
        invalid = contract.replace(after if stores else "return input + 2;", "return false;", 1)
        steps = [("initial", original, count), ("trivia", "// shifted 😀\n" + original, count),
                 ("body", body, count + 1), ("contract", contract, count + 1),
                 ("invalid", invalid, None), ("repair", contract, count + 1)]
        revisions = []
        for name, source, total in steps:
            oracle = None if total is None else driver(
                f"extern int32_t tv_f_step_{count - 1}(int32_t);",
                "\n".join(f"if (tv_f_step_{count - 1}({value}) != {value + total}) return 1;"
                          for value in (-1000, 0, 1000000)))
            revisions.append({"id": name, "source": source, "oracle": oracle,
                              "expected_error": "E0201" if total is None else None})
        result.append({"id": workload_id, "revisions": revisions,
                       "criteria": "Exact full/reference analysis, C and context; three full-i32 chain results; main returns zero; invalid edit is E0201."})
    original = ("struct P { x: i32 }\n"
                "fn read(p: &P) -> i32 { return p.x; }\n"
                "fn bump(p: &mut P) -> i32 { p.x = p.x + 1; return p.x; }\n"
                "fn main() -> i32 { let mut p = P { x: 1 }; return bump(&mut p) - 2; }\n")
    body = original.replace("p.x + 1", "p.x + 2").replace("bump(&mut p) - 2", "bump(&mut p) - 3")
    schema = body.replace("x: i32 }", "x: i32, y: bool }").replace("x: 1 }", "x: 1, y: false }")
    invalid = schema.replace("bump(&mut p)", "bump(&p)")
    revisions = []
    for name, source, fields, delta in (("initial", original, "", 1),
                                      ("trivia", "// shifted 😀\n" + original, "", 1),
                                      ("body", body, "", 2),
                                      ("schema", schema, " _Bool tv_m_y;", 2),
                                      ("invalid", invalid, " _Bool tv_m_y;", None),
                                      ("repair", schema, " _Bool tv_m_y;", 2)):
        oracle = None if delta is None else driver(
            f"struct tv_s_P {{ int32_t tv_m_x;{fields} }};\n"
            "extern int32_t tv_f_read(const struct tv_s_P *);\n"
            "extern int32_t tv_f_bump(struct tv_s_P *);",
            "\n".join("{ struct tv_s_P p = {" + str(value) + (", 1" if fields else "") + "}; "
                      f"if (tv_f_read(&p) != {value} || p.tv_m_x != {value}) return 1; "
                      f"if (tv_f_bump(&p) != {value + delta} || p.tv_m_x != {value + delta}) return 1; "
                      + ("if (p.tv_m_y != 1) return 1; " if fields else "") + "}"
                      for value in (-1000, 0, 1000000)))
        revisions.append({"id": name, "source": source, "oracle": oracle,
                          "expected_error": "E0201" if delta is None else None})
    result.append({"id": "borrowing", "revisions": revisions,
                   "criteria": "Exact full/reference analysis, C and context; read preserves owner; bump updates three full-i32 owners; added field preserved; main zero; invalid loan E0201."})
    return result


def checked(check, source):
    try:
        return check(source), None
    except CompileError as error:
        return None, error.diagnostic(source)


def summarize(samples, repetitions):
    result = []
    for workload in workloads():
        for revision in workload["revisions"]:
            for mode in ("full", "incremental"):
                group = [s for s in samples if s["phase"] == "measured" and s["workload"] == workload["id"]
                         and s["revision"] == revision["id"] and s["mode"] == mode]
                base.require(len(group) == repetitions and all(s["verified"] for s in group),
                             f"incomplete verified samples: {workload['id']}/{revision['id']}/{mode}")
                values = [s["elapsed_ns"] for s in group]
                result.append({"workload": workload["id"], "revision": revision["id"], "mode": mode,
                               "samples": len(group), "min_ns": min(values),
                               "median_ns": statistics.median(values), "max_ns": max(values)})
    return result


def verify_native(recorder, cc, directory, generated, oracle):
    cfile, subject = directory / "generated.c", directory / "subject.o"
    oracle_file, executable = directory / "oracle.c", directory / "acceptance"
    cfile.write_text(generated, encoding="utf-8")
    oracle_file.write_bytes(oracle)
    recorder.command([cc, *base.FLAGS, "-fno-lto", "-Dmain=talven_benchmark_main", "-c", str(cfile), "-o", str(subject)])
    recorder.command([cc, *base.FLAGS, "-fno-lto", str(subject), str(oracle_file), "-o", str(executable)])
    stdout, entry = recorder.command([str(executable)])
    base.require(stdout == b"" and entry["stderr"]["bytes"] == 0, "native oracle output mismatch")
    return {"generated_c": base.fingerprint(cfile), "oracle": base.fingerprint(oracle_file),
            "executable": base.fingerprint(executable)}


def run(args):
    call_type_contracts = getattr(args, 'call_type_contracts', False)
    base.require(type(call_type_contracts) is bool, 'call type contracts must be an explicit boolean')
    reuse_body_syntax = getattr(args, 'reuse_body_syntax', False)
    base.require(type(reuse_body_syntax) is bool, 'body syntax reuse must be an explicit boolean')
    out, cc, arch = base.preflight(args.out, args.repetitions, args.warmups, args.timeout, args.cc, args.expect_arch)
    out.mkdir(parents=True)
    (out / "commands").mkdir()
    report = {"schema": "talven.incremental-comparison.v1", "complete": False, "passed": False,
              "summary": None, "commands": [], "samples": [], "inputs": {}, "workloads": [],
              "started_at": datetime.now(timezone.utc).isoformat(), "repetitions": args.repetitions,
              "warmups": args.warmups, "call_type_contracts": call_type_contracts, "reuse_body_syntax": reuse_body_syntax,
              "compiler_hash": base.compiler_hash(), "profile": PROFILE,
              "compiler_version": VERSION, "python": platform.python_version(),
              "python_executable": base.fingerprint(Path(sys.executable)),
              "c_executable": base.fingerprint(Path(cc)), "machine": arch, "system": platform.system(),
              "os_release": platform.release(), "environment_note": args.environment_note,
              "in_process_environment": {key: os.environ.get(key) for key in base.ENVIRONMENT},
              "effective_environment_hash": source_hash(json.dumps(dict(os.environ), sort_keys=True)),
              "working_directory_hash": source_hash(str(Path.cwd())),
              "garbage_collector": {"enabled": gc.isenabled(), "thresholds": gc.get_threshold()},
              "c_flags": [*base.FLAGS, "-fno-lto"], "verification_timeout_seconds": args.timeout,
              "clock": {"implementation": time.get_clock_info("perf_counter").implementation,
                        "resolution_seconds": time.get_clock_info("perf_counter").resolution},
              "timed_boundary": "In-process analysis including full lexing/declarations, selected full/body grammar and incremental identity hashing; initial includes session construction. Verification and C builds excluded.",
              "unmeasured": ["startup", "incremental tokenization", "native Rust reuse", "native builds", "save-to-running latency", "memory", "model/token/cost effectiveness"]}
    recorder = base.Recorder(out, report, args.timeout)
    recorder.save()
    try:
        inputs = sorted([*ROOT.joinpath("talven").glob("*.py"), Path(__file__).resolve(),
                         ROOT / "scripts/measure-tooling.py", ROOT / "experiments/tooling_workloads.py",
                         ROOT / "experiments/__init__.py", *ROOT.joinpath('examples').glob('*.tal')])
        for path in inputs:
            relative = path.relative_to(ROOT)
            archived = out / "inputs" / relative
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(path.read_bytes())
            report["inputs"][str(relative)] = base.fingerprint(archived)
        for key, command in {"git_revision": ["git", "rev-parse", "HEAD"],
                             "git_status": ["git", "status", "--porcelain"],
                             "c_version": [cc, "--version"], "c_target": [cc, "-dumpmachine"]}.items():
            output, _ = recorder.command(command, phase="provenance")
            report[key] = output.decode().strip()
        report["cpu_model"] = base.cpu_model(recorder)
        for workload in workloads():
            expected = {}
            row = {"id": workload["id"], "criteria": workload["criteria"], "revisions": []}
            report["workloads"].append(row)
            for revision in workload["revisions"]:
                directory = out / "workloads" / workload["id"] / revision["id"]
                directory.mkdir(parents=True)
                source = directory / "source.tal"
                source.write_text(revision["source"], encoding="utf-8")
                analysis, diagnostic = checked(analyze, revision["source"])
                base.require((analysis is not None) == (revision["expected_error"] is None),
                             "workload analysis is missing or unexpectedly valid")
                base.require((diagnostic["code"] if diagnostic else None) == revision["expected_error"],
                             "workload did not meet its expected validity")
                generated = emit_c(analysis) if analysis else None
                facts = context(analysis, max_bytes=1048576) if analysis else None
                expected[revision["id"]] = analysis, diagnostic, generated, facts
                record = {"id": revision["id"], "source": base.fingerprint(source), "diagnostic": diagnostic,
                          "native_acceptance": None}
                if analysis:
                    record["native_acceptance"] = verify_native(recorder, cc, directory, generated, revision["oracle"])
                row["revisions"].append(record)
            for phase, count in (("warmup", args.warmups), ("measured", args.repetitions)):
                for repetition in range(count):
                    frontend = None
                    for revision in workload["revisions"]:
                        order = ("full", "incremental") if repetition % 2 == 0 else ("incremental", "full")
                        for mode in order:
                            sample = {"phase": phase, "repetition": repetition + 1, "workload": workload["id"],
                                      "revision": revision["id"], "mode": mode, "verified": False}
                            report["samples"].append(sample)
                            recorder.save()
                            started = time.perf_counter_ns()
                            if mode == "incremental" and frontend is None:
                                frontend = IncrementalFrontend(call_type_contracts=call_type_contracts,
                                                               reuse_body_syntax=reuse_body_syntax)
                            actual, diagnostic = checked(frontend.analyze if mode == "incremental" else analyze, revision["source"])
                            sample["elapsed_ns"] = time.perf_counter_ns() - started
                            sample["diagnostic"] = diagnostic
                            sample["reuse"] = frontend.stats if mode == "incremental" else None
                            sample["parsing"] = frontend.parse_stats if mode == "incremental" else None
                            wanted, error, generated, facts = expected[revision["id"]]
                            base.require(diagnostic == error and actual == wanted, "analysis/diagnostic mismatch")
                            if actual:
                                base.require(emit_c(actual) == generated and context(actual, max_bytes=1048576) == facts,
                                             "emission/context differs from accepted current revision")
                            sample["verified"] = True
                            recorder.save()
        for relative, identity in report["inputs"].items():
            base.require(base.fingerprint(ROOT / relative) == identity, f"input changed: {relative}")
        for path, identity in ((Path(sys.executable), report["python_executable"]), (Path(cc), report["c_executable"])):
            base.require(base.fingerprint(path) == identity, f"executable changed: {path}")
        base.require(base.compiler_hash() == report["compiler_hash"], "compiler changed during measurement")
        report["summary"] = summarize(report["samples"], args.repetitions)
        report.update(complete=True, passed=True)
        return 0
    except (base.MeasurementError, CompileError, OSError, ValueError) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        recorder.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--expect-arch", choices=("aarch64", "x86_64"))
    parser.add_argument("--environment-note", default="unspecified")
    parser.add_argument("--call-type-contracts", action="store_true", help="Select caller type dependencies with current reference descriptions")
    parser.add_argument("--reuse-body-syntax", action="store_true", help="Select exact last-successful body grammar with fresh lexing/declarations")
    try:
        return run(parser.parse_args())
    except (base.MeasurementError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
