# Current call type contract observations

Status: correctness-gated local comparison of default persistent signatures and explicit [call type contracts](call-type-contracts.md), Proposed D55. Parameter renames recheck one definition instead of its definition and direct caller. Timings remain mixed and full checking often costs less, particularly on small inputs. No default change or consistent speedup is established.

## Reproduction and acceptance

The [retained receipt](../experiments/results/call-contracts-macos-arm64-20261002.json) contains three same-checkout named/types pairs ordered named/types, types/named, named/types. Each condition includes a full-check control. Each report retains five measured repetitions and two warmups over four workloads and six edit revisions in both full/persistent modes. All 2,016 samples verified: 1,440 measured and 576 warmup; each table cell aggregates fifteen measured samples. Invalid-edit samples verify current rejections, not native acceptance.

Measurements ran from 2026-10-01T19:06:53.569778+00:00 to 2026-10-01T19:08:19.308083+00:00 UTC (2 October local time), on Apple M4, macOS 27.0.0, ARM64, CPython 3.14.7, Apple Clang targeting `arm64-apple-darwin27.0.0`. The compiler hash is `b500dcf0594f057ac8885c190318872e5811ec610ca70d159a26ea31b7e98c24`; source base is `7f23aa1` plus archived call-contract/compiler/runner edits. Both conditions use identical compiler/source bytes, actual working directory, effective inherited environment and GC configuration. The initial Python hash seed is 0; fixed environment selections/hashes, native verification flags and clock details are retained. Only the selected call-contract option differs; warm caches/background load remain uncontrolled. No model/provider calls or tokenizer/cost measurements occurred.

Every valid workload revision is checked with independent native integer/borrow-owner oracles before timing, under C11/O2/warnings/no-LTO. Each measured/warmup attempt then requires complete current analysis equality, exact first diagnostic equality, deterministic context and byte-identical ordinary C against fresh checking. Record schema, borrow-mode and invalid/repair behavior remain current. The paired orchestrator verifies archived inputs, driver/Python identities, sources/oracles and sample selections before publishing completion.

Public data retains every duration, full controls, check/reuse work, exact source/oracle text, command outcome/output hashes and input identities. Identical immutable work lists are interned losslessly in `reuse_sets`; private command arguments/log paths and checkout status are removed. Embedded orchestration/curation scripts document the transformation. Raw reports/source archives remain in `build/call-contracts-paired-20261002`. The public JSON SHA-256 is `7b71473ddb740e04e49845c4899320933f8ef4c9346af3b5bb174394314d091f`.

## Timings

Medians in milliseconds across fifteen verified measured samples per cell. Columns group the full control and persistent condition for each option. Timed work is in-process analysis, including fresh parsing/declarations and persistent compiler-identity hashing; initial persistent samples include session construction. Context/emission verification, C builds/native oracles, JSON recording and final cleanup are outside timing. This is neither watcher latency nor native object reuse.

| Workload | Revision | Full named | Full types | Persistent named | Persistent types |
| --- | --- | ---: | ---: | ---: | ---: |
| chain-32 | initial | 1.091 | 1.139 | 2.131 | 2.108 |
| chain-32 | trivia | 1.062 | 1.104 | 1.579 | 1.587 |
| chain-32 | body | 1.102 | 1.088 | 1.516 | 1.577 |
| chain-32 | contract | 1.068 | 1.043 | 1.597 | 1.570 |
| chain-32 | invalid | 0.979 | 0.965 | 1.330 | 1.399 |
| chain-32 | repair | 1.025 | 0.976 | 1.547 | 1.494 |
| chain-128 | initial | 4.542 | 4.694 | 5.727 | 6.183 |
| chain-128 | trivia | 4.344 | 4.501 | 6.549 | 6.056 |
| chain-128 | body | 4.769 | 4.367 | 5.835 | 5.047 |
| chain-128 | contract | 5.398 | 4.585 | 5.133 | 5.098 |
| chain-128 | invalid | 4.034 | 3.970 | 4.722 | 4.390 |
| chain-128 | repair | 3.885 | 3.959 | 5.713 | 4.753 |
| stores-128 | initial | 41.802 | 42.794 | 44.532 | 38.129 |
| stores-128 | trivia | 45.912 | 47.513 | 46.778 | 40.891 |
| stores-128 | body | 37.439 | 32.167 | 41.320 | 41.194 |
| stores-128 | contract | 97.394 | 87.417 | 44.868 | 38.242 |
| stores-128 | invalid | 36.444 | 32.697 | 35.413 | 31.855 |
| stores-128 | repair | 35.009 | 38.773 | 33.853 | 37.935 |
| borrowing | initial | 0.189 | 0.173 | 1.211 | 1.105 |
| borrowing | trivia | 0.198 | 0.183 | 0.712 | 0.656 |
| borrowing | body | 0.188 | 0.174 | 0.765 | 0.699 |
| borrowing | schema | 0.207 | 0.184 | 0.763 | 0.712 |
| borrowing | invalid | 0.213 | 0.195 | 0.770 | 0.669 |
| borrowing | repair | 0.197 | 0.182 | 0.748 | 0.676 |

All chain/store parameter-rename samples use the expected check decisions: named mode checks `step_0` and `step_1`; type mode checks only `step_0`. Current caller descriptions are reconstructed from fresh declarations in type mode. Schema changes still check `read`, `bump` and `main` in both modes, and invalid edits preserve the last-successful cache through repair.

Reduced checking work does not establish consistent latency gains. Several type-mode medians are higher, the unchanged full-control timings vary, and the persistent compiler-identity check plus reference reconstruction remain costs. Each five-repetition group belongs to one session/run on a warm host; these are not independent host trials or statistical confidence bounds. Keep explicit selection and report all conditions.

Unmeasured: memory, incremental parsing, CLI startup, native builds/Rust reuse, actual save-to-running latency, readiness/state preservation, agent task cost/success, OS-cold behavior and other hosts/toolchains. Linux CI separately verifies current analysis/context/C and untimed native acceptance. Earlier [persistent checking observations](incremental-checking-evidence.md) and [native declaration observations](local-contracts-evidence.md) use different source identities and boundaries and remain separate evidence.
