#!/usr/bin/env python3
"""Compare type-check latency of the Talven frontends and, for context, mature compilers.

Generates equivalent scalar programs (functions with arithmetic, comparisons,
conditionals, and calls) in Talven, C, and Rust, then measures:

- the Python reference frontend in-process (after import, so no interpreter start-up);
- the Python reference CLI end to end (`python3 -m talven check`);
- the native Rust prototype end to end (`talven-native check`, including its start-up);
- `cc -fsyntax-only` and `rustc --emit=metadata` on the equivalent C and Rust sources.

Every run must succeed or the benchmark fails. The other languages' checkers do
different and more work (richer languages, larger front ends); their rows give
scale, not a like-for-like comparison.

Usage: python3 scripts/benchmark-frontends.py --native PATH --out results.json [--repetitions 7]
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from talven.frontend import analyze, lex  # noqa: E402


def talven_program(functions):
    parts = []
    for i in range(functions):
        call = f"f{i - 1}(a, b)" if i else "a - b"
        parts.append(f"fn f{i}(a: i32, b: i32) -> i32 {{\n"
                     f"    let c = a * 3 + b % 7;\n"
                     f"    if (c > 100 && b != 0) {{\n        return c / 2;\n    }}\n"
                     f"    return c + {call};\n}}\n")
    parts.append(f"fn main() -> i32 {{\n    return f{functions - 1}(1, 2) - f{functions - 1}(1, 2);\n}}\n")
    return "\n".join(parts)


def c_program(functions):
    parts = ["#include <stdint.h>"]
    for i in range(functions):
        call = f"f{i - 1}(a, b)" if i else "a - b"
        parts.append(f"static int32_t f{i}(int32_t a, int32_t b) {{ int32_t c = a * 3 + b % 7; "
                     f"if (c > 100 && b != 0) {{ return c / 2; }} return c + {call}; }}")
    parts.append(f"int main(void) {{ return (int)(f{functions - 1}(1, 2) - f{functions - 1}(1, 2)); }}")
    return "\n".join(parts) + "\n"


def rust_program(functions):
    parts = []
    for i in range(functions):
        call = f"f{i - 1}(a, b)" if i else "a - b"
        parts.append(f"fn f{i}(a: i32, b: i32) -> i32 {{ let c = a * 3 + b % 7; "
                     f"if c > 100 && b != 0 {{ return c / 2; }} c + {call} }}")
    parts.append(f"fn main() {{ std::process::exit(f{functions - 1}(1, 2) - f{functions - 1}(1, 2)); }}")
    return "\n".join(parts) + "\n"


def timed(action, repetitions):
    action()  # Warm-up; excluded.
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        action()
        samples.append(time.perf_counter() - started)
    return {"median_ms": statistics.median(samples) * 1000, "min_ms": min(samples) * 1000,
            "max_ms": max(samples) * 1000, "samples": len(samples)}


def run_ok(argv, cwd):
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=120)
    if completed.returncode != 0:
        raise SystemExit(f"benchmark command failed: {argv}\n{completed.stderr.decode(errors='replace')}")


def version(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--native", type=Path, required=True, help="Built talven-native release binary")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--sizes", default="10,100,400")
    args = parser.parse_args()
    native = args.native.resolve(strict=True)
    rustc, cc = shutil.which("rustc"), shutil.which("cc")
    results = []
    with tempfile.TemporaryDirectory(prefix="talven-bench-") as temporary:
        directory = Path(temporary)
        for functions in map(int, args.sizes.split(",")):
            source = talven_program(functions)
            tokens = len(lex(source)) - 1
            talven_file = directory / f"p{functions}.tal"
            talven_file.write_text(source)
            analyze(source)  # Must be valid before timing.
            row = {"functions": functions, "lines": source.count("\n"), "bytes": len(source.encode()),
                   "talven_tokens": tokens,
                   "python_in_process": timed(lambda: analyze(source), args.repetitions),
                   "python_cli": timed(lambda: run_ok([sys.executable, "-m", "talven", "check", str(talven_file)], ROOT),
                                       args.repetitions),
                   "native_cli": timed(lambda: run_ok([str(native), "check", str(talven_file)], directory),
                                       args.repetitions)}
            if cc:
                c_file = directory / f"p{functions}.c"
                c_file.write_text(c_program(functions))
                row["cc_syntax_only"] = timed(lambda: run_ok([cc, "-std=c11", "-fsyntax-only", str(c_file)], directory),
                                              args.repetitions)
            if rustc:
                rust_file = directory / f"p{functions}.rs"
                rust_file.write_text(rust_program(functions))
                row["rustc_metadata"] = timed(lambda: run_ok([rustc, "--edition", "2021", "--emit=metadata",
                                                              "--crate-type", "bin", "-o", str(directory / "out.rmeta"),
                                                              str(rust_file)], directory), args.repetitions)
            results.append(row)
            print(json.dumps({k: (v["median_ms"] if isinstance(v, dict) else v) for k, v in row.items()}), flush=True)
    evidence = {
        "schema": "talven.frontend-benchmark.v1",
        "host": {"system": platform.system(), "machine": platform.machine(), "processor": platform.processor() or None,
                 "logical_cpus": os.cpu_count(), "python": platform.python_version()},
        "tools": {"native": str(native.name), "cc": version([cc, "--version"]) if cc else None,
                  "rustc": version([rustc, "--version"]) if rustc else None},
        "repetitions": args.repetitions,
        "note": "Wall-clock medians after one warm-up. Python in-process excludes interpreter start-up; "
                "all CLI rows include process start-up. Other languages' checkers do different work.",
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
