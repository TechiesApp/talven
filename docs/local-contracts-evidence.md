# Local function contract observations

Status: correctness-gated local observations for the explicit [local function contract profile](local-function-contracts.md), Proposed D54. Parameter renames avoided global object invalidation and reduced their native rebuild/watch timings in all three paired runs. Other edits and cold builds were mixed. This does not establish a consistently faster compiler or a better default.

## Inputs and acceptance

The [retained receipt](../experiments/results/local-contracts-macos-arm64-20261002.json) contains twelve reports: three global/local pairs each for actual-object rebuilds and actual CLI watcher edits, ordered global/local, local/global, global/local. There are 576 verified measured samples, no warmups: 288 per experiment, three samples per workload/revision/mode/condition. Ordinary full-build controls run in each report. No model/provider calls occurred; model/tokenizer/task-dollar measurements are absent.

Measurements ran from 2026-10-01T18:43:43.443863+00:00 to 2026-10-01T18:50:36.943450+00:00 UTC (2 October local time), on Apple M4, macOS 27.0.0, ARM64, CPython 3.14.7. The recorded Apple Clang driver targets `arm64-apple-darwin27.0.0`. Strict hosted C11/O2/warnings/no-LTO settings, compiler executable/version/hash, effective environment identities, timing clocks and all source archive hashes are retained. The compiler hash is `b87c9db666c090390abf7d6d6a10afd878f7a368212635c80b2d65a04893af15`; source base is `987e837` plus the archived local-contract implementation/runner edits. Both conditions use the same checkout, compiler bytes, actual working directory and inherited environment; only `--local-contracts` differs. Caches and background host load remain uncontrolled.

Each report verifies exact current sources and independent native oracles before timing. Object measurements then link independent integer/owner checks against the actual cached candidate objects. Watch measurements execute independently specified checks in actual watched main and require exact output, exit zero, current receipts and clean shutdown. Current invalid edits reject with E0201; repair follows the same last-successful session. All 480 valid timed build/start samples passed and all 96 expected rejection samples matched current diagnostics. These counts exclude untimed acceptance work.

The public artifact retains exact workload/oracle text, every measured duration, all full controls, native verification and actual compiled/reused decisions. Identical object lists are interned losslessly in `object_sets`. Private command arguments, local source/log paths and checkout status are removed; command output identities remain. The embedded orchestration/curation scripts document this transformation. Original local reports and source archives remain under `build/local-contracts-paired-20261002`. The public JSON SHA-256 is `b3b3fd89b5eaad7c85413669d92bd14d1d2e0eb16fdae8208d445f01f4592972`.

## Timings

Medians in milliseconds over three samples per cell. Rebuild columns measure the in-process current build; watcher columns measure parent launch/edit to a started/rejected receipt. They have different boundaries and must not be compared as identical operations. Watch measurements use 50 ms configured polling, 100 ms debounce and 1 ms parent receipt polling; started is process creation, not readiness. Invalid rows are expected rejections.

| Workload | Revision | Objects global | Objects local | Watch global | Watch local |
| --- | --- | ---: | ---: | ---: | ---: |
| chain-32 | initial | 1514.279 | 1260.679 | 1329.189 | 1363.817 |
| chain-32 | trivia | 95.558 | 92.852 | 276.318 | 296.015 |
| chain-32 | body | 114.986 | 148.332 | 327.930 | 355.355 |
| chain-32 | contract | 1225.377 | 122.536 | 1213.952 | 318.791 |
| chain-32 | invalid | 1.795 | 1.958 | 159.918 | 163.718 |
| chain-32 | repair | 78.342 | 95.712 | 278.970 | 292.983 |
| chain-128 | initial | 3364.389 | 4483.000 | 4832.573 | 5361.798 |
| chain-128 | trivia | 118.730 | 107.556 | 324.245 | 306.900 |
| chain-128 | body | 138.653 | 167.452 | 357.971 | 426.952 |
| chain-128 | contract | 3734.202 | 119.469 | 4773.503 | 354.766 |
| chain-128 | invalid | 5.613 | 4.072 | 159.635 | 166.690 |
| chain-128 | repair | 141.090 | 93.987 | 332.455 | 328.516 |
| stores-128 | initial | 4877.935 | 4708.857 | 4928.776 | 5320.988 |
| stores-128 | trivia | 125.347 | 145.036 | 403.166 | 378.801 |
| stores-128 | body | 172.667 | 183.276 | 433.912 | 447.852 |
| stores-128 | contract | 3804.436 | 192.564 | 5261.963 | 403.253 |
| stores-128 | invalid | 43.569 | 35.277 | 196.771 | 186.900 |
| stores-128 | repair | 175.112 | 134.017 | 419.316 | 376.824 |
| borrowing | initial | 244.478 | 276.338 | 506.061 | 492.261 |
| borrowing | trivia | 110.703 | 86.083 | 269.083 | 277.597 |
| borrowing | body | 153.501 | 142.172 | 354.025 | 375.414 |
| borrowing | schema | 206.932 | 210.078 | 439.939 | 431.469 |
| borrowing | invalid | 1.339 | 1.238 | 164.222 | 164.307 |
| borrowing | repair | 78.113 | 79.412 | 272.138 | 288.340 |

Chain and store contract revisions rename a parameter without changing its types or caller behavior. The global profile recompiles all 34/130 objects; the local profile recompiles only `fn:step_0` and reuses 33/129. That exact work reduction appears in every object and watcher pair. Borrowing schema revisions change a global record layout and still recompile every unit in both profiles.

Cold builds still compile every unit and link afresh. Body, trivia, invalid and repair costs vary, and several local medians are higher. Full-build controls also vary although their code path is unchanged. Three paired observations on one warm host do not establish distributions, confidence bounds or a universal latency advantage. Keep the existing defaults and explicit profile selection.

Unmeasured: memory, disk/OS-cold behavior, application readiness, state-preserving reload, agent cost/success, Rust native reuse, other toolchains/targets and broader workloads. Linux CI separately runs both profiles' native acceptance; local macOS observations do not establish a new supported target. Earlier [global rebuild](object-rebuild-evidence.md), [watch](native-watch-evidence.md) and [rejected polling](watch-polling-evidence.md) observations use different source identities/boundaries and remain separate evidence.
