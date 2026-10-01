# Native emitter buffer evidence

Status: implemented allocation reduction with local paired observations on 1 October 2026. The native emitter now appends indented body lines to one growable string, then assembles header/console/selected helpers and body into a buffer with exact final capacity. It removes the per-line indentation and completed-line allocations, line-vector splice and final join. Expression formatting still allocates temporary strings; allocation counts and peak memory were not measured.

Generated C bytes, helper order, short-circuit lowering, temporary numbering and source-order borrow/mutation behavior retain the reference contract. The [phase method](native-phase-baseline.md) measures the same parse/check/emission boundaries. No new language or target profile is introduced.

## Paired run identity

The [public comparison extract](../experiments/results/native-emitter-macos-arm64-20261001.json) retains every phase sample, six verified reports, summaries, source/C identities, native build settings and input fingerprints. The working tree was based on `beb2b94`, not a clean checkout. Baseline source/binary bytes came from the earlier [phase run](native-phase-evidence.md), replayed in a separate input tree. Both conditions used the updated measurement runner and complete workload dependencies. Their 31 archived input identities differ only at `experiments/native-compiler/src/lib.rs`.

Three pairs ran in AB, BA, AB order (A: original line vector; B: body buffer). Each condition ran all five workloads, in fixed workload order, with one ordinary preflight, two warmups and 20 measured iterations per workload. Each whole suite used new native processes. This retains 660 phase samples, of which 600 are measured. All 30 independent native acceptance executions passed; corresponding sources and generated C hashes were identical across all six reports.

The host was Apple M4, macOS/Darwin `27.0.0`, ARM64, CPython `3.14.7`, Rust `1.96.0` release optimization 3/no LTO/16 codegen units, native target `aarch64-apple-darwin`. C acceptance used Apple Clang `21.0.0`, C11 `-O2` and `-fno-lto`; executable identities and effective settings are retained. The reference compiler hash was `3f1b89fbb98cc4c92679236068f7479d2210cdc8b5331ab7d5a8e25254767ef9`. No model/tokenizer or agent-cost run was performed.

Interval: 09:01:19–09:01:28 UTC. Desktop apps were open, with no other validation jobs intentionally running; load, caches and thermals remained uncontrolled. Full receipts, command streams, both input trees and independent acceptance artifacts remain under ignored local `build/native-buffer-paired/` and `build/native-buffer-baseline-inputs/`. The full comparison SHA-256 is `113d1e85ad1734852aec88b4149f6b019053cf88034766d12eae625010568be9`. The public extract removes absolute command paths/raw streams and embedded native source text, retaining input identities. It is derived evidence, not an authenticated attestation.

## Observed emission medians

Cells list **milliseconds for pair 1, pair 2, pair 3**, each median over 20 measured iterations. Every min/max and raw nanosecond value remains in the extract. No outlier was removed. Parsing/checking values are retained separately and were not the optimization target.

| Workload | Original line vector | Body buffer |
| --- | --- | --- |
| hello | 0.007146, 0.004646, 0.004709 | 0.003563, 0.003354, 0.003125 |
| chain-32 | 0.081479, 0.089521, 0.081812 | 0.063042, 0.082604, 0.060854 |
| chain-128 | 0.294500, 0.295187, 0.414687 | 0.246438, 0.286979, 0.235708 |
| stores-128 | 1.643458, 1.568646, 1.768355 | 1.130646, 1.181062, 1.287583 |
| borrowing | 0.023729, 0.009937, 0.010292 | 0.007437, 0.015166, 0.006916 |

The store-heavy input emitted 243,313 bytes of identical C. Its buffer medians were lower in all three pairs; chain medians were also lower. One borrowing pair was slower with the buffer. These few observations support keeping the structurally simpler buffering change while showing that small timings are noisy. They do not establish a general speedup, calibrated clock precision, memory saving, full-build improvement or editor latency budget. Earlier standalone and phase observations occurred under different scheduling/cache conditions and are not pooled with these paired runs.

