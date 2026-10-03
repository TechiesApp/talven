# Native agent-tool CLI baseline

Status: implemented optional comparison under [Proposal 0013](proposals/0013-native-scalar-compiler.md), with a finite local observation. It measures the checked compact context and read-only canonical formatting added by [Proposal 0031](proposals/0031-native-compact-agent-context.md) and [Proposal 0032](proposals/0032-native-canonical-formatting.md). It does not select a production compiler or establish the live-agent M1 gate.

## Run and acceptance

Build the pinned [native compiler](../experiments/native-compiler/README.md), then run:

~~~sh
python3 scripts/measure-native-prototype.py --native experiments/native-compiler/target/release/talven-native --out build/native-agent-tools --repetitions 5 --warmups 1 --agent-tools
~~~

`--agent-tools` selects `talven.native-agent-tools.v1`, with explicit operations `check`, `emit-c`, `context` and `fmt`. Without it, the existing `talven.native-comparison.v1` check/emission report and 12 summary groups remain unchanged. Each report names its operations. A new output directory is required; failed runs retain partial receipts with no summary, and existing outputs are preserved. The declared native Linux CI jobs retain this separate archive alongside the original comparison and phase baseline.

Use the same fixed greeting and chain-32/128 inputs as the existing comparison. Before timing, require exact compact context bytes from current reference analysis and exact syntax-only canonical layout, with reference formatting idempotence. Both CLIs must satisfy these expectations. Each implementation's original emitted C must independently pass the greeting or full-signed-integer chain oracle through the trusted C11 compiler. Re-emitting the formatted source must produce byte-identical accepted C, and both formatters must accept the canonical file in JSON check mode. These verification commands remain outside timed samples.

Timed outputs must reproduce the verified preflight bytes. Complete measured groups contain exactly the requested repetitions for every workload, operation and implementation; missing/unverified context or formatting samples prevent a summary. The [comparison tests](../experiments/native-compiler/tests/comparison.py) exercise exact-output rejection, missing/unverified operations, actual native acceptance, failure retention and stale formatter/compiler source detection. The shared differential/formatting suites provide broader functional coverage than the three measured inputs.

## Measurement boundary

Every sample is a standalone process duration including launch, source I/O, frontend work, serialization/layout and stdout capture. Context performs full checking; formatting requires syntax only and re-lexes its output. This compares equivalent behavior per operation, not equal work between context and formatting. The inputs are already canonical. Core phases, editor edits, persistent sessions and formatting noncanonical/comment-heavy programs are not timed here.

Preflight warms input/code caches. Reference/native order alternates within each repetition; the small fixed workloads, first-order imbalance for odd repetition counts, OS scheduling, caches and background load limit inference. Receipt persistence, C compilation/link/execution and correctness checks are excluded. Source/runner/test and executable identities, exact embedded native sources, Rust/C settings, actual host, clock and raw samples are retained. Model/tokenizer versions and billing do not apply: no model provider is called. No token, dollar-cost, full-build, cold-cache, memory or incremental benefit is measured.

## Local macOS ARM64 observation, 3 October 2026

The [compact retained record](../experiments/results/native-agent-tools-macos-arm64-20261003.json) contains 120 measured and 24 warmup samples across 24 groups: five repetitions and one warmup for three workloads, two implementations and four operations. All preflight, native task, formatted C/layout and repeated-output checks passed. The full local archive at `build/native-agent-tools-20261003/` additionally preserves source/compiler/runner inputs, executable artifacts, argv and streams. Compact records omit local path/stream contents and retain their byte counts and hashes.

UTC interval: `2026-10-03T03:31:06.308213+00:00` to `2026-10-03T03:31:15.973662+00:00`. Host: Apple M4, macOS/Darwin 27.0.0, aarch64, CPython 3.14.7. Native compiler: Rust 1.96.0, `aarch64-apple-darwin`, Cargo release optimization 3, no LTO, 16 codegen units and empty effective Rust flags; present settings are retained. C acceptance used Apple Clang 21.0.0 targeting `arm64-apple-darwin27.0.0`, strict C11/O2 flags recorded in the artifact. The clock is `mach_absolute_time()`; exact reported resolution is retained. Background host load and caches were uncontrolled.

Measured medians in milliseconds, rounded for display; every raw nanosecond sample and min/max remain in the record:

| Input | Input bytes | Context bytes | Operation | Python reference | Rust native |
| --- | ---: | ---: | --- | ---: | ---: |
| hello | 58 | 83 | compact context | 56.961 | 3.441 |
| hello | 58 | 83 | canonical formatting | 57.473 | 3.592 |
| chain-32 | 2170 | 1097 | compact context | 98.492 | 7.934 |
| chain-32 | 2170 | 1097 | canonical formatting | 101.482 | 6.250 |
| chain-128 | 8563 | 4197 | compact context | 54.571 | 3.691 |
| chain-128 | 8563 | 4197 | canonical formatting | 61.962 | 3.828 |

Native process durations were shorter on these inputs in this run. Python launch/import work is included, so this is not a core-compiler throughput ratio. Chain-32 was slower than chain-128 in both implementations during portions of the run, illustrating uncontrolled load; do not infer workload scaling or rank core phases from these medians. Five samples per group do not establish a representative production benefit.

The native executable was 782816 file bytes, including embedded source/build metadata, with SHA-256 `f556d6ebe6bd9126c913774df813c86d34a072803303570d4e483afa5a2407ea`. This is not RAM use or packaged dependency size. The measurement base commit was `195c5fb94a895421d8e2e6d28145d5ae849dbb87`, with the new runner/tests present as recorded uncommitted inputs; their exact hashes identify the measured implementation. Native embedded source identity was verified. The report's source hashes and self-reported metadata provide provenance rather than authentication. Historical native results remain separate and are not relabeled as measurements of these tools.
