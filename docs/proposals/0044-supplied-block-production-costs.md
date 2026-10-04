# Proposal 0044: Supplied-block production cost evidence

- Status: Implemented measurement experiment; no performance guarantee
- Profile: existing `m2-supplied-blocks-v1`; no language extension
- Requirements: R09, R10, R11, R16
- Decisions: D72, D69, D70, D71

## Scope and independent acceptance

Measure three fixed original Talven functions at capacities 1, 32 and 4096:
one reserve/read-zero/release cycle, two cycles with write/read and reuse in one
region, and two sequential lexical regions. Dynamic size, alignment and index
arguments follow four archived successful input rows. Invalid and oversized
requests are checked before timing and excluded from successful-call summaries.

Both compilers independently check and format the original expanded source and
must emit identical C. Capture exact compiler, source, runtime, driver and tool
identities. Validate the Rust executable's embedded fixed public source manifest
against current files before and after execution. Historical receipts for changed
inputs cannot substitute for current acceptance.

Run the existing source sanitizer gates for each producer. In addition, execute
the new fixtures with an independent event/byte ledger at O0 and O2 under
ASan/UBSan. The ledger derives expected requests, byte values, events and scalar
returns from the input schedule. Valid typing alone does not establish the
workload's correctness. Production binaries contain neither event/fault hooks nor
the ledger nor sanitizers.

## Distinct costs and limits

| Quantity | Evidence | Interpretation |
| --- | --- | --- |
| C layouts | Executed `sizeof`, `_Alignof`, `offsetof` probe for runtime and nominal outcomes | Target-specific representation and padding; not total RAM |
| Supplied backing and work | Literal capacities, lexical regions, independently checked operation counts and successful request bytes | Source-derived semantic work; not executed memory traffic |
| Per-function stack usage | Compiler-produced static `.su` records for selected generated functions at O0/O2 | Compiler-reported bytes, not a measured whole-stack or peak-memory bound |
| Artifact sizes | Exact object/executable file bytes, raw named-section and symbol output | Toolchain-specific file/section evidence; no unique runtime-overhead subtraction |
| Complete-call latency | Monotonic-clock batch duration divided by verified call count | Includes initialization, matching, zeroing, reads, release, call and loop overhead |

Descriptor, owner and outcome layout sizes cannot simply be added to capacity to
predict an optimized frame: values can overlap, be inlined, disappear or require
extra spills/alignment. Release frees the slot obligation while its backing object
remains within its lexical lifetime. Region exit need not change the stack pointer
or return pages to the OS. Sequential regions allow inspection of storage reuse
without requiring an optimization.

[GCC's stack-usage documentation](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc.pdf)
distinguishes static, dynamic and bounded records;
[Clang documents its `.su` output option](https://clang.llvm.org/docs/ClangCommandLineReference.html#cmdoption-clang-fstack-usage).
This experiment accepts only static selected-function records. It archives
assembly for inspection but does not independently interpret every ABI frame,
red zone, callee frame or recursive call chain. Report the evidence as
**compiler-reported stack usage**, including zero when the compiler reports zero.

Compile generated C and the production driver separately with LTO disabled at
fixed strict C11 O0/O2 settings. Retain unchanged generated C, assembly, objects,
stack records and binaries. Preserve exact tool arguments and tool identities.
Inspect undefined symbols at the generated-object boundary using the resource
gate's permitted dependency set; hosted startup and transitive libc behavior are
outside that boundary. Preserve raw section output because ELF and Mach-O
categories differ. No executable-size subtraction is called an isolated resource
runtime cost.

An optimizer may simplify semantically unobservable work. Do not insert volatile
backing storage or timing hooks to defeat it while claiming ordinary production
behavior. Nominal initialized-byte counts describe language semantics, not stores
observed in machine code.

## Timing and receipt contract

Use `CLOCK_MONOTONIC` and record `clock_getres`. A single clock pair surrounds a
bounded batch of complete calls in the independently compiled C driver. Process
launch, acceptance, compilation and output parsing remain outside that interval.
Every batch must have the exact expected checksum and call count, positive clock
resolution and elapsed time at least 100 times the reported resolution. Reject
inadequate samples rather than reporting apparent precision. Checksums and varying
arguments keep calls observable to the separate driver; they do not prevent valid
optimization within the generated functions.

The runner accepts 1..100 measured batches, 0..10 warmups and a bounded iteration
count divisible by four. Retain all raw output and warmups; summarize only the
complete verified measured groups with count/min/median/max batch-average time per
call. Report actual CPU/OS/architecture, C target/compiler, Python orchestration
clock and operator-supplied conditions. CPU frequency, migration, contention and
cache state are uncontrolled. No p99, isolated reserve/release/zeroing latency or
guarantee follows from these finite samples. Do not subtract workload medians and
label the difference an individual intrinsic's cost.

Reuse the offline recorder's bounded subprocesses, fresh output directory,
fingerprints and raw command archives. The `talven.resource-cost.v1` receipt starts
with `complete/passed` false and no summary. It records exact expanded sources and
schedule, archived inputs, native build/binary identity, acceptance receipts,
artifacts, layouts, static stack records and timings. Recheck all captured input
and producer/tool identities before completion. Preserve failed commands and
partial artifacts without publishing successful summaries.

Tests cover malformed/missing/dynamic stack records, strict timing output,
checksums, inadequate clocks, incomplete groups, excluded warmups, bounded options,
existing output protection and producer/input changes. CI executes on actual
Linux x86-64 and ARM64 hosts, retains receipts and checks correctness/completeness;
it sets no timing or size threshold on shared hosts. Local macOS ARM64 evidence
is labelled separately.

## Remaining M2 work

This increment measures the fixed sequential hosted workloads only. General
allocators, heap containers, concurrency, cancellation, executor costs, tail
latency, process peak RAM/RSS, complete recursive stack bounds, cross-language
overhead and live-agent benefit remain open. The broader M2 gate is incomplete.

## Alternatives and trust boundary

A hand-written runtime microbenchmark would measure a different boundary from
checked Talven source; keep it for a separate experiment if isolated intrinsic
costs become necessary. Process RSS would include hosted startup, allocator and
OS effects and cannot establish the resource's stack budget. Instrumenting every
production event would change the code under measurement. A shared-host speed
threshold would confuse host noise with semantic correctness.

This runner adds offline tool/receipt complexity, not runtime dependencies or
compiler context fields. Native toolchains and the independent test driver are
trusted local inputs; this is no hostile-code sandbox. Capture only public source
and selected environment facts, not secrets or complete environment dumps.
Resolve macOS dispatch wrappers and record the effective executable and selected
SDK/sysroot. System headers, linker inputs and hosted libraries are not a fully
archived immutable toolchain; executable hashes do not claim that stronger bound.
No package, board, foreign ownership ABI or concurrent allocator support follows
from executing these hosted workloads.
