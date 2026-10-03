# Native compiler experiment

Status: bounded Rust prototype, `native-call-borrows-v1`. This is an implementation experiment under [Proposal 0013](../../docs/proposals/0013-native-scalar-compiler.md), not a replacement for the full Python reference or a production toolchain selection. It directly parses, checks, and emits C11; it never launches Python, a shell, or another compiler. The lexer, parser, checker and hosted emitter are a hand-written port of `talven/frontend.py` and `talven/backend.py`, kept in step by a shared differential corpus.

The explicit [concrete-outcome companion](../../docs/outcomes.md) selects
`m2-concrete-outcomes-v1` with `--outcomes` on `check`, `fmt` and `emit-c`. Rust
independently parses/checks original outcome source, including exhaustive consuming
matches, scalar/record payload moves and must-handle paths. Exact C/formatter and
diagnostic parity plus independent O0/O2 sanitizer drivers run in
`tests/outcomes.py`. Outcome context/edit/module/watch/C API integration remains
separate; ordinary commands retain their existing grammar and profile.

## Build and run

Build with Rust/Cargo 1.96.0. There are no third-party crates. The checked-in lockfile and explicit release settings describe the experiment; Rust is needed to build the compiler, not to invoke the resulting executable.

~~~sh
cargo +1.96.0 build --release --offline --locked --manifest-path experiments/native-compiler/Cargo.toml
experiments/native-compiler/target/release/talven-native check examples/hello.tal --json
experiments/native-compiler/target/release/talven-native context examples/borrowing.tal --compact
experiments/native-compiler/target/release/talven-native fmt examples/borrowing.tal --check --json
mkdir -p build
experiments/native-compiler/target/release/talven-native emit-c examples/hello.tal --console > build/native-hello.c
cc -std=c11 -O2 -Wall -Wextra -pedantic-errors build/native-hello.c -o build/native-hello
./build/native-hello
~~~

Install the pinned Rust toolchain first if absent. This provides compact and bounded focused context, read-only edit previews and canonical formatting, but not the full reference context API, native `build` driver, formatter file replacement/revision guards, LSP, watch integration, installer, freestanding backend, or incremental compiler. `emit-c` writes to stdout without modifying source. The shell/C compiler steps above remain explicit. Redirect to a separate output path: shell redirection can truncate a source before the compiler starts.

The current hosted experiment targets Linux aarch64 and x86-64, exercised by the repository CI. macOS has an input-opening implementation and local tests, not a complete supported target profile. Other operating systems and other Linux architectures reject source opening rather than guess their `O_NONBLOCK` value. Both the compiler and generated executable may depend on host libraries; neither is a statically linked or single-dependency distribution claim. The compiler uses Rust's heap and standard library; emitted Talven text/arithmetic introduces no new language allocator or managed runtime.

## Declared subset

- `i32`, `bool`, static immutable `str`; literals, scalar/text parameters and returns, local bindings, initialized mutable `i32`/`bool` locals with fixed-type reassignment, and optional local type annotations.
- Named functions, forward calls, recursion, `if`/`else`, return-path checking, and discarded expression statements. Local shadowing and duplicate/reserved global declarations are rejected.
- Affine records: `struct` declarations with `i32`/`bool` fields, record literals (fields in any order, trailing comma), field reads including on call results and literals (`make().x`), and records as by-value parameters, results, local declarations and discarded expression statements. Moves are affine exactly as in the reference: using a record after a possible move is `E0301`, a move in a branch that returns does not affect the other path, and moves on the right of `&&`/`||` count as possible. Record literal, field-type, namespace and equality diagnostics (`E0203`, `E0204`, `E0101`, `E0102`) match the reference.
- Checked i32 arithmetic, signed division/remainder semantics, comparisons, scalar equality, short-circuit booleans, and source-order calls. There are no text operators or implicit conversions.
- [Static UTF-8 text and optional `print`](../../docs/text-console.md), including static storage after returning a view, embedded NUL, empty text, output status, short writes, and EINTR handling. `--console` is required for C emission using `print`, even in an uncalled function. Checking itself does not grant console access or require a native entry point.
- Hosted emission requires `fn main() -> i32`. C helpers retain the reference's checked arithmetic and POSIX output contract in inspected source files (`src/runtime.c`, `src/console.c`); like the reference, only referenced helpers, and the trap only when a helper is emitted, appear in the output. For accepted programs the emitted C is byte-identical to the reference's hosted output. No Python generation occurs during Cargo builds.

