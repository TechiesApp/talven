# Freestanding Linux validation

Measured on 8 September 2026. This records actual execution of the [bounded Linux probe](freestanding.md) through the unchanged Talven compiler. It establishes that this arithmetic/borrowing program can execute without libc, CRT startup, libgcc, a dynamic loader, or heap allocation. It remains a Linux process, not a bare-metal or board port. No model calls were made.

## Linux ARM64 environment

The checkout was mounted read-only in a Linux ARM64 container, with the ignored build directory writable:

| Input | Observed value |
| --- | --- |
| Container | `python:3.11-bookworm`, image digest `sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca` |
| Actual host | Linux `aarch64` |
| CPU model | `unknown`, as reported by the container; no particular CPU model is inferred |
| Python | CPython 3.11.16 |
| C compiler | Debian GCC 12.2.0-14+deb12u1; target `aarch64-linux-gnu` |
| Inspection tools | GNU `nm`, `readelf`, and `size`, binutils 2.40 |
| Talven compiler hash | `e5c4c8973de267594e32d403a646c0c783178c6dfaf32af64f25b0551728bb69` |
| Probe source SHA-256 | `803c08271479bdc61d3efed0f7d5f56544c32566afcb127224ab46f5b9bca560` |
| Generated C SHA-256 | `be767a9222673ecb1f18e9d29b688eb20f3fdab4e2729cd011d6c3a51d6776bb` |

The local archive records base revision `ff4506f7ddea557309d74d8a9b37540e3ad96a34` with a dirty working tree, preserving the exact probe, startup, validator, compiler inputs, generated C, drivers, objects, and binaries. This is development verification evidence, not a clean-release benchmark. The JSON report retains tool paths, versions and executable hashes, per-input and per-binary hashes, exact argument lists, captured inspection output, and execution results.

For both `-O0` and `-O2`, compilation used `-std=c11 -ffreestanding -fno-builtin -fno-stack-protector -fno-pie -fno-lto -fno-unwind-tables -fno-asynchronous-unwind-tables`. Linking used `-nostdlib -static -no-pie -fno-lto -Wl,-e,_start -Wl,--build-id=none -Wl,-z,noexecstack` with only the startup, generated program, and independent driver objects. No default runtime library was supplied.

## Executions and measured sizes

All **18 executions passed**: one success executable and eight trap executables at each optimization level. The independent success driver checked full i32 arithmetic values and four ordered-mutation results, then exited zero. Each overflow or invalid-division/remainder case exited through the explicit trap with status **97**. Normal return, a different exit, or a signal would fail.

| Optimization and driver | Executable file bytes | Berkeley text bytes | Data bytes | BSS bytes |
| --- | --- | --- | --- | --- |
| `-O0`, success | 3,624 | 1,680 | 0 | 0 |
| `-O2`, success | 2,800 | 1,072 | 0 | 0 |
| `-O0`, negation trap | 3,216 | 1,268 | 0 | 0 |
| `-O0`, each other trap | 3,216 | 1,272 | 0 | 0 |
| `-O2`, negation trap | 2,464 | 732 | 0 | 0 |
| `-O2`, each other trap | 2,464 | 736 | 0 | 0 |

These measurements include startup, the whole generated probe, and the selected C driver. File length includes ELF metadata and non-loaded material; Berkeley text includes read-only data. Neither is peak RAM, stack consumption, RSS, or startup latency. Zero data/BSS does not mean zero process memory: Linux still maps the executable and initial stack.

Every generated object had exactly one undefined symbol, `talven_trap`, supplied by the startup object. Every final executable had no undefined symbols, interpreter, dynamic segment, or dynamic dependencies. Each was an ELF64 little-endian AArch64 `EXEC`, with entry address `0x4000b0` matching `_start`, a read/execute load segment, and a read/write non-executable GNU stack. No writable/executable load segment was present.

## Regression verification

- Full unittest discovery: **175 tests passed, zero skips**. The existing 163 tests, compiler, evaluation runner, and corpora remain unchanged; the new file adds 12 portable inspector/CLI tests.
- Borrowing sanitizers: **six ASan/UBSan executions passed** across `-O0` and `-O2`.
- Native CLI examples: vectors and borrowing both built and exited zero.
- Formatting: all **12** Talven example/corpus/fixture files passed, including the new probe.
- Original and borrowing offline fixtures: each completed **8/8** trials, with 16 adapter calls and eight repairs, followed by eight successful independent reverifications.
- Anthropic offline fixtures: `strict-type` and `borrow-permission` each completed **2/2** trials, with four adapter calls and two repairs, followed by two successful independent reverifications.

The fixture model remains `fixture-messages-v1` with tokenizer declaration `fixture: no tokenizer`. Token and cost totals remain **null**. These are scripted verification results, not measurements of model effectiveness or spending.

Independent review identified an inspector defect that accepted truncated program-header rows or hid an executable stack behind a second stack header. The final parser requires complete hexadecimal columns and rejects duplicate stack headers. Portable regressions cover those cases and targeted dependency/permission failures. Review found no remaining blocking issue after the correction. The native executions and sizes above include the corrected parser.

The 12 portable tests also passed on macOS ARM64/Python 3.14.4. An actual native-probe invocation on that host failed explicitly at preflight with `Darwin arm64`, without creating the requested output directory. No macOS freestanding execution or sanitizer result is claimed.

## CI and remaining evidence

The existing protected native jobs now run the probe on Linux x86-64/Python 3.11, x86-64/Python 3.12, and ARM64/Python 3.12, alongside the full suite, fixtures, examples, formatting, and sanitizers. Documentation links and Mermaid rendering are checked separately. Configuration alone is not execution evidence; completed run results are available in the introducing PR's checks. The size table above comes only from the declared local ARM64 run and must not be attributed to other targets or toolchains.

No peak-memory, bounded-stack, timing, board-support, stable-ABI, or live-agent result is established. The separate M1 controlled-agent evaluation gate remains open.
