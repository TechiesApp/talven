# Native scalar compiler experiment

Status: bounded Rust prototype, `native-scalar-text-v1`. This is an implementation experiment under [Proposal 0013](../../docs/proposals/0013-native-scalar-compiler.md), not a replacement for the full Python reference or a production toolchain selection. It directly parses, checks, and emits C11; it never launches Python, a shell, or another compiler.

## Build and run

Build with Rust/Cargo 1.96.0. There are no third-party crates. The checked-in lockfile and explicit release settings describe the experiment; Rust is needed to build the compiler, not to invoke the resulting executable.

~~~sh
cargo +1.96.0 build --release --offline --locked --manifest-path experiments/native-compiler/Cargo.toml
experiments/native-compiler/target/release/talven-native check examples/hello.tal --json
mkdir -p build
experiments/native-compiler/target/release/talven-native emit-c examples/hello.tal --console > build/native-hello.c
cc -std=c11 -O2 -Wall -Wextra -pedantic-errors build/native-hello.c -o build/native-hello
./build/native-hello
~~~

Install the pinned Rust toolchain first if absent. This does not provide a native `build` driver, formatter, context API, LSP, watch integration, installer, freestanding backend, or incremental compiler. `emit-c` writes to stdout without modifying source. The shell/C compiler steps above remain explicit. Redirect to a separate output path: shell redirection can truncate a source before the compiler starts.

The current hosted experiment targets Linux aarch64 and x86-64, exercised by the repository CI. macOS has an input-opening implementation and local tests, not a complete supported target profile. Other operating systems reject source opening. Both the compiler and generated executable may depend on host libraries; neither is a statically linked or single-dependency distribution claim. The compiler uses Rust's heap and standard library; emitted Talven text/arithmetic introduces no new language allocator or managed runtime.

## Declared subset

- `i32`, `bool`, static immutable `str`; literals, scalar/text parameters and returns, immutable local bindings, and optional local type annotations.
- Named functions, forward calls, recursion, `if`/`else`, return-path checking, and discarded expression statements. Local shadowing and duplicate/reserved global declarations are rejected.
- Checked i32 arithmetic, signed division/remainder semantics, comparisons, scalar equality, short-circuit booleans, and source-order calls. There are no text operators or implicit conversions.
- [Static UTF-8 text and optional `print`](../../docs/text-console.md), including static storage after returning a view, embedded NUL, empty text, output status, short writes, and EINTR handling. `--console` is required for C emission using `print`, even in an uncalled function. Checking itself does not grant console access or require a native entry point.
- Hosted emission requires `fn main() -> i32`. C helpers retain the reference's checked arithmetic and POSIX output contract in inspected source files; no Python generation occurs during Cargo builds.

Records, owned/moved records, borrowing, field access, and mutation are explicitly unsupported (`E0801`); there is no fallback to the reference. A named type outside the three supported types also receives `E0801`, so an unknown-type diagnostic is not reference-compatible. Existing vectors/borrowing examples require the reference compiler. Unsupported CLI commands/options fail with status 2.

The arena-based expression representation avoids recursively dropping an unbounded expression tree. Limits are 256 KiB source and 16384 tokens, with conservative parser/tree nesting guards of 128; nesting guard boundaries are not identical to Python's parser/AST limits. These are resource guards, not host CPU/memory quotas. Input uses nonblocking opened-descriptor checks to reject FIFOs/nonregular files; paths use OS strings, and source contents require UTF-8.

## Diagnostics and identity

`check SOURCE --json` returns a `talven.diagnostics.v1` envelope with an additional mandatory `profile: native-scalar-text-v1`. This profile is narrower than the reference language. Diagnostics carry familiar codes, native messages, `source: talven-native`, and zero-based UTF-16 ranges. Selected supported error codes/ranges are tested against the reference; complete wording, error-priority, context-schema, and limit-boundary equivalence are not claimed. Success exits 0, a source/I/O/emission diagnostic exits 1, and usage errors exit 2.

