# Function-body syntax reuse observations

Status: correctness-gated local comparison for explicit [body syntax reuse](body-syntax.md), Proposed D56. Exact body reuse removes selected parsing work and lowers some warm-edit medians, but cache creation and several invalid/schema cases cost more. Full controls vary and often cost less. No consistent overall speedup, memory reduction or default change is established.

## Inputs and acceptance

The [retained receipt](../experiments/results/body-syntax-macos-arm64-20261002.json) contains three same-checkout full-body-parse/reused-body pairs, ordered parse/bodies, bodies/parse, parse/bodies. Both persistent conditions select current call type contracts; only `--reuse-body-syntax` differs. Every report also includes full-check controls. Five measured repetitions and two warmups over four workloads/six edits/two modes yield 2,016 verified samples: 1,440 measured, 576 warmup. Each table cell aggregates fifteen measured samples. Expected invalid attempts verify current rejection, not native acceptance.

Measurements ran from 2026-10-01T19:38:47.984467+00:00 to 2026-10-01T19:40:04.779594+00:00 UTC (2 October local time), on Apple M4, macOS 27.0.0, ARM64, CPython 3.14.7, Apple Clang targeting `arm64-apple-darwin27.0.0`. The compiler hash is `585a62e80d2380c4932bc82aeccf4f0a7d588d6dc32f73eea0d12adaf60333dc`; source base is `1243c56` plus archived syntax-reuse/compiler/runner edits. Both conditions share exact compiler/source inputs, working directory/environment hashes and GC settings. The invoking Python hash seed is 0. Source/driver/Python identities, clock details, native flags and complete work lists are retained. Warm caches and background host load are uncontrolled; there are no model/provider calls or tokenizer/cost measurements.

Before timing, independently native-verify every valid workload revision against full-i32 and borrow-owner oracles, using ordinary C11/O2/warnings/no-LTO lowering. Every timed/warmup attempt requires complete current analysis/first-diagnostic equality, deterministic context and byte-identical C against ordinary parsing/checking. Current headers, spans, body types, owner mutations, schema changes and invalid/repair must match. Recheck all archived inputs and selected executables before completion. The semantic reuse decisions match across paired conditions; parser work differs explicitly.

Public data retains every duration, all full controls, parser/semantic work, exact source/oracle text and command outcome/output identities. Identical work lists are interned losslessly in `parse_sets`/`reuse_sets`. Private command arguments/log paths and checkout status are omitted; embedded orchestration/curation scripts document the transformation. Raw reports/source archives remain under `build/body-syntax-paired-20261002`. Public JSON SHA-256: `4573b9495421cdb3fc63bc3c2bd10b030eeb9540ada2b7dc2adc531527542a80`.

## Timings

Medians in milliseconds over fifteen verified measured samples per cell. Full controls are unchanged ordinary analysis; persistent columns use common call type contracts with full body parsing or selected grammar reuse. Timed work includes complete current lexing, fresh declarations, selected parsing/reconstruction, current AST depth checking, semantic work, compiler identity hashing and successful cache creation. Initial includes session construction. Verification/context/C/native oracles, JSON recording and final cleanup are outside timing. This is not actual watcher/native-build latency.

| Workload | Revision | Full parse control | Full bodies control | Persistent parse | Persistent bodies |
| --- | --- | ---: | ---: | ---: | ---: |
| chain-32 | initial | 1.068 | 0.976 | 2.210 | 2.363 |
| chain-32 | trivia | 1.097 | 1.081 | 1.713 | 1.569 |
| chain-32 | body | 1.059 | 1.070 | 1.746 | 1.568 |
| chain-32 | contract | 0.989 | 1.048 | 1.574 | 1.468 |
| chain-32 | invalid | 0.919 | 0.937 | 1.412 | 1.460 |
| chain-32 | repair | 0.952 | 1.003 | 1.474 | 1.530 |
| chain-128 | initial | 4.515 | 4.140 | 6.159 | 7.824 |
| chain-128 | trivia | 4.214 | 4.537 | 5.865 | 5.294 |
| chain-128 | body | 4.265 | 4.014 | 5.295 | 5.082 |
| chain-128 | contract | 4.281 | 4.229 | 5.186 | 4.706 |
| chain-128 | invalid | 3.951 | 3.639 | 4.219 | 4.428 |
| chain-128 | repair | 3.862 | 3.622 | 4.858 | 4.828 |
| stores-128 | initial | 36.654 | 35.410 | 39.883 | 58.991 |
| stores-128 | trivia | 53.758 | 38.114 | 40.385 | 37.474 |
| stores-128 | body | 32.778 | 35.467 | 34.501 | 34.226 |
| stores-128 | contract | 84.018 | 38.771 | 49.305 | 32.533 |
| stores-128 | invalid | 29.132 | 33.087 | 29.553 | 40.290 |
| stores-128 | repair | 44.530 | 37.779 | 37.030 | 31.389 |
| borrowing | initial | 0.159 | 0.163 | 1.104 | 1.043 |
| borrowing | trivia | 0.160 | 0.175 | 0.691 | 0.606 |
| borrowing | body | 0.156 | 0.164 | 0.681 | 0.658 |
| borrowing | schema | 0.173 | 0.174 | 0.657 | 0.777 |
| borrowing | invalid | 0.175 | 0.191 | 0.783 | 0.649 |
| borrowing | repair | 0.160 | 0.170 | 0.678 | 0.647 |

In every paired condition, initial syntax-reuse analysis parses all bodies and creates immutable grammar facts. Trivia/repair can reconstruct all unchanged bodies; changed helper/main bodies parse normally. Parameter-rename revisions parse the changed `step_0` body while reconstructing callers. Borrowing schema changes reconstruct `read`/`bump` grammar, parse the changed main body, and still recheck all three functions semantically. Grammar reuse is not type-check acceptance.

The selected mode pays cache construction/reconstruction costs. Store-heavy initial analysis is substantially higher with body facts; some invalid/schema timings are also higher. Several warm-edit medians are lower, but unchanged full controls vary materially. The repetitions belong to three warm local run pairs, not independent host trials or confidence bounds. Counts alone cannot establish a latency benefit. Keep explicit selection and retain all conditions.

Unmeasured: retained/peak memory, incremental tokenization, CLI startup, Rust/native object reuse, actual save-to-running latency, readiness/state preservation, agent cost/success, OS-cold behavior and other hosts/toolchains. Linux CI separately repeats current analysis/context/C and native acceptance; local observations add no supported target. Earlier [call type comparisons](call-contracts-evidence.md) and [native declaration comparisons](local-contracts-evidence.md) have different source identities/boundaries and remain separate evidence.