The experiment supports the reference's call-scoped shared/exclusive record borrows, mutable owned record fields, explicit reborrowing, and source-order scalar snapshots. Loans begin when their direct call argument is checked, remain live through later arguments, and end after the call; nested calls retain earlier outer loans. `&R` parameters permit reading, `&mut R` parameters permit reading and writing, and a shared parameter cannot be upgraded. References cannot be stored or returned. Temporaries, field-only borrows, scalar borrows, and whole-record/text reassignment remain rejected with the reference diagnostics. See the [borrowing contract](../../docs/borrowing.md). There is no fallback to the reference. `examples/borrowing.tal` now checks and emits natively. Unsupported CLI commands/options fail with status 2.

The arena-based expression representation avoids recursively dropping an unbounded expression tree. Limits are 256 KiB source and 16384 tokens. The reference's 128-level syntax-tree walk is reproduced exactly, including its traversal order, so the reported node for a long `+` chain matches; parentheses add no level. Both parsers also enforce the reference's defined nesting limit: at most 256 active block/expression levels, counting a function body as 1 and each parenthesis as a level, reported as `E0005` at the token where the limit is crossed. The limit no longer depends on the Python interpreter. These are resource guards, not host CPU/memory quotas. Input uses nonblocking opened-descriptor checks to reject FIFOs/nonregular files; paths use OS strings, and source contents require UTF-8.

## Diagnostics and identity

`check SOURCE --json` returns a `talven.diagnostics.v1` envelope with an additional mandatory `profile: native-call-borrows-v1`. This profile identifies an independent implementation of the reference's current bounded language subset; native tooling remains narrower. Diagnostics carry the reference's codes, messages and zero-based UTF-16 ranges, with `source: talven-native`; human-readable errors use the reference's `PATH:LINE:COLUMN: CODE: MESSAGE` form. Parity is tested on the differential corpus below, not proven for all inputs. Known differences: the wording of `E0901` I/O and invalid-UTF-8 errors (host library text), and the number of diagnostics: the native checker stops at the first error, while the reference `check` recovers and reports several, the first of which must match. Full context v2 and LSP are not implemented. Success exits 0, a source/I/O/emission diagnostic exits 1, and usage errors exit 2.

## Compact agent context

`context SOURCE --compact` performs the same complete native analysis as `check`, then emits `talven.agent-context.v2`: `functions` contains every function signature sorted by name, and `records` contains every record sorted by name, with fields in declaration order and a by-value move reminder. Parameters retain their declared names, order, and `&R`/`&mut R` modes. Output matches `python3 -m talven context SOURCE --compact` byte for byte, including JSON key order and the final newline, on the differential corpus. This port is specified in [Proposal 0031](../../docs/proposals/0031-native-compact-agent-context.md).

Checking/context do not require `main`, execute source, or require `--console` for a checked `print` call. Empty source produces empty arrays. Invalid source produces the structured native diagnostic envelope and no program facts, matching the reference context command's automatic JSON error mode. Optional `--json` is accepted for compatibility with the native check command; it does not change context output. The compact mode requires `--compact` explicitly and rejects focused-mode options before reading source.

This whole-program index omits source/compiler hashes, byte budgets, symbol selection, bodies, dependency/caller/effect records, target metadata and revision checks. It is not the full `talven.context.v2` API or a cache receipt. Input retains the same regular-file, UTF-8, source/token/depth limits; output size follows the checked declarations, without a separate output-budget option. The native library exposes `agent_context(&Program)` through checked programs returned by `analyze` or `analyze_measured`. It never invokes the reference compiler or a model provider. The separate [agent-tool CLI baseline](../../docs/native-agent-tools-baseline.md) retains finite process costs; no core context latency, memory, token savings, or production parity claim is made.

`--version` identifies the experimental CLI/profile. `--build-info` reports the Rust version, target, Cargo profile/optimization level, effective encoded Rust flags, target features/debug setting, present profile environment overrides, and exact compiler source/Cargo input text embedded at build time. The comparison requires those source bytes to match the archived checkout; a stale native executable is rejected. This adds embedded source bytes to the experimental binary size. The metadata and executable hashes are provenance data, not authenticated attestations; system linkers/libraries and complete external Cargo configuration are not bundled.

## Focused context

