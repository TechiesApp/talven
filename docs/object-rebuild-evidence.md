# Local private-object rebuild evidence

This is one local correctness-gated run of the [rebuild comparison method](object-rebuild-baseline.md), not a production speed claim. [Retained evidence](../experiments/results/unit-rebuilds-macos-arm64-20261001.json) includes all 192 raw samples: four workloads × six revisions × two build conditions × (one warmup + three measured repetitions). Every current successful build passed native acceptance; expected invalid edits matched full diagnostics and repairs used the last successful cache.

The run used Apple M4, macOS ARM64, CPython 3.14.7 and Apple Clang 21.0.0 (`clang-2100.3.34.2`), target `arm64-apple-darwin27.0.0`. Both conditions used strict C11/O2/warnings/no-LTO flags. It ran from 2026-10-01 14:20:49 through 14:23:05 UTC with a trusted stable local toolchain and warm/uncontrolled host caches. No other local agent test, documentation or measurement job ran concurrently; ordinary background applications were uncontrolled. This is not an isolated-machine experiment. Compiler byte identity was `01895a9de53c4dc34dc4de920816695c9462559fc47ad20a20728c7119b684e5`; base commit was `3f179e8ea385145c9e8b90532ddb548f9e50f0e6` plus the archived measurement runner. An earlier correctness-valid timing run overlapped local tests and was repeated before selecting this retained evidence. No model/provider/tokenizer participated.

Median milliseconds from three measured repetitions:

| Workload | Revision | Whole C build | Private units | Units compiled / reused |
| --- | --- | ---: | ---: | --- |
| chain-32 | initial | 75.702 | 1246.810 | 34 / 0 |
| chain-32 | body | 78.844 | 161.240 | 2 / 32 |
| chain-128 | initial | 115.180 | 4101.546 | 130 / 0 |
| chain-128 | body | 114.272 | 200.131 | 2 / 128 |
| stores-128 | initial | 265.683 | 4234.921 | 130 / 0 |
| stores-128 | comment | 323.837 | 206.078 | 0 / 130 |
| stores-128 | body | 298.856 | 266.985 | 2 / 128 |
| stores-128 | contract | 358.013 | 4439.998 | 130 / 0 |
| stores-128 | repair | 331.521 | 223.212 | 0 / 130 |
| borrowing | initial | 89.987 | 452.598 | 4 / 0 |
| borrowing | body | 73.367 | 175.542 | 2 / 2 |
| borrowing | repair | 76.008 | 128.346 | 0 / 4 |

The complete evidence contains all comment, contract/schema, invalid and repair timings too. Invalid timings measure rejection, not native builds. Whole builds do one compiler invocation; private units include fresh driver probes/preprocessing, byte checks/copies, separate object compilation and linking. These are actual end-to-end prototype boundaries, not identical command counts. Contract/schema edits conservatively rebuild every unit; body edits rebuild the changed helper and the main acceptance check. Repaired revisions retain all objects from the preceding successful contract/schema build.

This run supports mixed behavior: store-heavy comment/body/repair medians were lower with reuse, while chain and small borrowing edits were higher; initial and global-contract builds were much higher for units. It does not establish a consistent speedup. Per-function compiler commands and repeated preparation merit investigation, without attributing a measured percentage to any phase before phase evidence exists. Do not enable the API as the default build/watch path on this evidence.

The public JSON removes local artifact paths, command arguments and working-tree status. It retains exact sources/oracles, all input archive hashes, raw durations/order, configuration and native identities, summaries and work receipts. Repeated object lists are losslessly interned by compact sorted-JSON hash; each unit sample references its full list in `object_sets`. The complete original report identity and local archive remain available under `build/unit-rebuild-local-clean-20261001/`. SHA-256 values identify bytes, not authenticated toolchain or acceptance evidence. Memory, cold caches, watcher latency/cancellation, process readiness/state, native Rust reuse and agent cost remain unmeasured.
