# Local native watcher edit observations

Status: one retained local run of the [actual watcher measurement](native-watch-baseline.md). Every source/program/receipt check passed; this is not evidence of a consistent improvement or application readiness.

The [public receipt](../experiments/results/native-watch-macos-arm64-20261002.json) retains all 192 samples (144 measured, 48 warmup), all 32 normalized session event streams, exact source/oracle texts, native acceptance and input/log identities. Artifact SHA-256: `02dd70e28eedbd259e8ac60963912cf2c4b5186a105c36818edf71c1fd5b7b2c`. Its curation removes private command/source paths and working-tree status; the exact curation script and raw local report identity are recorded. The raw archive remains in `build/native-watch-local-20261002` on the measurement host; it is not a public reproducibility service or a complete toolchain archive.

## Recorded conditions

- Apple M4, macOS ARM64 (`aarch64`), Darwin 27; CPython 3.14.7; Apple Clang 21.0.0 (`clang-2100.3.34.2`), target `arm64-apple-darwin27.0.0`.
- Compiler source hash `50b684636b0dc2397fe47d06f4146c632877e67236e606467df1d32d026321a0`; source base `a82dd292c1d57e129c8e12ac224be9be57524ab2`, with exact archived measurement-runner inputs. Profile `m1-scalar-mutation-v1`.
- UTC 2026-10-01 16:28:15–16:31:18 (2 October locally); parent `perf_counter_ns`, `mach_absolute_time()` with reported 41.67 ns resolution. This resolution does not imply timing accuracy at that scale.
- Three measured repetitions and one retained warmup per workload/mode; whole-session orders full/units, units/full, full/units. Fresh private object sessions each repetition; OS caches and ordinary background activity uncontrolled. No competing agent tests/builds ran during measurement.
- 50 ms configured polling and 100 ms debounce in both modes; native command pipelines retain their implemented at-most-5-ms active delay. Parent receipt polling sleeps 1 ms and its reading/JSON overhead is included. Fixed child overrides: `LC_ALL=C`, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`; selected Python/driver bytes and effective child-environment hash recorded.
- Default full C11/O2/strict warnings; native objects additionally use `-Werror -fno-lto`. Separate preflight C oracle compilation uses no LTO. The exact flags and driver version/target are retained.

Each watched main checks three independently specified integer inputs; borrowing also verifies owner updates and preservation of an added field. Valid programs printed exactly `accepted` plus newline and exited zero. Expected invalid edits produced current E0201 diagnostics without starting a program; repair occurred within the same session. Native trivia and repair compiled no objects and reused driver probes. All sessions exited 143 after SIGTERM with cleanup receipts. Separate ordinary-C oracles also passed before timing. These are generated, bounded single-file tasks; they are not long-running application/readiness or model-task evaluations.

## Parent-to-terminal receipt medians

Milliseconds, three measured samples per cell. Initial measures watcher launch to `started`; valid edits measure atomic source replacement to `started`; invalid edits measure replacement to `rejected`. These include source observation, debounce, native work and receipt transport/reading. Actual program exit/output verification is outside the terminal duration. Full and units have different active command polling and native build flags; these numbers compare the actual modes rather than isolating object reuse.

| Workload | Revision | Full (ms) | Units (ms) |
| --- | --- | ---: | ---: |
| chain-32 | initial | 298.559 | 1965.576 |
| chain-32 | trivia | 279.925 | 288.824 |
| chain-32 | body | 270.592 | 364.615 |
| chain-32 | contract | 281.842 | 1826.563 |
| chain-32 | invalid | 169.438 | 162.826 |
| chain-32 | repair | 284.342 | 313.879 |
| chain-128 | initial | 383.094 | 4914.277 |
| chain-128 | trivia | 342.768 | 327.377 |
| chain-128 | body | 385.109 | 422.877 |
| chain-128 | contract | 336.039 | 5010.872 |
| chain-128 | invalid | 166.781 | 161.221 |
| chain-128 | repair | 284.822 | 361.872 |
| stores-128 | initial | 536.429 | 4745.890 |
| stores-128 | trivia | 606.855 | 431.828 |
| stores-128 | body | 568.859 | 543.924 |
| stores-128 | contract | 602.376 | 4355.800 |
| stores-128 | invalid | 200.117 | 186.378 |
| stores-128 | repair | 648.263 | 391.118 |
| borrowing | initial | 319.224 | 500.181 |
| borrowing | trivia | 266.711 | 263.904 |
| borrowing | body | 264.456 | 371.660 |
| borrowing | schema | 271.772 | 449.803 |
| borrowing | invalid | 156.595 | 153.647 |
| borrowing | repair | 262.751 | 277.862 |

The larger store workload benefited on trivia/repair in this run and only slightly on body edits. Chain body edits and most repairs were slower in units. Native cold starts and global contract changes were substantially more expensive, especially with 128 functions. Rejection durations mostly reflect observation/debounce plus current full checks; rejected source never reaches object reuse. Tiny differences on borrowing trivia or rejection are not robust evidence with three samples.

Keep native reuse opt-in. Investigate active polling and repeated per-unit compilation/global contracts with separately retained comparisons before changing defaults. No percentile, universal save-to-running guarantee, memory reduction, long-running shutdown/cancellation improvement, state-preserving reload, native Rust reuse or model/token/dollar saving follows from this receipt. Earlier [in-process rebuild](object-rebuild-evidence.md) and [probe reuse](driver-probe-evidence.md) timings have different boundaries and source identities; do not pool them with this run.
