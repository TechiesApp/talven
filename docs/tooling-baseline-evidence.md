# Offline tooling baseline evidence

Status: actual fixed-workload observations, recorded on 8 September 2026. No model/provider call, tokenizer measurement, dollar-cost calculation, or production performance conclusion is supplied. See the [method and limits](tooling-baseline.md) and the [machine-readable observation](../experiments/results/tooling-linux-aarch64-20260908.json).

## Run identity

- Clean Git revision: `a635fc75d8be1f43adb8643bd92a5b8a369a4855`.
- Compiler hash: `aea751513c037a6eba45ae74a0d050550773352e22ad573daa478ed4e09a916b`, unchanged from the edit-preview increment.
- Suite: `m1c-tooling-workloads-v1`; complete/passed; four independent native oracles passed.
- Linux aarch64, kernel `6.12.76-linuxkit`, eight reported logical CPUs. CPU model unavailable inside this VM; no physical CPU model is inferred.
- CPython 3.11.16; Debian GCC `12.2.0-14+deb12u1`, target `aarch64-linux-gnu`.
- Docker Desktop Linux VM, `python:3.11-bookworm`, image digest `sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca`.
- Source and output were bind-mounted from the macOS host. No other task validation jobs ran alongside the measurement; host background load and OS/bytecode caches were uncontrolled.
- Recorded interval: 08:53:56–08:54:14 UTC. One warmup and five measured samples per operation/workload; 160 measured samples, 32 warmups, 280 total runner commands. All 48 warmup/measured executables ran successfully, in addition to the four native oracles.

Native flags were `-std=c11 -O2 -Wall -Wextra -pedantic-errors`; independent oracle compilation additionally used `-fno-lto`. The exact invocation and operator note remain in the complete report under local `build/tooling-linux-baseline-r1/`. This directory retains raw command outputs, source, candidates, generated C, oracles and executables. Its report SHA-256 is `75af54c1af5b58e5f8ac0fd84f92815163c1049a2ca19c955733a1eebb7f6cd7`.

The committed observation is a derived extract, not the complete raw report: it removes absolute executable paths and retains all measured/warmup durations, summaries, input hashes, settings, and observed tool/host identity. Hashes identify artifacts without authenticating them.

## Observed command latency

Each cell is **median milliseconds (minimum–maximum)** from five measured samples. No outlier was removed. The observation JSON retains nanoseconds before rounding.

| Operation | Vectors | Borrowing | Chain 32 | Chain 128 |
| --- | --- | --- | --- | --- |
| Check | 35.871 (34.042–44.991) | 41.561 (31.601–84.579) | 44.122 (35.979–73.050) | 48.496 (39.984–75.148) |
| Format | 36.577 (34.867–41.893) | 40.437 (37.228–66.215) | 43.608 (39.591–135.301) | 68.724 (43.500–98.767) |
| Selected context | 36.383 (32.086–42.190) | 39.737 (37.248–63.822) | 37.569 (35.476–67.674) | 48.548 (36.740–63.636) |
| Snapshot | 35.466 (33.420–58.010) | 40.982 (36.551–79.100) | 37.781 (37.189–71.541) | 42.311 (33.986–133.205) |
| Edit validation | 38.567 (35.367–48.464) | 40.831 (37.641–55.947) | 44.754 (38.624–59.789) | 63.390 (44.965–82.424) |
| Emit C | 35.244 (31.377–38.479) | 38.541 (35.617–54.577) | 42.882 (34.607–50.595) | 71.716 (45.089–670.209) |
| Direct C build | 25.914 (22.185–33.360) | 34.665 (25.806–73.952) | 85.611 (57.711–161.828) | 240.532 (168.717–1448.304) |
| Full Talven build | 65.050 (56.387–70.037) | 74.773 (62.647–347.445) | 123.369 (97.783–166.552) | 183.056 (167.667–721.197) |

The wide ranges show substantial run variation under these conditions. In particular, the largest workload's direct C median exceeds the full build median; these are separately scheduled observations, not evidence of negative frontend overhead. Repeat on a controlled host and investigate the variation before attributing differences to a compiler component. No architecture comparison, speedup, tail-latency guarantee, or compiler replacement recommendation follows from these samples.

## Observed sizes

All five samples agreed on each listed byte size. These are byte lengths, not token counts or memory footprint.

| Workload | Source | Selected context | Generated C | Direct C executable | Talven build executable |
| --- | --- | --- | --- | --- | --- |
| Vectors | 382 | 1823 | 2413 | 70464 | 70456 |
| Borrowing | 557 | 2064 | 2818 | 70536 | 70536 |
| Chain 32 | 2170 | 1554 | 9899 | 71600 | 71600 |
| Chain 128 | 8563 | 1560 | 36572 | 75184 | 75184 |

Context selected main plus direct dependencies, not every helper. The two build paths use different generated source/output filenames and hosted toolchain defaults; the vector executable sizes were observed to differ by eight bytes. No byte-identical binary claim is made.

## Verification and remaining evidence

The initial unchanged Linux baseline passed all 195 tests after correcting the container mount so the linked checkout's Git metadata was accessible. The incorrectly mounted attempt failed evaluation provenance checks and is not counted as successful evidence.

With the new runner, the Linux ARM64 suite passed all **204 tests**, with no skips, including nine new behavioral tests. The focused nine tests also passed on macOS ARM64. They cover option/output protection, raw-byte/hash preservation, timeout/launch/nonzero failures, partial receipts, warmup exclusion and sample completeness, false tool success, and complete CLI execution. A type-valid vector program whose main always returns zero was rejected by the separate dot-product oracle before any measured sample.

Documentation checks passed: 235 relative links across 47 Markdown files and four Mermaid renders. CI retains its own run reports separately with three measured repetitions per operation, rather than relabeling this local five-repetition run as CI evidence.

No original compiler, formatter, context, edit-validation, LSP, evaluation corpus, provider adapter, independent task oracle, or freestanding implementation was changed. Model effectiveness and total task cost remain unmeasured; controlled agent evaluation is still an open M1 gate.
