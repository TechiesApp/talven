# Native compiler experiment evidence

This record concerns the bounded [native scalar/static-text experiment](../experiments/native-compiler/README.md). It is separate from the broader reference compiler's conformance and the existing Python tooling baseline. Records/borrowing and shared editor/agent tooling are not implemented natively.

## Correctness criteria

The dedicated suite verifies actual emitted-code behavior with a trusted C11 compiler and ASan/UBSan, plus finite reference diagnostic comparisons, explicit unsupported-feature failures, and source/path limits. Comparison-runner tests require incomplete runs to retain failure evidence without summaries and reject a type-valid constant-success implementation through the unchanged independent chain oracle.

Each Linux CI job must build the pinned Rust experiment, run both dedicated suites, pass the original reference suite without skips, run borrowing sanitizers and existing independent acceptance, then archive a short comparison. A configured target is not evidence until that run succeeds.

## Measurement boundaries

Only standalone `check` and `emit-c` process durations are compared on the greeting and chain-32/128 overlap. The native prototype validates less language/tooling scope and emits different C bytes. C compilation, link, execution, receipt persistence and correctness validation are outside these frontend timings. Preflight warms inputs; OS caches and scheduling are uncontrolled. Source/tool/binary identities, settings and all raw samples belong to each report archive. No full-build, cold-cache, memory, token, dollar-cost or incremental result is inferred.

## Local Linux ARM64 observation, 11 September 2026

The full reference suite passed **246 tests without skips**. The dedicated native conformance suite passed **11 tests**, including ASan/UBSan-backed generated programs, and the comparison-runner suite passed **5 tests**. The separate reference borrowing sanitizer check passed six executions at `-O0`/`-O2`. Documentation checking rendered four Mermaid diagrams. Initial verification exposed native FIFO/byte-path handling defects and comparison provenance gaps; these were corrected and independently reviewed before this successful run.

The [retained observations](../experiments/results/native-linux-aarch64-20260911.json) contain all 60 measured and 12 warmup frontend samples from a completed, correctness-gated run. The environment was local Docker Desktop Linux aarch64, Python 3.11.16, GCC 12.2.0, Rust 1.96.0, Cargo release `opt-level=3`, no LTO, 16 codegen units, and empty effective Rust flags. Native target: `aarch64-unknown-linux-gnu`; C target: `aarch64-linux-gnu`. The container did not expose a CPU model. The host-mounted filesystem, caches and background host load were uncontrolled. Reference/native order alternated per repetition.

Five-sample medians, in milliseconds (rounded for display; raw nanoseconds/minima/maxima retained):

| Workload | Operation | Python reference | Rust experiment |
| --- | --- | ---: | ---: |

| hello | check | 34.113 | 1.137 |
| hello | emit-c | 36.770 | 1.191 |
| chain-32 | check | 33.639 | 1.127 |
| chain-32 | emit-c | 34.554 | 1.239 |
| chain-128 | check | 42.706 | 1.786 |
| chain-128 | emit-c | 47.254 | 1.408 |

These samples show shorter native frontend process durations on this finite overlap in this run. They do not establish a representative production speedup or a full-build improvement. Small-operation variation can exceed the work being compared; do not infer phase costs by subtracting medians or rank checking versus emission from this sample.

The native executable occupied 625472 file bytes, including embedded build-source metadata; its SHA-256 is retained in the record. That is not deployed dependency size, memory use, or a minimal packaged compiler size. The measurement ran before the implementation commit; accompanying source/runner fingerprints and an explicit dirty-checkout flag identify the inputs. The runner verified the executable's embedded native sources against the archived checkout. Metadata is self-reported, not an authenticity proof.

The compact checked-in record retains source/tool hashes and all frontend samples. The complete local archive also retains exact argv, streams, compiler inputs and executable artifacts; the CI workflow independently archives the same complete report format per Linux job. Cargo build time, linker/library configuration, backend alternatives, cold-cache behavior, incremental compilation and live model results remain outside this evidence.
