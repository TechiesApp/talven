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