`context SOURCE --symbol NAME` returns a bounded `talven.native-context.v1` response with the selected function, direct callees, used record types, direct caller names, passing/borrow contracts and required console runtime. Omit `--symbol` for all functions/records. Add `--include-body` for exact selected function declarations under `untrusted_source_text`; comments remain data and dependency bodies are omitted. `--max-bytes N` defaults to 16384, accepts 1 through 1 MiB, and counts UTF-8 output including the newline. Oversized results fail with E0502 rather than returning partial facts.

`--expect-source-hash HASH` rejects a stale SHA-256 source revision with E0501 before analysis. Successful output includes that exact buffer's source hash and an embedded native source/build identity, hosted target, native/language profiles and frontend-only validation. The native schema deliberately differs from the reference's full context v2: it has no Python identity, cache key or full rules. Common selected semantic facts and exact body text are checked against the reference across the differential corpus. See [Proposal 0034](../../docs/proposals/0034-native-focused-context.md) for the identity framing and failure ordering.

Focused mode rejects duplicate/malformed flags and unsupported `--freestanding` before source I/O. Optional `--json` does not change output. Checking still covers the whole program; an invalid unrelated function prevents context facts. No execution, writes, caching, atomic freshness, native-build acceptance or measured agent/latency benefit is claimed. The hash identifies the source read by this invocation; edit previews require separate observed-file freshness checks.

## Read-only edit previews

`edit snapshot SOURCE [--include-source] [--max-bytes N]` identifies exact bounded UTF-8 bytes without language analysis, then rereads to reject observed changes. This works for broken programs. The result is `talven.native-edit-snapshot.v1`; optional text is labeled `untrusted_source_text` and omitted on failure. `edit validate SOURCE --candidate FILE --expect-source-hash HASH --expect-compiler-hash HASH [--max-bytes N]` checks those native identities before analyzing a complete candidate and rereading both files. Obtain both hashes from the native snapshot or matching focused context; Python compiler identities are different.

The `talven.native-edit-validation.v1` receipt reports each input's first frontend result and, when both pass, added/removed declarations, changed contracts and changed direct calls. Invalid-base repairs can succeed with null changes. Declaration comparisons retain parameter/field order and borrow permissions; layout/body-only changes can produce empty change arrays. A preview has no source bodies and performs no writes, native compilation or execution. Both commands emit JSON, exit 0 on success, 1 on controlled operation failure, and 2 on malformed/missing/duplicate CLI options.

Budgets default to 16384 and accept 1 byte through 1 MiB, including the UTF-8 newline. E0701 rejects invalid hashes/budgets, E0702 a stale compiler identity, E0501 a stale source/observed file change, and E0703 an oversized completed receipt. Failure receipts are outside the requested success budget. Observed reread errors/changes clear checked facts. Embedded compiler identity stays immutable within the loaded process; a new compiler invocation may have a different identity.

[Proposal 0035](../../docs/proposals/0035-native-edit-previews.md) specifies the native schemas and limits. Neither rereads nor hashes provide locking, atomic compare-and-swap or permission to apply an edit. An applying host must coordinate writers and check current identities. Independent native fixtures accept a correct borrow repair and reject a frontend-valid off-by-one repair at O0/O2. Native LSP integration, atomic application, caching and measured task-cost benefits remain open.

## Hosted scalar C API units

`emit-c-api SOURCE --module NAME --export FUNCTION [--export FUNCTION ...] [--console] [--max-bytes N]` freshly checks source and returns a `talven.c-api.v1` library/header receipt. It does not require `main` or run a C compiler. Selected public signatures allow only i32/bool parameters/results. Length-framed module names namespace public wrappers and compiler-private function/record tokens so independently compiled units can reuse private names. Default executable emission stays unchanged.

Exact decoded C/header bytes, hashes and interface facts match the reference across eligible differential cases; native compiler identity remains distinct. The [C export guide](../../docs/c-api.md) uses two checked units and a libc `strtol` C caller. Standalone fixtures execute native/reference outputs under ASan/UBSan at O0/O2 and retain overflow traps. [Proposal 0036](../../docs/proposals/0036-hosted-scalar-c-api.md) defines budgets, failure ordering and scope. This does not provide Talven imports, foreign pointers/records/text exports, stable binary packages or measured bridge overhead. Generation performs no writes or program execution.

The separate reference [local-module profile](../../docs/modules.md) resolves bounded explicit imports through the shared checker. `tests/project.py` compares this resolved core source against native C emission and independently executes both outputs with sanitizers. The Rust CLI does not load module graphs or accept raw module syntax; this boundary test does not claim native resolution parity.

## Canonical formatting

