# Native in-process phase evidence

Status: actual local observations on 1 October 2026 using the [phase method](native-phase-baseline.md). The [public extract](../experiments/results/native-phases-macos-arm64-20261001.json) retains all 260 samples, source/oracle text, summaries, correctness receipts and input identities. No model, tokenizer, token or dollar-cost measurement was performed.

## Run identity

- Working tree based on `25213a1`, with exact native and runner input identities retained. It was not a clean checkout of that commit.
- Reference compiler hash `3f1b89fbb98cc4c92679236068f7479d2210cdc8b5331ab7d5a8e25254767ef9`; native `native-call-borrows-v1`, Rust `1.96.0`, target `aarch64-apple-darwin`, release optimization 3, no LTO, 16 codegen units. Effective target features and environment overrides remain in the extract.
- Apple M4, macOS/Darwin kernel `27.0.0`, ARM64; CPython `3.14.7`; Apple Clang `21.0.0`, C target `arm64-apple-darwin27.0.0`. Native acceptance uses C11 `-O2`, warnings/pedantic checks and `-fno-lto`.
- Interval 08:50:20–08:50:24 UTC. Each of five workloads had one ordinary unmeasured preflight, two warmups and 50 measured iterations. All five native acceptance drivers passed; native/reference C was byte-identical.
- Desktop applications were open; no other validation jobs were intentionally running. Scheduler load, allocator/cache state and thermals were uncontrolled. These are local observations, not a controlled comparison with Python or an optimization experiment.

The full run, exact compiler/measurement inputs, executable, generated C, drivers and raw command streams remain under ignored local `build/native-phase-local-20261001/`. Its report SHA-256 is `a2e66fb603a945708fbc7720d6b029e77ff8013b16701fce072689551182181a`. The public extract omits absolute command paths/raw streams and embedded native source text, retaining their input identities. It is derived evidence, not the full report or an authenticated attestation.

## Observed phase latency

Each cell is **median milliseconds from 50 measured iterations**. No outlier was removed. Min/max and every raw nanosecond sample are retained. Parsing includes lexing and depth validation; analysis includes parsing, checking and measurement overhead. Emission is hosted C text generation. Source I/O, process startup, returned program/C destruction, serialization, verification and native C builds are outside these core timers.

| Workload | Source bytes | Parse | Check | Analysis | Emit C |
| --- | --- | --- | --- | --- | --- |
| hello | 58 | 0.002542 | 0.000542 | 0.003167 | 0.007896 |
| chain-32 | 2170 | 0.039395 | 0.015395 | 0.059208 | 0.123583 |
| chain-128 | 8563 | 0.118938 | 0.056167 | 0.175521 | 0.348959 |
| stores-128 | 41327 | 1.149604 | 0.402396 | 1.530917 | 3.167229 |
| borrowing | 185 | 0.010333 | 0.003250 | 0.013791 | 0.020333 |

Median analysis need not equal the sum of separate phase medians: the median can select different iterations in each column. For every individual sample the whole-analysis clock covers its parse/check clocks.

On these inputs emission exceeded analysis; parsing exceeded checking. The store-heavy source generated 243,313 bytes of C. This motivates investigating emitter allocations and frontend parsing costs. It does not establish the cause, a general bottleneck or a representative latency budget. Small greeting/borrowing values are particularly sensitive to clock overhead and cache state.

## Correctness and limits

Three measurement-harness tests reject malformed or stale receipts, partial/unverified groups and output overwrite. Thirteen Rust tests, 15 native conformance tests, the 840-case differential corpus and five native comparison tests passed locally. Borrowing sanitizer execution passed all six `-O0`/`-O2` native cases with ASan/UBSan. The reference suite passed 343 tests with one Linux-only static-text sanitizer test skipped on macOS; CI requires native-host execution and no skips.

The method measures full fresh analysis on fixed initial sources. It does not measure persistent checking, invalid-edit recovery, compiler memory, final native builds, editor responsiveness or save-to-running latency. Standalone process and earlier Python timing boundaries differ, so their medians are not used here to claim a speedup or infer process startup. Backend and production compiler selection remain open.
