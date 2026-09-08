"""Run with python3 -m talven. No dependency installation is necessary."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import VERSION
from .backend import emit_c
from .context import context, encode, source_hash
from .edit_validation import snapshot_source, validate_edit
from .formatter import format_source
from .frontend import CompileError, MAX_SOURCE_BYTES, Span, analyze
from .source_edit import replace_source, writable_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="talven", description="Talven reference compiler and agent tooling")
    parser.add_argument("--version", action="version", version=f"Talven {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Parse and type/ownership-check without execution")
    check.add_argument("source", type=Path)
    check.add_argument("--json", action="store_true")
    fmt = commands.add_parser("fmt", help="Format source with one canonical, token-preserving layout")
    fmt.add_argument("source", type=Path)
    mode = fmt.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check formatting without writing source")
    mode.add_argument("--write", action="store_true", help="Explicitly replace the source file after freshness checks")
    fmt.add_argument("--json", action="store_true", help="Use structured diagnostics with --check")
    fmt.add_argument("--expect-source-hash", help="Reject an unexpected source revision")
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
    emit.add_argument("--console", action="store_true", help="Enable optional hosted POSIX stdout writes")
    build = commands.add_parser("build", help="Invoke a trusted local C compiler to build a native executable")
    build.add_argument("source", type=Path)
    build.add_argument("-o", "--output", type=Path, required=True)
    build.add_argument("--cc", default="cc", help="Trusted C compiler executable (one path, no shell command)")
    build.add_argument("--console", action="store_true", help="Enable optional hosted POSIX stdout writes")
    commands.add_parser("lsp", help="Start the read-only LSP server over stdio")
    edit = commands.add_parser("edit", help="Create revision-checked read-only edit receipts")
    edit_commands = edit.add_subparsers(dest="edit_command", required=True)
    snapshot = edit_commands.add_parser("snapshot", help="Snapshot an exact source revision")
    snapshot.add_argument("source", type=Path)
    snapshot.add_argument("--include-source", action="store_true")
    snapshot.add_argument("--max-bytes", type=int, default=16384)
    validate = edit_commands.add_parser("validate", help="Validate a candidate against pinned revisions")
    validate.add_argument("source", type=Path)
    validate.add_argument("--candidate", type=Path, required=True)
    validate.add_argument("--expect-source-hash", required=True)
    validate.add_argument("--expect-compiler-hash", required=True)
    validate.add_argument("--max-bytes", type=int, default=16384)
    args = parser.parse_args(argv)
    if args.command == "fmt" and args.json and not args.check:
        parser.error("fmt --json requires --check")
    if args.command == "lsp":
        from .lsp import serve
        return serve(sys.stdin.buffer, sys.stdout.buffer)
    if args.command == "edit":
        if args.edit_command == "snapshot":
            receipt = snapshot_source(args.source, include_source=args.include_source,
                                      max_bytes=args.max_bytes)
        else:
            receipt = validate_edit(args.source, args.candidate,
                                    expected_source_hash=args.expect_source_hash,
                                    expected_compiler_hash=args.expect_compiler_hash,
                                    max_bytes=args.max_bytes)
        print(encode(receipt), end="")
        return 0 if receipt["ok"] else 1
    source = ""
    try:
        if args.command == "fmt" and args.write:
            writable_source(args.source)
        with args.source.open("rb") as stream:
            snapshot = os.fstat(stream.fileno())
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise CompileError("E0005", "Source exceeds the 256 KiB prototype limit", Span(0, 0))
        source = data.decode("utf-8")
        if args.command == "fmt":
            if args.expect_source_hash is not None and args.expect_source_hash != source_hash(source):
                raise CompileError("E0501", "Source revision changed; request fresh source before formatting", Span(0, 0))
            formatted = format_source(source)
            if args.check:
                if formatted != source:
                    raise CompileError("E0601", "Source is not canonically formatted; run talven fmt --write", Span(0, 0))
                if args.json:
                    print(encode({"schema": "talven.diagnostics.v1", "ok": True, "diagnostics": []}), end="")
                else:
                    print("Formatting check passed")
            elif args.write:
                replace_source(args.source, data, formatted, snapshot)
                print(f"Formatted {args.source}" if formatted != source else "Already formatted")
            else:
                sys.stdout.write(formatted)
            return 0
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
            generated = emit_c(result, freestanding=getattr(args, "freestanding", False), console=args.console)
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
