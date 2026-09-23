#!/usr/bin/env python3
"""Compare Talven with C, Rust, Go, Java, and TypeScript on three small workloads.

1. check:  type-check or compile an equivalent 300-function program
           (Talven native/Python check, clang -fsyntax-only, rustc --emit=metadata,
           go tool compile, javac, tsc --noEmit)
2. hello:  build Hello World, then record the artifact size and start-to-exit time
3. fib:    recursive fib(35) with each toolchain's default release settings

Every command must succeed and every program must return the expected result, or
the run fails. Wall-clock medians after one warm-up; all rows include process
start-up. Each language does different work (richer type systems, runtimes, JIT),
so these numbers give scale for a developer, not a like-for-like language race.

Usage: python3 scripts/benchmark-languages.py --native PATH --tsc PATH --out results.json
"""
import argparse
import importlib.util
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
_spec = importlib.util.spec_from_file_location("frontends", ROOT / "scripts/benchmark-frontends.py")
frontends = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frontends)

FIB_N, FIB_EXPECTED = 35, 9227465


def go_program(functions):
    parts = ["package main"]
    for i in range(functions):
        call = f"f{i - 1}(a, b)" if i else "a - b"
        parts.append(f"func f{i}(a int32, b int32) int32 {{ c := a*3 + b%7; "
                     f"if c > 100 && b != 0 {{ return c / 2 }}; return c + {call} }}")
    parts.append(f"func main() {{ if f{functions - 1}(1, 2) != f{functions - 1}(1, 2) {{ panic(\"mismatch\") }} }}")
    return "\n".join(parts) + "\n"


def java_program(functions):
    parts = ["public class Main {"]
    for i in range(functions):
        call = f"f{i - 1}(a, b)" if i else "a - b"
        parts.append(f"static int f{i}(int a, int b) {{ int c = a * 3 + b % 7; "
                     f"if (c > 100 && b != 0) {{ return c / 2; }} return c + {call}; }}")
    parts.append(f"public static void main(String[] args) {{ System.exit(f{functions - 1}(1, 2) - "
                 f"f{functions - 1}(1, 2)); }} }}")
    return "\n".join(parts) + "\n"


def ts_program(functions):
    parts = []
    for i in range(functions):
        call = f"f{i - 1}(a, b)" if i else "a - b"
        parts.append(f"function f{i}(a: number, b: number): number {{ const c = a * 3 + b % 7; "
                     f"if (c > 100 && b !== 0) {{ return Math.trunc(c / 2); }} return c + {call}; }}")
    parts.append(f"process.exit(f{functions - 1}(1, 2) - f{functions - 1}(1, 2));")
    return "declare const process: {{ exit(code: number): never }};\n".replace("{{", "{").replace("}}", "}") + \
        "\n".join(parts) + "\n"


HELLO = {
    "talven": ("hello.tal", 'fn main() -> i32 {\n    return print("Hello, world!\\n");\n}\n'),
    "c": ("hello.c", '#include <stdio.h>\nint main(void) { fputs("Hello, world!\\n", stdout); return 0; }\n'),
    "rust": ("hello.rs", 'fn main() { print!("Hello, world!\\n"); }\n'),
    "go": ("hello.go", 'package main\nimport "os"\nfunc main() { os.Stdout.WriteString("Hello, world!\\n") }\n'),
    "java": ("Hello.java", 'public class Hello { public static void main(String[] a) { '
                           'System.out.print("Hello, world!\\n"); } }\n'),
    "typescript": ("hello.ts", 'declare const process: { stdout: { write(s: string): boolean } };\n'
                               'process.stdout.write("Hello, world!\\n");\n'),
}

