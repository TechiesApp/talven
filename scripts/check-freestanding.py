#!/usr/bin/env python3
"""Build and inspect Talven's native Linux freestanding execution probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "talven.freestanding.v1"
ARCHES = {
    "x86_64": ("Advanced Micro Devices X86-64", "start-x86_64.S"),
    "aarch64": ("AArch64", "start-aarch64.S"),
}
TOOLS = ("cc", "nm", "readelf", "size")
BUILD_TIMEOUT = 30
RUN_TIMEOUT = 5


class ProbeError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_nm_undefined(output: str) -> set[str]:
    symbols: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*(?:[0-9A-Fa-f]+\s+)?U\s+(\S+)\s*", line)
        if not match:
            raise ValueError(f"malformed nm undefined-symbol line: {line!r}")
        symbols.add(match.group(1))
    return symbols


def parse_readelf(output: str, expected_machine: str, start_address: int | None = None) -> dict[str, Any]:
    required = {
        "class": r"^\s*Class:\s+ELF64\s*$",
        "data": r"^\s*Data:\s+2's complement, little endian\s*$",
        "type": r"^\s*Type:\s+EXEC\b",
        "machine": rf"^\s*Machine:\s+{re.escape(expected_machine)}\s*$",
    }
    for label, pattern in required.items():
        if not re.search(pattern, output, re.MULTILINE):
            raise ValueError(f"readelf has wrong or missing {label}")
    entry_match = re.search(r"^\s*Entry point address:\s+0x([0-9A-Fa-f]+)\s*$", output, re.MULTILINE)
    if not entry_match or int(entry_match.group(1), 16) == 0:
        raise ValueError("readelf has missing or zero entry point")
    entry = int(entry_match.group(1), 16)
    if start_address is not None and entry != start_address:
        raise ValueError("ELF entry point does not match _start")
    load_flags: list[str] = []
    stack_flags: str | None = None
    header_row = re.compile(
        r"^\s*(LOAD|GNU_STACK)\s+"
        r"(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+"
        r"(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+([RWE](?:\s*[RWE])*)\s+"
        r"(0x[0-9A-Fa-f]+)\s*$"
    )
    for line in output.splitlines():
        stripped = line.lstrip()
        if not (stripped.startswith("LOAD") or stripped.startswith("GNU_STACK")):
            continue
        match = header_row.fullmatch(line)
        if not match:
            raise ValueError(f"malformed {stripped.split()[0]} program header")
        kind, flags = match.group(1), "".join(match.group(7).split())
        if len(set(flags)) != len(flags):
            raise ValueError(f"malformed {kind} program header flags")
        if kind == "LOAD":
            load_flags.append(flags)
        else:
            if stack_flags is not None:
                raise ValueError("duplicate GNU_STACK program header")
            stack_flags = flags
    if not load_flags:
        raise ValueError("readelf contains no LOAD program headers")
    if any("W" in value and "E" in value for value in load_flags):
        raise ValueError("ELF contains a writable/executable LOAD segment")
    if stack_flags is None or "E" in stack_flags:
        raise ValueError("GNU_STACK is missing or executable")
    if re.search(r"^\s*(INTERP|DYNAMIC)\b", output, re.MULTILINE):
        raise ValueError("ELF contains an interpreter or dynamic program header")
    if re.search(r"\(NEEDED\)", output) or not re.search(
        r"There is no dynamic section in this file\.", output
    ):
        raise ValueError("ELF contains or ambiguously reports a dynamic section")
    return {"entry": entry, "load_flags": load_flags, "gnu_stack_flags": stack_flags}


def parse_size(output: str) -> dict[str, int]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 2 or lines[0].split()[:4] != ["text", "data", "bss", "dec"]:
        raise ValueError("malformed GNU size header")
    fields = lines[1].split(maxsplit=5)
    if len(fields) != 6 or not all(re.fullmatch(r"\d+", item) for item in fields[:4]):
        raise ValueError("malformed GNU size result row")
    text, data, bss, dec = map(int, fields[:4])
    if dec != text + data + bss:
        raise ValueError("GNU size total does not match sections")
    if not re.fullmatch(r"[0-9A-Fa-f]+", fields[4]) or int(fields[4], 16) != dec:
        raise ValueError("GNU size hexadecimal total does not match sections")
    return {"text_bytes": text, "data_bytes": data, "bss_bytes": bss}


def parse_start_symbol(output: str) -> int:
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < 3 or rows[0][-1] != "_start" or not re.fullmatch(r"[0-9A-Fa-f]+", rows[0][0]):
        raise ValueError("malformed or ambiguous _start symbol")
    value = int(rows[0][0], 16)
    if value == 0:
        raise ValueError("_start has zero address")
    return value


def success_driver() -> str:
    return r'''#include <stdint.h>
#include <limits.h>
extern int32_t tv_f_add_value(int32_t, int32_t);
extern int32_t tv_f_subtract_value(int32_t, int32_t);
extern int32_t tv_f_multiply_value(int32_t, int32_t);
extern int32_t tv_f_divide_value(int32_t, int32_t);
extern int32_t tv_f_remainder_value(int32_t, int32_t);
extern int32_t tv_f_negate_value(int32_t);
extern int32_t tv_f_ordered(int32_t, int32_t);
int talven_probe(void) {
  if (tv_f_add_value(17, -9) != 8 || tv_f_add_value(INT32_MAX, 0) != INT32_MAX) return 1;
  if (tv_f_subtract_value(-12, -7) != -5 || tv_f_subtract_value(INT32_MIN, 0) != INT32_MIN) return 1;
  if (tv_f_multiply_value(-123, 17) != -2091 || tv_f_multiply_value(0, INT32_MIN) != 0) return 1;
  if (tv_f_divide_value(-17, 5) != -3 || tv_f_divide_value(17, -5) != -3) return 1;
  if (tv_f_remainder_value(-17, 5) != -2 || tv_f_remainder_value(17, -5) != 2) return 1;
  if (tv_f_negate_value(-37) != 37 || tv_f_negate_value(0) != 0) return 1;
  if (tv_f_ordered(2, 3) != 20508 || tv_f_ordered(-2, 3) != -19896) return 1;
  if (tv_f_ordered(0, 0) != 0 || tv_f_ordered(10, -3) != 100704) return 1;
  return 0;
}
'''


TRAPS = {
    "add-overflow": ("add_value", "INT32_MAX, 1"),
    "subtract-overflow": ("subtract_value", "INT32_MIN, 1"),
    "multiply-overflow": ("multiply_value", "46341, 46341"),
    "negate-overflow": ("negate_value", "INT32_MIN"),
    "divide-zero": ("divide_value", "1, 0"),
    "divide-overflow": ("divide_value", "INT32_MIN, -1"),
    "remainder-zero": ("remainder_value", "1, 0"),
    "remainder-overflow": ("remainder_value", "INT32_MIN, -1"),
}


def trap_driver(function: str, arguments: str) -> str:
    arity = 1 if "," not in arguments else 2
    params = "int32_t" if arity == 1 else "int32_t, int32_t"
    return ("#include <stdint.h>\n#include <limits.h>\n"
            f"extern int32_t tv_f_{function}({params});\n"
            f"int talven_probe(void) {{ (void)tv_f_{function}({arguments}); return 1; }}\n")


def command(report: dict[str, Any], argv: Sequence[str], stage: str, timeout: int, *, allow_empty: bool = False,
            check: bool = True) -> subprocess.CompletedProcess[str]:
    def normalized(value: str | bytes | None) -> str:
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""

    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, cwd=ROOT,
                                env={**os.environ, "LC_ALL": "C"})
    except subprocess.TimeoutExpired as error:
        report["commands"].append({"argv": list(argv), "stage": stage, "timeout_seconds": timeout,
                                   "timed_out": True, "stdout": normalized(error.stdout), "stderr": normalized(error.stderr)})
        raise ProbeError(stage, f"command timed out after {timeout} seconds") from error
    report["commands"].append({"argv": list(argv), "stage": stage, "timeout_seconds": timeout,
                               "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    if check and result.returncode != 0:
        raise ProbeError(stage, f"command exited {result.returncode}: {argv[0]}")
    if not allow_empty and not result.stdout.strip() and not result.stderr.strip():
        raise ProbeError(stage, f"command unexpectedly produced no output: {argv[0]}")
    return result


def git_details(report: dict[str, Any]) -> dict[str, Any]:
    revision = command(report, ["git", "-C", str(ROOT), "rev-parse", "HEAD"], "provenance", BUILD_TIMEOUT).stdout.strip()
    dirty = bool(command(report, ["git", "-C", str(ROOT), "status", "--porcelain"], "provenance", BUILD_TIMEOUT, allow_empty=True).stdout)
    return {"revision": revision, "dirty": dirty}


def preflight(out_text: str, expect_arch: str | None) -> tuple[Path, str, dict[str, str]]:
    if not out_text.strip():
        raise ProbeError("preflight", "--out must not be empty")
    out = Path(out_text).expanduser().resolve()
    if out.exists():
        raise ProbeError("preflight", f"output path already exists: {out}")
    system, machine = platform.system(), platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if system != "Linux" or machine not in ARCHES:
        raise ProbeError("preflight", f"requires native Linux x86_64/aarch64; actual {system} {platform.machine()}")
    if expect_arch and expect_arch != machine:
        raise ProbeError("preflight", f"expected {expect_arch}, actual {machine}")
    resolved = {name: shutil.which(name) or "" for name in TOOLS}
    missing = [name for name, value in resolved.items() if not value]
    if missing:
        raise ProbeError("preflight", "missing required tools: " + ", ".join(missing))
    inputs = [ROOT / "experiments/freestanding/probe.tal", ROOT / "experiments/freestanding" / ARCHES[machine][1]]
    absent = [str(path) for path in inputs if not path.is_file()]
    if absent:
        raise ProbeError("preflight", "missing inputs: " + ", ".join(absent))
    return out, machine, resolved


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if ":" in line and line.split(":", 1)[0].strip() in {"model name", "Model"}:
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    except (OSError, UnicodeError):
        pass
    return "unknown"


def run_probe(out_text: str, expect_arch: str | None = None) -> dict[str, Any]:
    out, arch, tools = preflight(out_text, expect_arch)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    report: dict[str, Any] = {"schema": SCHEMA, "passed": False, "stage": "initializing", "commands": [], "cases": []}
    report_path = out / "report.json"
    try:
        source = ROOT / "experiments/freestanding/probe.tal"
        startup = ROOT / "experiments/freestanding" / ARCHES[arch][1]
        archive = out / "inputs"
        archive.mkdir()
        archived_source, archived_startup = archive / source.name, archive / startup.name
        shutil.copy2(source, archived_source)
        shutil.copy2(startup, archived_startup)
        shutil.copy2(Path(__file__), archive / Path(__file__).name)
        compiler_inputs = sorted((ROOT / "talven").glob("*.py"))
        compiler_archive = archive / "talven"
        compiler_archive.mkdir()
        for compiler_input in compiler_inputs:
            shutil.copy2(compiler_input, compiler_archive / compiler_input.name)
        sys.path.insert(0, str(ROOT))
        from talven.backend import emit_c
        from talven.context import compiler_hash
        from talven.frontend import analyze
        generated = emit_c(analyze(archived_source.read_text(encoding="utf-8")), freestanding=True)
        generated_path = out / "generated.c"
        generated_path.write_text(generated, encoding="utf-8")
        report.update({
            "host": {"system": platform.system(), "machine": platform.machine(), "arch": arch,
                     "cpu_model": cpu_model(),
                     "python": platform.python_version(), "implementation": platform.python_implementation()},
            "git": git_details(report), "compiler_hash": compiler_hash(),
            "inputs": {path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
                       for path in (source, startup, Path(__file__))},
            "compiler_inputs": {path.relative_to(ROOT).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
                                for path in compiler_inputs},
            "generated_c": {"sha256": sha256(generated_path), "bytes": generated_path.stat().st_size},
            "tools": {}, "flags": {},
        })
        for name, executable in tools.items():
            version_args = [executable, "--version"] if name != "cc" else [executable, "--version"]
            version = command(report, version_args, "tool-version", BUILD_TIMEOUT).stdout.splitlines()[0]
            item: dict[str, Any] = {"path": str(Path(executable).resolve()), "version": version,
                                    "sha256": sha256(Path(executable).resolve())}
            if name == "cc":
                item["target"] = command(report, [executable, "-dumpmachine"], "tool-version", BUILD_TIMEOUT).stdout.strip()
            report["tools"][name] = item
        common = ["-std=c11", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pie", "-fno-lto",
                  "-fno-unwind-tables", "-fno-asynchronous-unwind-tables"]
        link = ["-nostdlib", "-static", "-no-pie", "-fno-lto", "-Wl,-e,_start", "-Wl,--build-id=none", "-Wl,-z,noexecstack"]
        report["flags"] = {"compile_common": common, "link": link}
        for optimization in ("-O0", "-O2"):
            optdir = out / optimization[1:]
            optdir.mkdir()
            gen_obj, start_obj = optdir / "generated.o", optdir / "startup.o"
            command(report, [tools["cc"], *common, optimization, "-c", str(generated_path), "-o", str(gen_obj)], "compile-generated", BUILD_TIMEOUT, allow_empty=True)
            command(report, [tools["cc"], *common, optimization, "-c", str(archived_startup), "-o", str(start_obj)], "compile-startup", BUILD_TIMEOUT, allow_empty=True)
            undefined_raw = command(report, [tools["nm"], "-u", str(gen_obj)], "inspect-generated-symbols", BUILD_TIMEOUT).stdout
            if parse_nm_undefined(undefined_raw) != {"talven_trap"}:
                raise ProbeError("inspect-generated-symbols", "generated object undefined symbols are not exactly {talven_trap}")
            drivers = {"success": success_driver(), **{name: trap_driver(*spec) for name, spec in TRAPS.items()}}
            for case_name, driver in drivers.items():
                case_dir = optdir / case_name
                case_dir.mkdir()
                driver_path, driver_obj, binary = case_dir / "driver.c", case_dir / "driver.o", case_dir / "probe"
                driver_path.write_text(driver, encoding="utf-8")
                command(report, [tools["cc"], *common, optimization, "-c", str(driver_path), "-o", str(driver_obj)], "compile-driver", BUILD_TIMEOUT, allow_empty=True)
                command(report, [tools["cc"], *link, str(start_obj), str(gen_obj), str(driver_obj), "-o", str(binary)], "link", BUILD_TIMEOUT, allow_empty=True)
                final_nm = command(report, [tools["nm"], "-u", str(binary)], "inspect-final-symbols", BUILD_TIMEOUT, allow_empty=True).stdout
                if parse_nm_undefined(final_nm):
                    raise ProbeError("inspect-final-symbols", "final executable has undefined symbols")
                start_raw = command(report, [tools["nm"], "-n", "--defined-only", str(binary)], "inspect-entry", BUILD_TIMEOUT).stdout
                start_lines = "\n".join(line for line in start_raw.splitlines() if line.split() and line.split()[-1] == "_start")
                start_address = parse_start_symbol(start_lines)
                elf_raw = command(report, [tools["readelf"], "-h", "-l", "-d", "-W", str(binary)], "inspect-elf", BUILD_TIMEOUT).stdout
                elf = parse_readelf(elf_raw, ARCHES[arch][0], start_address)
                size_raw = command(report, [tools["size"], "--format=berkeley", "--radix=10", str(binary)], "measure-sections", BUILD_TIMEOUT).stdout
                sections = parse_size(size_raw)
                expected = 0 if case_name == "success" else 97
                execution = command(report, [str(binary)], "execute", RUN_TIMEOUT, allow_empty=True, check=False)
                actual = execution.returncode
                case = {"name": case_name, "optimization": optimization, "expected_exit": expected,
                        "actual_exit": actual, "passed": actual == expected, "driver_bytes": driver_path.stat().st_size,
                        "driver_sha256": sha256(driver_path), "binary_sha256": sha256(binary),
                        "file_bytes": binary.stat().st_size, "section_measurement": sections, "elf": elf}
                report["cases"].append(case)
                if actual != expected:
                    raise ProbeError("execute", f"{optimization} {case_name}: expected exit {expected}, got {actual}")
        current_inputs = [source, startup, Path(__file__), *compiler_inputs]
        for original in current_inputs:
            if original in (source, startup):
                archived = archived_source if original == source else archived_startup
            elif original == Path(__file__):
                archived = archive / original.name
            else:
                archived = compiler_archive / original.name
            if sha256(original) != sha256(archived):
                raise ProbeError("input-freshness", f"input changed during validation: {original.relative_to(ROOT)}")
        report.update({"passed": True, "stage": "complete", "claim_scope":
                       "Native Linux process execution of freestanding-generated C without libc or heap allocation; not a board or bare-metal port."})
    except Exception as error:
        report["passed"] = False
        report["stage"] = error.stage if isinstance(error, ProbeError) else "internal"
        report["error"] = str(error)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-arch", choices=sorted(ARCHES))
    args = parser.parse_args(argv)
    try:
        report = run_probe(args.out, args.expect_arch)
    except ProbeError as error:
        report = {"schema": SCHEMA, "passed": False, "stage": error.stage, "error": str(error)}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