## Correctness and retained-input repair

Local validation passed 13 Rust tests, 15 native conformance tests, all 840 differential cases, five native comparison tests and six native ASan/UBSan borrow executions at `-O0`/`-O2`. The reference suite passed 343 tests with one Linux-only test skipped locally; Linux CI enforces zero skips. Rust formatting and Clippy passed.

Archive replay also revealed that the shared workload factory reads unselected example inputs. The runner now retains all top-level example sources and the experiments package initializer, so replay resolves the archived package and workload source without the original checkout. A focused regression executes the archived workload factory in an isolated Python subprocess, in addition to existing malformed/partial receipt and no-overwrite tests. The original phase observation's selected sources/results remain unchanged; its archive predates this retention repair.

## Direct line formatting follow-up

The native emitter subsequently writes `format_args!` directly into the body buffer through `std::fmt::Write`, removing the temporary input string used for each formatted line. Expression/temporary names and C value strings remain owned because later lowering steps use them. Output order and bytes retain the same contract; no allocation counter or peak-memory observation was collected.

A second [public comparison extract](../experiments/results/native-direct-formatting-macos-arm64-20261001.json) records three AB/BA/AB pairs (A: body buffer with preformatted lines; B: direct line formatting). Each suite again uses all five workloads, one ordinary preflight, two warmups and 20 measured iterations per workload. All 30 native acceptance executions passed, with identical sources and generated C identities. All 32 input identities match between conditions except the native library source. The same method, C/Rust flags and hardware apply; baseline native inputs/binary were frozen from the preceding body-buffer experiment and the shared reference inputs updated identically for both conditions.

The working tree was based on `06ef745`; reference compiler hash was `8feabf1f63fc043ae3712ff0b8fe0da36f307855d1e66bda3f97a5f4940e26b1`, including the new signature-help module. Interval: 09:18:57–09:19:09 UTC. Desktop apps were open, with no validation jobs intentionally running; scheduler/cache/thermal conditions remained uncontrolled. Raw receipts and both frozen input versions remain under ignored `build/native-format-paired/` and `build/native-format-baseline-inputs/`. The full comparison SHA-256 is `88de989565b83eb364eaeae0cdc679baec5968d765e24461b94c07648489cbda`. The extract retains all 660 phase samples and source/build identities, omitting absolute command paths/raw streams and embedded native source text. No model/tokenizer or cost measurement was performed.

Cells are **emission median milliseconds for pair 1, pair 2, pair 3**, each based on 20 measured iterations; no outlier was removed.

| Workload | Body buffer / preformatted lines | Direct line formatting |
| --- | --- | --- |
| hello | 0.003083, 0.003396, 0.003396 | 0.002521, 0.002646, 0.003167 |
| chain-32 | 0.064895, 0.118875, 0.063562 | 0.047292, 0.054395, 0.046000 |
| chain-128 | 0.255895, 0.228396, 0.351083 | 0.168499, 0.176271, 0.169020 |
| stores-128 | 1.402459, 1.206750, 1.365895 | 1.620270, 0.792230, 0.826417 |
| borrowing | 0.007188, 0.006875, 0.007292 | 0.006271, 0.015605, 0.005812 |

Both chain workloads had lower direct-formatting medians in all pairs. The first store-heavy pair and second borrowing pair were slower with direct formatting. This preserves evidence of variability rather than averaging it into an unconditional speedup. Keeping the change removes a clear formatting allocation step, but this small run does not establish a general performance guarantee, memory gain or full-build/editor improvement. Earlier runs are not pooled with this comparison.

Rust formatting/Clippy and 13 tests, 15 native conformance tests, all 840 differential cases, five comparison tests and six native ASan/UBSan borrow executions passed locally. The full reference suite passed 351 tests with one Linux-only static-text sanitizer case skipped on this macOS host. Required Linux CI remains the native-host gate.
