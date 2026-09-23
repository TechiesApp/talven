# Proposal 0013: Native scalar compiler experiment

- Status: Accepted by the project owner on 24 September 2026; bounded experimental implementation
- Author(s): Talven contributors
- Requirements affected: R01, R08, R09, R11, R15, R24; see [requirements](../requirements.md)
- Decisions affected: D37, new D41; see [decisions](../decisions.md)
- Discussion: Native prototype implementation pull request

## Problem

The watch/restart loop now works, but the reference compiler remains Python-based. The project needs direct evidence from a native implementation while retaining established semantics and independent acceptance. Replacing ownership, tooling, backend and deployment together would obscure regressions and make performance attribution unreliable.

## Proposal

Implement a separate dependency-free Rust experiment for the scalar/static-text overlap: functions, immutable locals, conditionals, checked i32 arithmetic, booleans, static strings and optional console output. Compile it to a standalone host executable with `check` and `emit-c` commands, without Python delegation. Keep C11 code generation so frontend implementation is evaluated separately from backend replacement.

Explicitly reject struct declarations (`E0801`), and with them records, moves/borrowing and mutation. Preserve the Python compiler, formatter, context/LSP and watch command. The [native guide](../../experiments/native-compiler/README.md) defines exact scope, command dependencies, resource guards, diagnostics and target limits. The native frontend ports the reference lexer, parser and checker, so record-free programs receive the reference's diagnostic codes, messages and UTF-16 ranges, and accepted programs emit byte-identical hosted C. A shared differential corpus enforces this with an explicit allowlist of divergences: `E0801` for struct programs, host-library `E0901` wording, and a recursion boundary that already varies by one level between CPython versions. A distinct profile prevents claiming full language validation.

Retain raw comparison samples and provenance on three declared overlapping workloads. Measure separate check and C-emission process boundaries, gate emitted outputs through independent native acceptance, and provide no summary for incomplete/failed suites. No production language/backend selection, full-build speed claim, dependency graph, persistent cache or reload support is implied.

## Examples

Implemented interface after compiling the Rust experiment:

~~~sh
experiments/native-compiler/target/release/talven-native check examples/hello.tal --json
experiments/native-compiler/target/release/talven-native emit-c examples/hello.tal --console
~~~

The second command emits C; a separate C11 toolchain builds the final greeting executable. It does not execute source or invoke Python. The borrowing example remains a reference-compiler workload.

## Alternatives considered

- Rewrite the full reference immediately: increases regression surface before any measured native frontend evidence.
- A native launcher wrapping Python: does not evaluate a native frontend and hides the runtime dependency.
- Change to Cranelift simultaneously: introduces a second experimental variable; retain C11 for this slice.
- Lexer-only timing: useful microbenchmark, but insufficient to test a checked source-to-native path.
- Replace the reference on a partial passing corpus: would lose borrowing and shared tooling contracts. Keep explicitly separate until the replacement demonstrates its intended scope.

## Costs and implications

- Agent context: a separate profile/command and evidence guide; no provider token savings inferred.
- Runtime/memory: Rust build toolchain and host compiler executable, with compiler heap allocations; generated program costs retain the reference C11 contract. No managed runtime is added to Talven programs.
- Security: trusted native tooling, standard libraries and C compiler. Source paths and contents are handled separately, nonregular inputs rejected, and source/token/depth guards prevent common accidental resource growth. No sandbox or authenticity claim.
- Targets: Linux aarch64/x86-64 verification first. Host OS input constants and output facilities need explicit portability evidence. No package/ABI/GPU expansion.
- Maintenance: duplicate frontend semantics require differential and independent checks as the language evolves. Rust 1.96.0 and dependency-free Cargo settings bound this experiment, not the final production compiler.

## Evaluation

Require native exact-output/static-lifetime, checked arithmetic/trap, short-circuit/order tests and a shared differential corpus (examples, fixtures, edge cases, seeded generated programs and mutations) that compares both compilers' diagnostics, emitted C and executable behavior, with generated programs also checked against an independent evaluator. Explicitly exercise unsupported syntax and malformed/pathological input. Preserve all existing reference/agent acceptance. Run the same native experiment tests on Linux ARM64/x86-64 CI, with sanitizer-backed emitted-code cases.

Compare standalone checking and C emission on the exact greeting and unchanged generated chain workloads with independent full-integer C oracles. Retain source, compiler binary/embedded source and build settings, host/tool identities, flags, caches/ordering caveats, all raw commands and failure reports. Counts/minimum/median/maximum summarize only verified measured groups. A small sample is evidence about that run, not a representative speedup or production suitability decision.

## Unresolved questions

Native records/borrowing parity, shared formatter/context/LSP interfaces, diagnostic compatibility beyond the differential corpus, native build driver and packaging, persistent dependency queries, incremental codegen/linking, alternative backends, representative performance budgets and memory measurements remain open. Hot reload still requires explicit module/state/lifetime contracts.