FIB = {
    "talven": ("fib.tal", f"""fn fib(n: i32) -> i32 {{
    if (n < 2) {{
        return n;
    }}
    return fib(n - 1) + fib(n - 2);
}}

fn main() -> i32 {{
    if (fib({FIB_N}) == {FIB_EXPECTED}) {{
        return 0;
    }}
    return 1;
}}
"""),
    "c": ("fib.c", f"#include <stdint.h>\nstatic int32_t fib(int32_t n) {{ return n < 2 ? n : fib(n - 1) + fib(n - 2); }}\n"
                   f"int main(void) {{ return fib({FIB_N}) == {FIB_EXPECTED} ? 0 : 1; }}\n"),
    "rust": ("fib.rs", f"fn fib(n: i32) -> i32 {{ if n < 2 {{ n }} else {{ fib(n - 1) + fib(n - 2) }} }}\n"
                       f"fn main() {{ std::process::exit(if fib({FIB_N}) == {FIB_EXPECTED} {{ 0 }} else {{ 1 }}); }}\n"),
    "go": ("fib.go", f"package main\nimport \"os\"\nfunc fib(n int32) int32 {{ if n < 2 {{ return n }}; "
                     f"return fib(n-1) + fib(n-2) }}\nfunc main() {{ if fib({FIB_N}) != {FIB_EXPECTED} {{ os.Exit(1) }} }}\n"),
    "java": ("Fib.java", f"public class Fib {{ static int fib(int n) {{ return n < 2 ? n : fib(n - 1) + fib(n - 2); }} "
                         f"public static void main(String[] a) {{ System.exit(fib({FIB_N}) == {FIB_EXPECTED} ? 0 : 1); }} }}\n"),
    "typescript": ("fib.ts", "declare const process: { exit(code: number): never };\n"
                             "function fib(n: number): number { return n < 2 ? n : fib(n - 1) + fib(n - 2); }\n"
                             f"process.exit(fib({FIB_N}) === {FIB_EXPECTED} ? 0 : 1);\n"),
}


def run(argv, cwd, expect_stdout=None):
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=300)
    if completed.returncode != 0:
        raise SystemExit(f"command failed: {argv}\n{completed.stderr.decode(errors='replace')[-2000:]}")
    if expect_stdout is not None and completed.stdout != expect_stdout:
        raise SystemExit(f"unexpected output from {argv}: {completed.stdout!r}")


def timed(argv, cwd, repetitions, expect_stdout=None):
    run(argv, cwd, expect_stdout)  # Warm-up and correctness check; excluded.
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        run(argv, cwd, expect_stdout)
        samples.append((time.perf_counter() - started) * 1000)
    return {"median_ms": round(statistics.median(samples), 3), "min_ms": round(min(samples), 3),
            "max_ms": round(max(samples), 3), "samples": len(samples)}


def build(language, directory, name, tools):
    """Build one program; return (run argv, artifact paths, runtime note)."""
    source = directory / name
    stem = source.stem
    if language == "talven":
        exe = directory / f"{stem}-talven"
        console = ["--console"] if "print(" in source.read_text() else []
        run([sys.executable, "-m", "talven", "build", str(source), *console, "-o", str(exe)], ROOT)
        return [str(exe)], [exe], "none (native executable)"
    if language == "c":
        exe = directory / f"{stem}-c"
        run([tools["cc"], "-std=c11", "-O2", str(source), "-o", str(exe)], directory)
        return [str(exe)], [exe], "none (native executable)"
    if language == "rust":
        exe = directory / f"{stem}-rust"
        run([tools["rustc"], "-O", "--edition", "2021", str(source), "-o", str(exe)], directory)
        return [str(exe)], [exe], "none (native executable)"
    if language == "go":
        exe = directory / f"{stem}-go"
        env_dir = directory / f"go-{stem}"
        env_dir.mkdir(exist_ok=True)
        shutil.copy(source, env_dir / "main.go")
        (env_dir / "go.mod").write_text("module bench\n\ngo 1.21\n")
        run([tools["go"], "build", "-o", str(exe), "."], env_dir)
        return [str(exe)], [exe], "none (native executable)"
    if language == "java":
        out = directory / f"java-{stem}"
        out.mkdir(exist_ok=True)
        run([tools["javac"], "-d", str(out), str(source)], directory)
        return [tools["java"], "-cp", str(out), stem], list(out.glob("*.class")), "Java runtime (JVM)"
    if language == "typescript":
        out = directory / f"ts-{stem}"
        run([tools["tsc"], "--target", "es2022", "--outDir", str(out), str(source)], directory)
        return [tools["node"], str(out / f"{stem}.js")], [out / f"{stem}.js"], "Node.js runtime"
    raise ValueError(language)