`fmt SOURCE` prints the reference's `m1-scalar-mutation-layout-v1` layout without writing source. `fmt SOURCE --check` returns 0 with `Formatting check passed` when source already matches, or 1 with E0601 when layout differs. Add `--check --json` for the existing native diagnostic envelope on success/failure. `--json` requires `--check`; duplicate flags, `--write`, revision-hash flags and other unsupported options return usage status 2 before reading source. See [Proposal 0032](../../docs/proposals/0032-native-canonical-formatting.md).

The library `format_source(&str)` uses the shared native lexer and parser, without semantic checking or emission. It formats syntactically valid programs while types, moves or return paths are being repaired. Empty/whitespace-only input becomes empty output. Four-space indentation, LF endings, declaration separation, expression spacing and original trailing-comment attachment match the [reference layout](../../docs/formatting.md). Parentheses, leading zeros, quoted literals, field/argument order and trailing commas retain their spelling/order. Comments remain inert data; no configuration, directives or external tools are loaded.

Formatting counts comments toward the 16384-token bound and enforces the shared source/parser-depth limits. Expanded output is bounded to 256 KiB, including indentation and newlines; overflow is E0602 and returns no partial formatted text. Before returning, the formatter re-lexes the whole output and verifies token/comment identity, reporting E0604 on a mismatch. The E0601 message names the native preview command rather than recommending the reference's unsupported native `--write` option. Input I/O messages retain the documented host-specific differences.

This port does not apply edits, implement revision checks, atomic replacement, LSP formatting or tokenizer-specific budgets. Check mode verifies layout only. Output bytes match the reference on the differential corpus and comment/whitespace fixtures; the separate [agent-tool CLI baseline](../../docs/native-agent-tools-baseline.md) measures finite process costs, without a general-equivalence, core formatter speed, memory or agent-cost claim. The new `src/format.rs` is embedded in build identity and independently checked for stale-source rejection.

## Verify and measure

~~~sh
cargo +1.96.0 clippy --locked --offline --all-targets --manifest-path experiments/native-compiler/Cargo.toml -- -D warnings
cargo +1.96.0 test --locked --offline --manifest-path experiments/native-compiler/Cargo.toml
python3 experiments/native-compiler/tests/conformance.py
python3 experiments/native-compiler/tests/formatting.py
python3 experiments/native-compiler/tests/context.py
python3 experiments/native-compiler/tests/edit.py
python3 experiments/native-compiler/tests/c_api.py
python3 experiments/native-compiler/tests/project.py
python3 experiments/native-compiler/tests/differential.py
python3 experiments/native-compiler/tests/comparison.py
python3 scripts/check-borrow-sanitizers.py --native experiments/native-compiler/target/release/talven-native
python3 scripts/measure-native-prototype.py --native experiments/native-compiler/target/release/talven-native --out build/native-comparison --repetitions 5 --warmups 1
python3 scripts/measure-native-prototype.py --native experiments/native-compiler/target/release/talven-native --out build/native-agent-tools --repetitions 5 --warmups 1 --agent-tools
python3 scripts/measure-native-inprocess.py --native experiments/native-compiler/target/release/talven-native --out build/native-phase-baseline --repetitions 20 --warmups 2
~~~

Set `TALVEN_NATIVE` to a different already-built executable for the tests. The comparison command requires `--native`. Native acceptance needs `cc` with ASan/UBSan; failures are not skipped. The original reference suite still runs separately through `python3 -m unittest discover -s tests -v`.

The differential suite (`tests/differential.py`) runs both CLIs on every example, invalid example, test fixture and corpus source, hand-written lexer/parser/checker/limit/record/mutation edge cases, 160 seeded random well-typed programs, 64 seeded scalar-mutation programs, 64 seeded borrowing/mutation programs, and 260 seeded token mutations. It compares ok/failure and the first diagnostic's code, message, severity and range; requires byte-identical canonical formatting, compact context and `emit-c` output (with and without `--console`) or identical failures; and compiles and runs both C outputs with `-Werror`, comparing exit status and stdout with each other and, for generated programs, with an independent Python evaluator. The evaluator models scalar stores, record updates, borrowed aliases, and branch updates separately from C emission. The only allowlisted difference is `E0901` message text for invalid UTF-8; any semantic, formatting, context or emitted-code difference fails. Both compilers must agree on accepted and rejected borrowing programs.

