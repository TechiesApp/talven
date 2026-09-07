"""Run with python3 -m talven. No dependency installation is necessary."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import VERSION
from .backend import emit_c
from .context import context, encode
from .frontend import CompileError, MAX_SOURCE_BYTES, Span, analyze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="talven", description="Talven M1a reference compiler")
    parser.add_argument("--version", action="version", version=f"Talven {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Parse and type/ownership-check without execution")
    check.add_argument("source", type=Path)
    check.add_argument("--json", action="store_true")
    ctx = commands.add_parser("context", help="Return bounded, deterministic compiler-derived JSON")
    ctx.add_argument("source", type=Path)
    ctx.add_argument("--symbol")
    ctx.add_argument("--max-bytes", type=int, default=16384)
    ctx.add_argument("--expect-source-hash")
    ctx.add_argument("--freestanding", action="store_true")
    ctx.add_argument("--include-body", action="store_true", help="Include selected source as untrusted text data")
    emit = commands.add_parser("emit-c", help="Emit checked C11 without executing a C compiler")
    emit.add_argument("source", type=Path)
    emit.add_argument("-o", "--output", type=Path)
    emit.add_argument("--freestanding", action="store_true")
    build = commands.add_parser("build", help="Invoke a trusted local C compiler to build a native executable")
    build.add_argument("source", type=Path)
    build.add_argument("-o", "--output", type=Path, required=True)
    build.add_argument("--cc", default="cc", help="Trusted C compiler executable (one path, no shell command)")
    commands.add_parser("lsp", help="Start the read-only LSP server over stdio")
    args = parser.parse_args(argv)
    if args.command == "lsp":
        from .lsp import serve
        return serve(sys.stdin.buffer, sys.stdout.buffer)
    source = ""
    try:
        with args.source.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise CompileError("E0005", "Source exceeds the 256 KiB prototype limit", Span(0, 0))
        source = data.decode("utf-8")
        result = analyze(source)
        if args.command == "check":
            if args.json:
                print(encode({"schema": "talven.diagnostics.v1", "ok": True, "diagnostics": []}), end="")
            else:
                print("Check passed")
        elif args.command == "context":
            print(context(result, args.symbol, args.max_bytes, args.expect_source_hash,
                          args.freestanding, args.include_body), end="")
        else:
            output = args.output
            if output is not None and (output.resolve() == args.source.resolve()
                                       or (output.exists() and output.samefile(args.source))):
                raise CompileError("E0403", "Output must not overwrite the source file", Span(0, 0))
            generated = emit_c(result, freestanding=getattr(args, "freestanding", False))
            if args.command == "emit-c":
                if output:
                    output.write_text(generated, encoding="utf-8")
                else:
                    print(generated, end="")
            else:
                output = output.resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="talven-build-", dir=output.parent) as temporary:
                    directory = Path(temporary)
                    cfile, executable = directory / "program.c", directory / "program"
                    cfile.write_text(generated, encoding="utf-8")
                    completed = subprocess.run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic-errors",
                                                str(cfile), "-o", str(executable)], capture_output=True, text=True, timeout=30)
                    if completed.returncode:
                        raise CompileError("E0402", f"C compiler failed: {completed.stderr.strip()}", Span(0, 0))
                    os.replace(executable, output)
                print(f"Built {output}")
        return 0
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        failure = CompileError("E0901", str(error), Span(0, 0))
    except CompileError as error:
        failure = error
    diagnostic = failure.diagnostic(source)
    if args.command == "context" or getattr(args, "json", False):
        print(encode({"schema": "talven.diagnostics.v1", "ok": False, "diagnostics": [diagnostic]}), end="")
    else:
        start = diagnostic["range"]["start"]
        print(f"{args.source}:{start['line'] + 1}:{start['character'] + 1}: {failure.code}: {failure.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