def version(argv):
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return (completed.stdout or completed.stderr).strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--native", type=Path, required=True, help="talven-native release binary")
    parser.add_argument("--tsc", required=True, help="TypeScript compiler executable")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=9)
    parser.add_argument("--functions", type=int, default=300)
    args = parser.parse_args()
    tools = {name: shutil.which(name) for name in ("cc", "rustc", "go", "javac", "java", "node")}
    tools["tsc"] = str(Path(args.tsc).resolve(strict=True))
    missing = [name for name, path in tools.items() if not path]
    if missing:
        raise SystemExit(f"missing toolchains: {missing}")
    reps = args.repetitions
    results = {"check": {}, "hello": {}, "fib": {}}
    with tempfile.TemporaryDirectory(prefix="talven-lang-bench-") as temporary:
        d = Path(temporary)
        n = args.functions
        sources = {"talven": ("p.tal", frontends.talven_program(n)), "c": ("p.c", frontends.c_program(n)),
                   "rust": ("p.rs", frontends.rust_program(n)), "go": ("p.go", go_program(n)),
                   "java": ("Main.java", java_program(n)), "typescript": ("p.ts", ts_program(n))}
        for language, (name, text) in sources.items():
            (d / name).write_text(text)
        go_dir = d / "go-check"
        go_dir.mkdir()
        shutil.copy(d / "p.go", go_dir / "main.go")
        (go_dir / "go.mod").write_text("module bench\n\ngo 1.21\n")
        (d / "java-check").mkdir()
        checks = {
            "Talven (native check)": ([str(args.native.resolve(strict=True)), "check", str(d / "p.tal")], d),
            "Talven (Python reference check)": ([sys.executable, "-m", "talven", "check", str(d / "p.tal")], ROOT),
            "C (clang -fsyntax-only)": ([tools["cc"], "-std=c11", "-fsyntax-only", str(d / "p.c")], d),
            "Rust (rustc --emit=metadata)": ([tools["rustc"], "--edition", "2021", "--emit=metadata", "--crate-type",
                                              "bin", "-o", str(d / "p.rmeta"), str(d / "p.rs")], d),
            # go build reuses its build cache between runs; compile the package directly instead.
            "Go (go tool compile)": ([tools["go"], "tool", "compile", "-p", "main", "-o", str(d / "p-go.o"),
                                     str(go_dir / "main.go")], d),
            "Java (javac)": ([tools["javac"], "-d", str(d / "java-check"), str(d / "Main.java")], d),
            "TypeScript (tsc --noEmit)": ([tools["tsc"], "--noEmit", "--target", "es2022", str(d / "p.ts")], d),
        }
        for label, (argv, cwd) in checks.items():
            results["check"][label] = timed(argv, cwd, reps)
            print("check", label, results["check"][label]["median_ms"], flush=True)
        for workload, programs in (("hello", HELLO), ("fib", FIB)):
            for language, (name, text) in programs.items():
                (d / name).write_text(text)
                argv, artifacts, runtime = build(language, d, name, tools)
                expected = b"Hello, world!\n" if workload == "hello" else None
                row = timed(argv, d, reps, expected)
                row.update(artifact_bytes=sum(path.stat().st_size for path in artifacts), runtime_required=runtime)
                results[workload][language] = row
                print(workload, language, row["median_ms"], row["artifact_bytes"], flush=True)
        source_bytes = {language: len(text.encode()) for language, (_, text) in sources.items()}
    evidence = {
        "schema": "talven.language-benchmark.v1",
        "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                 "logical_cpus": os.cpu_count(), "python": platform.python_version()},
        "tools": {"cc": version([tools["cc"], "--version"]), "rustc": version([tools["rustc"], "--version"]),
                  "go": version([tools["go"], "version"]), "javac": version([tools["javac"], "-version"]),
                  "java": version([tools["java"], "-version"]), "node": version([tools["node"], "--version"]),
                  "tsc": version([tools["tsc"], "--version"])},
        "settings": {"repetitions": reps, "check_program_functions": args.functions,
                     "check_program_source_bytes": source_bytes, "fib_n": FIB_N,
                     "release_flags": {"talven": "talven build (C11, cc -O2)", "c": "-O2", "rust": "-O",
                                       "go": "go build (default)", "java": "javac; java (default JIT)",
                                       "typescript": "tsc --target es2022; node"}},
        "note": "Wall-clock medians after one warm-up, including process start-up. Languages do different work; "
                "treat as scale, not a like-for-like race.",
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