The formatting suite additionally inserts a Unicode comment at every token boundary of a borrowing/scalar-mutation program and varies whitespace with a fixed seed, requiring reference bytes, idempotence, token identity, unchanged checked native lowering and successful check mode. Independent exact-layout fixtures, semantic-error repairs, UTF-8/comment/output limits, unsupported flags and nonregular files verify the read-only boundary. The declared native CI jobs run these tests alongside existing conformance.

The conformance suite checks actual greeting bytes, static text lifetimes, ordered console calls, by-value record results and initializer order, short-circuit traps, independently computed integer results, overflow/division traps, loan conflicts, mutation permissions, reference escape rejection, limits, input paths, and selected diagnostic parity. The sanitizer script additionally compares native emitted C to the reference and executes all three borrowing fixtures at `-O0`/`-O2` with ASan/UBSan; CI requires this on both declared native hosts. Comparison tests check failure retention, immutable run destinations, complete verified sample counts, and that the unchanged chain oracle rejects an implementation which always returns zero.

The separate comparison schema is `talven.native-comparison.v1`. Workloads are the exact greeting and the existing generated `chain-32`/`chain-128` sources and independent C oracles. The measurement workloads remain greeting/scalar chains and exclude records and borrowing; extended conformance does not broaden the recorded timing workload. Check and emit-C operations start a fresh process each time. The two implementations have different scope and output sizes; this finite overlap is not a whole-language comparison.

Before sampling, both implementations must produce valid checking receipts and C accepted by native execution. The greeting checks exact stdout/empty stderr/exit zero. Chain oracles use separate C translation units, no LTO, and three full-i32 parameter/result comparisons. Repeated emitted bytes must match that implementation's accepted preflight bytes exactly; generated C need not match across implementations.

Order is workload, phase (warmup then measured), repetition, operation (`check`, `emit-c`), implementation. Reference/native order alternates each repetition. No outlier is removed. Each raw command includes actual elapsed nanoseconds, argv, phase, status, output hashes/bytes, and verification state. Summaries contain count/minimum/median/maximum only for complete verified measured groups. The timing boundary is the existing recorder's process launch through output collection and any failure cleanup. Receipt writes and validation are outside that boundary. C compilation and acceptance execute outside the frontend timing.

The output path must be new. The runner archives source and runner inputs, the native compiler binary, build metadata, reference compiler hash, Python/C executable fingerprints, Git revision/dirty state, source/C/oracle files, native acceptance binaries, and exact command stdout/stderr. It rechecks selected input/tool fingerprints before marking success. Expected failures retain an incomplete report with no summary; interruption retains the last saved state. Existing [recorder behavior and trust limits](../../docs/tooling-baseline.md) apply: trusted tool execution, timeouts, no hostile-process sandbox, and no exhaustive resource quota.

Caches, scheduler load, filesystem, thermals, VM/container placement and host libraries are uncontrolled. Preflight has already touched inputs; these are not cold-cache timings. `--environment-note` is operator-supplied, CPU identity can be unavailable, and nanosecond storage does not imply nanosecond accuracy. Rust standard libraries, Python standard libraries, C headers/libraries/subtools and complete inherited environment are not bundled; embedded sources are checked for consistency, but hashes and self-reported metadata do not establish source-to-binary authenticity. Record the build invocation and preserve the original CI/container evidence for comparisons.

No representative speedup, full-build improvement, memory saving, model-token/task-cost reduction, incremental reuse, or M1 completion follows from these samples. [Native comparison evidence](../../docs/native-compiler-evidence.md) records actual runs and remaining gaps. Next work must extend independently verified semantics and design dependency-aware compilation before replacing existing tooling.

The separate [in-process phase method](../../docs/native-phase-baseline.md) measures parsing, checking, total instrumented analysis and C emission inside the native executable. It adds fixed scalar-store and borrowing workloads to greeting/chains, requires byte-identical reference C and independent native acceptance, and retains every phase sample. `measure SOURCE --iterations 20 --warmups 2` reads once, performs one ordinary unmeasured preflight, and emits a bounded JSON receipt; it does not execute source. Source I/O, process startup, returned program/C destruction, receipt output and C builds are outside its core timers. Ordinary `check`/`emit-c` do not read clocks. These inner durations have a different boundary from the standalone comparison above.

The emitter now appends body lines to one growable buffer and assembles the prefix afterward, preserving exact reference bytes while removing per-line indentation/completed-line allocations and the line-vector join. Formatted lines write directly into the buffer rather than allocating an intermediate line string; expression value strings remain owned. [Paired local observations](../../docs/native-emitter-evidence.md) retain actual timings and variability for both increments; memory and full-build gains remain unmeasured.
