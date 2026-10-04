# Supplied-block production costs

This offline experiment measures fixed sequential workloads under the existing
`m2-supplied-blocks-v1` profile. It adds no language feature. See
[Proposal 0044](proposals/0044-supplied-block-production-costs.md) for the evidence
contract and [the resource guide](resources.md) for ownership semantics.

~~~sh
cargo +1.96.0 build --release --offline --locked --manifest-path experiments/native-compiler/Cargo.toml
python3 scripts/measure-resource-costs.py \
  --native experiments/native-compiler/target/release/talven-native \
  --out build/resource-costs --repetitions 5 --warmups 1 --iterations 100000
~~~

Use a fresh output directory. The runner requires an already-built native compiler
whose embedded source matches the current checkout, a native C11 compiler, `nm`
and a section-size tool. Actual Linux x86-64/ARM64 and local macOS ARM64 runs are
labelled by host and C target; unsupported/missing evidence fails rather than
silently skipping it. `--expect-arch` checks the actual host architecture.

The [fixed Talven source](../experiments/resource-costs/workload.tal) expands to
capacities 1, 32 and 4096. Its cycle, reuse and sequential-region functions use
dynamic size/alignment/index arguments from a fixed schedule. Both producers
independently check/format original source and agree on emitted C. Existing source
acceptance and the [new independent C ledger](../experiments/resource-costs/driver.c)
run under O0/O2 ASan/UBSan. Ledger and fault hooks are excluded from production.

Production builds compile the generated unit and driver separately at O0/O2 with
LTO disabled. Each timing sample covers a complete batch inside the C driver using
`CLOCK_MONOTONIC`. It excludes process startup and compilation. Every batch must
match independent return/checksum expectations and clear a clock-resolution
adequacy check. Warmups are retained but excluded from summaries.

The report separates these quantities:

- Executed target C sizes, alignments and field offsets, including nominal outcomes.
- Literal supplied capacity and source-derived operation/initialized-byte counts.
- Compiler-reported static per-function stack usage, with raw records and assembly.
- Actual object/executable file sizes and raw section/symbol output.
- Verified batch-average elapsed time per complete call, with every raw sample.

The `report.json` schema is `talven.resource-cost.v1`. Only a complete verified
run has `complete/passed` true and a summary. It archives exact inputs, generated
units, native build information and binary identity, acceptance receipts, tools,
artifacts and raw command output. Observed input/producer/tool changes fail the
run. Failed reports retain their reason and partial evidence.

On macOS, system compiler/tool dispatch wrappers are resolved to their selected
Xcode executables. The runner records the selected SDK path/version and explicit
sysroot used by that compiler. Compiler and inspection executable identities do
not establish a complete immutable toolchain: system headers, linker inputs and
hosted libraries are not all archived. Existing source-gate receipts record their
own `cc` selection separately from the runner's production compiler.

A smaller request does not shrink its declared backing capacity. Release frees
the slot while the backing remains within its lexical lifetime. Layout sizes do
not add up to an optimized frame, and `.su` bytes do not establish total recursive
stack use or process peak RAM. Initialized-byte counts describe semantics rather
than observed memory traffic. Inspect archived assembly before attributing an
optimization to a particular operation.

Cache state, CPU frequency/migration and host contention are uncontrolled. These
finite batch samples do not measure isolated reserve/release/zeroing costs, p99,
tail latency, cross-language overhead or agent effectiveness. Containers,
concurrency, cancellation and the broader M2 gate remain open.

## Local observation: macOS ARM64

The [4 October 2026 receipt](../experiments/results/resource-costs-macos-arm64-20261004.json)
passed all six capacity/optimization configurations, 90 measured batches and
18 warmups on an Apple M4, macOS 27.0, Apple Clang 21 and SDK 27.0. Each measured
batch made 100,000 complete calls. Both existing producer source gates and all
six new independent sanitizer ledgers passed. This is a local observation with
uncontrolled workstation conditions, separate from required Linux CI evidence.

| Capacity | O0 cycle/reuse/sequential static stack bytes | O2 cycle/reuse/sequential static stack bytes | O2 generated object file bytes |
| --- | --- | --- | --- |
| 1 | 448 / 1024 / 816 | 0 / 0 / 0 | 2160 |
| 32 | 480 / 1072 / 880 | 80 / 80 / 96 | 2896 |
| 4096 | 4544 / 5136 / 9008 | 4160 / 4160 / 4176 | 3096 |

These are compiler-reported static function records and actual file sizes. The
one-byte O2 result illustrates elimination of storage in a bounded workload;
the sequential-region records illustrate compiler-dependent storage reuse.
Neither establishes a general total-memory guarantee. The receipt retains every
verified timing sample and summary; complete-call averages include driver loop
and checksum overhead and are not isolated intrinsic costs.

The committed JSON preserves identities and sample records. Its relative command
and artifact paths refer to the full local bundle at
`build/resource-costs-macos-arm64-20261004-v5`, rather than files committed beside
the JSON. CI uploads complete Linux bundles, including raw outputs, source,
assembly and binaries, with 30-day retention. Regenerate into a fresh directory
when that retention expires; the public report alone is not the complete binary
and raw-command archive.