`--version` identifies the experimental CLI/profile. `--build-info` reports the Rust version, target, Cargo profile/optimization level, effective encoded Rust flags, target features/debug setting, present profile environment overrides, and exact compiler source/Cargo input text embedded at build time. The comparison requires those source bytes to match the archived checkout; a stale native executable is rejected. This adds embedded source bytes to the experimental binary size. The metadata and executable hashes are provenance data, not authenticated attestations; system linkers/libraries and complete external Cargo configuration are not bundled.

## Verify and measure

~~~sh
python3 experiments/native-compiler/tests/conformance.py
python3 experiments/native-compiler/tests/comparison.py
python3 scripts/measure-native-prototype.py --native experiments/native-compiler/target/release/talven-native --out build/native-comparison --repetitions 5 --warmups 1
~~~

Set `TALVEN_NATIVE` to a different already-built executable for the tests. The comparison command requires `--native`. Native acceptance needs `cc` with ASan/UBSan; failures are not skipped. The original reference suite still runs separately through `python3 -m unittest discover -s tests -v`.

The conformance suite checks actual greeting bytes, static text lifetimes, ordered console calls, short-circuit traps, independently computed integer results, overflow/division traps, declared unsupported features, limits, input paths, and selected diagnostic parity. Comparison tests check failure retention, immutable run destinations, complete verified sample counts, and that the unchanged chain oracle rejects an implementation which always returns zero.

The separate comparison schema is `talven.native-comparison.v1`. Workloads are the exact greeting and the existing generated `chain-32`/`chain-128` sources and independent C oracles. Vectors and borrowing are excluded explicitly because they are unsupported, not silently counted as passes. Check and emit-C operations start a fresh process each time. The two implementations have different scope and output sizes; this finite overlap is not a whole-language comparison.

Before sampling, both implementations must produce valid checking receipts and C accepted by native execution. The greeting checks exact stdout/empty stderr/exit zero. Chain oracles use separate C translation units, no LTO, and three full-i32 parameter/result comparisons. Repeated emitted bytes must match that implementation's accepted preflight bytes exactly; generated C need not match across implementations.

Order is workload, phase (warmup then measured), repetition, operation (`check`, `emit-c`), implementation. Reference/native order alternates each repetition. No outlier is removed. Each raw command includes actual elapsed nanoseconds, argv, phase, status, output hashes/bytes, and verification state. Summaries contain count/minimum/median/maximum only for complete verified measured groups. The timing boundary is the existing recorder's process launch through output collection and any failure cleanup. Receipt writes and validation are outside that boundary. C compilation and acceptance execute outside the frontend timing.

The output path must be new. The runner archives source and runner inputs, the native compiler binary, build metadata, reference compiler hash, Python/C executable fingerprints, Git revision/dirty state, source/C/oracle files, native acceptance binaries, and exact command stdout/stderr. It rechecks selected input/tool fingerprints before marking success. Expected failures retain an incomplete report with no summary; interruption retains the last saved state. Existing [recorder behavior and trust limits](../../docs/tooling-baseline.md) apply: trusted tool execution, timeouts, no hostile-process sandbox, and no exhaustive resource quota.

Caches, scheduler load, filesystem, thermals, VM/container placement and host libraries are uncontrolled. Preflight has already touched inputs; these are not cold-cache timings. `--environment-note` is operator-supplied, CPU identity can be unavailable, and nanosecond storage does not imply nanosecond accuracy. Rust standard libraries, Python standard libraries, C headers/libraries/subtools and complete inherited environment are not bundled; embedded sources are checked for consistency, but hashes and self-reported metadata do not establish source-to-binary authenticity. Record the build invocation and preserve the original CI/container evidence for comparisons.

No representative speedup, full-build improvement, memory saving, model-token/task-cost reduction, incremental reuse, or M1 completion follows from these samples. [Native comparison evidence](../../docs/native-compiler-evidence.md) records actual runs and remaining gaps. Next work must extend independently verified semantics and design dependency-aware compilation before replacing existing tooling.
