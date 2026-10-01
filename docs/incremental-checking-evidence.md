# Persistent function-checking evidence

Status: actual local observations on 1 October 2026, using the [measurement method](incremental-checking-baseline.md). The [committed extract](../experiments/results/incremental-macos-arm64-20261001.json) retains every warmup/measured duration, reuse count, diagnostic, summary and input identity. No model/provider, tokenizer, token or dollar-cost measurement was performed.

## Run identity

- Working tree based on `ddba3283e963364743df1b236d5e5337670958d1`, with the measurement harness and immutable-span optimization recorded in the extract's source identities. This was not a clean checkout of that commit.
- Compiler hash: `1108334f54d7617d79e495c5e289f622990dbab742b4b7fd781dd035ddf39578`.
- Apple M4, macOS/Darwin kernel `27.0.0`, ARM64 (normalized as `aarch64`), CPython `3.14.7`.
- Apple Clang `21.0.0` (`clang-2100.3.34.2`), target `arm64-apple-darwin27.0.0`.
- `LC_ALL=C`, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`; garbage collector settings are retained. Native acceptance uses C11 `-O2`, warnings/pedantic checks and `-fno-lto`.
- Interval: 07:50:50–07:51:03 UTC. Seven measured repetitions and one warmup; 336 measured samples, 48 warmups. All 20 valid-revision native drivers passed, and all expected invalid revisions reported `E0201`.
- Other development applications were open. Focused development tests ran alongside part of this measurement; host load and caches were uncontrolled. This is a correctness-gated local observation, not a controlled optimization comparison or platform-wide guarantee.

Complete receipts, exact source revisions and compiler/measurement inputs, generated C, drivers, executables and raw command streams remain under local ignored `build/incremental-comparison-local-optimized/`. The complete report's SHA-256 is `5065a7e1232b04eba1087a69b296f4ea109f64484f9ac5966c063addda0d10eb`. The public extract omits absolute command paths and raw command streams, replacing function-name reuse lists with their counts. It is a derived observation, not the full raw report or authenticated evidence.

## Observed checking latency

Each cell is **median milliseconds from seven measured samples**. No outlier was removed; minimum/maximum and every raw nanosecond sample remain in the extract. Native verification and report writing are outside these timings. Full analysis and persistent analysis run in the same process with condition order alternating across repetitions.

| Edit | Chain 128 full | Chain 128 persistent | Stores 128 full | Stores 128 persistent |
| --- | --- | --- | --- | --- |
| Initial | 3.820 | 4.982 | 26.677 | 31.382 |
| Leading comment | 3.928 | 4.151 | 27.434 | 36.681 |
| Helper body and main | 3.667 | 4.083 | 29.431 | 28.637 |
| Parameter-name contract | 3.836 | 3.832 | 32.124 | 31.319 |
| Invalid return | 3.246 | 3.559 | 34.860 | 26.296 |
| Repair | 3.286 | 3.822 | 26.602 | 28.025 |

The initial chain sources are 8,563 bytes; the store-heavy source is 41,327 bytes. Both contain 128 helpers plus main. Every leading-comment and repair revision reused all 129 function checks. Body edits checked the changed helper and main; parameter-name changes checked the helper and its direct caller. The persistent mode still parsed every function and reconstructed current references.

On the smaller borrowing workload, median full checks were about 0.13–0.15 ms for valid revisions, while persistent checks ranged from about 0.40–0.67 ms. Compiler identity hashing and cache bookkeeping dominate such small inputs. Adding a field invalidated all three functions as required; the native driver verified that the field stayed intact during mutation.

These results do **not** establish a consistent speedup. Reuse often costs more than repeating the small checker, and some large-workload medians overlap or vary with collection/load. An earlier local exploratory run exposed excessive position allocation; the implementation now reuses immutable unchanged spans and constructs each moved local definition once per function. The earlier and current runs were not a controlled paired optimization experiment, so their difference is not attributed quantitatively to that change.

## Correctness and remaining work

Every measured result matched full current analysis, diagnostics, reference locations/descriptions, deterministic context and accepted emitted C. Invalid revisions preserved only the previous successful cache and repairs reused it. Independent native drivers checked full-i32 values and borrowing mutations. The focused 30 tests for reuse, development sessions and the measurement harness passed locally. The full reference suite passed 321 tests with one Linux-only static-text sanitizer test skipped on this macOS host; Linux CI requires no skips.

The experiment justifies keeping reuse opt-in while investigating parsing, allocation and native integration. Memory/RSS and end-to-end feedback remain unmeasured. Linux CI runs the same correctness gates and retains separate receipts; this local record is not relabeled as Linux evidence or a production-speed claim.
