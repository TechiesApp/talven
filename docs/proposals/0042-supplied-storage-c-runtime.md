# Proposal 0042: Supplied-storage C runtime prototype

- Status: Implemented C experiment, `c11-single-slot-regions-v1`; no Talven source support
- Requirements: R08, R09, R10, R11, R16
- Decisions: D70, D69, D67

## Purpose and boundary

[Proposal 0041](0041-supplied-storage-regions.md) chooses stable lexical storage and
explicit linear release for the first resource slice. This prototype fixes and
tests its C descriptor, allocation-instance, initialized byte and rollback behavior
before adding opaque owner types to a compiler. The
[runtime header](../../experiments/supplied-storage/runtime.h) is called only by
trusted C drivers. It does not make `region`, `Block`, `reserve` or `release` valid
Talven syntax, and it does not enforce source moves, loans, function-result escape,
region scope exit or consume-and-release function contracts.

The next compiler increment must implement those obligations in the shared
CLI/context/LSP frontend and independent native checker. Runtime tests cannot
substitute for that proof. General allocation, containers, automatic cleanup,
foreign-pointer imports and concurrency remain unimplemented.

## Exact C representation and operations

| Value | Stored fields |
| --- | --- |
| `tv_region` | Storage pointer; capacity; `uint64_t` instance; live size; live alignment; occupied boolean |
| `tv_block` | Origin descriptor pointer; matching `uint64_t` instance; requested length and alignment |
| `tv_allocation` | `uint32_t` tag and union containing a block payload |
| `tv_byte_read` | `uint32_t` tag and `int32_t` byte value when successful |

Lengths/capacities/alignments use C `size_t`; target padding/alignment remains
visible and is measured by the driver. Storage is supplied separately, aligned to
16 bytes, with capacity 1..4096. Initialization starts a fresh logical origin
lifetime and initializes metadata without filling the storage. C callers must keep
the descriptor and actual backing object alive and cannot reinitialize an origin
while earlier tokens remain valid. Source enforcement of these rules is future work.

`tv_region_reserve` accepts `int32_t` size/alignment. Nonpositive size or alignment
outside 1, 2, 4, 8, 16 returns `InvalidRequest`; a request beyond capacity, occupied
slot or saturated instance counter returns `Exhausted`. Validation precedes state
changes and signed-to-size conversion. A valid reservation increments its instance,
marks the slot occupied, initializes exactly the requested bytes to zero and then
returns `Granted`. Its owner records the exact request and live descriptor.

`tv_region_release` checks occupancy, instance, length and alignment before freeing
the originating slot. The instance counter is never decremented or wrapped. A
last reservation can publish `UINT64_MAX`; after release that free origin remains
permanently exhausted. A stale C token from an earlier same-request allocation
therefore cannot release a later owner while the origin remains alive.

`tv_region_read`/`tv_region_write` validate the live owner before indexing. Bounds
are checked before pointer arithmetic; reads return `Value` or `OutOfBounds`.
Writes check bounds before requiring a byte value in 0..255, returning `Written`,
`OutOfBounds` or `InvalidByte`. Failed writes leave memory unchanged. An invalid
state/request/instance token with a live descriptor aborts before storage access.
Arbitrary forged matching tokens, dangling origins and undersized supplied objects
are outside the trusted-C preconditions, not a public safe foreign-pointer ABI.

The prototype write result is a scalar C discriminator, and its read value is a
direct C field. These are internal C test interfaces, not the Talven concrete-outcome
ABI. Compiler integration must adapt them to checked nominal alternatives and
their selected-payload layout before claiming emission/interface parity.

## Initialization failures and independent ledger

Production reservation zero filling has no normal fallible operation. A separate
`TV_REGION_TEST_FAULT` build calls a trusted fixture hook after reservation, before
every byte initialization and before owner publication. Injection returns
`Exhausted`, clears occupancy/live request metadata and retains the consumed
instance. Partial initialized bytes remain in inaccessible supplied storage; a
successful retry initializes its full visible range. No owner is published on
failure, and the hook is absent from production runtime calls.

The [C acceptance driver](../../tests/fixtures/region-runtime-driver.c) keeps a
separate ledger and expected byte buffer. It computes expected request outcomes,
instance progression, partial initialization, live ownership and release counts
from its inputs and test plan. It compares observed descriptor/owner fields and
all backing/sentinel bytes against that ledger; it does not use emitted runtime
bookkeeping to generate expected values.

For capacities 1, 32 and 4096, production and injected builds run at O0/O2 under
ASan/UBSan. Positive workloads cover all size/alignment validation combinations,
boundary indices/byte values, occupied-slot preservation, release/reuse, every
initialization failure point for size 1 and full capacity, and counter saturation.
Every complete workload requires no live ledger entries. Nonsaturated origins
must be reusable; saturation instead requires free occupancy and permanent
exhaustion. Guard bytes and failure-write memory remain unchanged as specified.

Each build also executes six separate negative probes: stale owner after
same-request reuse, double release, mismatched length, alignment or instance, and
read after release. Each must terminate specifically with SIGABRT, without ASan or
UBSan error output. A merely nonzero ordinary oracle exit is not accepted as a
trap. These process probes imply no in-process recovery or unwind cleanup.

The [gate script](../../scripts/check-region-runtime.py) compiles captured exact
header/driver bytes, runs twelve positive executions and 72 negative processes,
and rejects observed input changes. It also compiles a production object without
sanitizers/test hooks, records all undefined symbols and permits only abort,
byte-copy/fill and compiler stack/GOT support symbols. Any other direct dependency,
including heap allocation or test hooks, fails. This inspection covers that object, not transitive libc/startup
behavior. Required Linux x86-64/ARM64 CI runs the same gate through the unittest
suite and retains a separately generated JSON receipt.

## Evidence and costs

~~~sh
python3 scripts/check-region-runtime.py --out build/region-runtime.json
python3 -m unittest tests.test_region_runtime -v
~~~

`--out` creates a new file; default output is JSON on stdout. Successful
`talven.region-runtime-check.v1` receipts preserve exact source texts/hashes,
compiler version/target, actual host architecture, compiler settings, each layout,
successful ledger/trap checks, production wrapper and observed undefined symbols.
Unsupported hosts/tools and any failed check fail the gate instead of skipping.
The declared C process/signal boundary is Linux/macOS; other targets remain open.

The [retained local receipt](../../experiments/results/region-runtime-20261004/receipt.json)
passed all twelve positive and 72 negative executions on macOS arm64 with Apple
Clang 21.0.0. On this recorded target the descriptor is 48 bytes, block 32 bytes and
allocation result 40 bytes. These are measured C layouts for the captured inputs,
not portable layout guarantees or the complete region storage cost. CI produces
separate receipts for its actual Linux targets.

The experiment measures `sizeof` descriptor/block/allocation values only. Supplied
capacity, alignment padding between local objects, simultaneously live owner/outcome
copies, generated frame layout and the fixture's independent buffer/ledger add
separate storage costs. Capacity stays reserved until its enclosing C storage
lifetime ends even after slot release. No latency, total/peak stack, executable-size
or live-agent benefit is measured, and no heap-free process/startup claim follows
from a helper object without direct heap symbols.

## Next implementation gate

Add explicit region/opaque block AST and provenance state, prevent region movement
and block-bearing results, enforce linear release or checked synchronous delegation
on every normal return/scope exit, preserve obligations through constructors and
exhaustive matches, and reject inconsistent joins/optional release paths. Integrate
versioned effects/context with exact source/runtime identities and native parity.
Test escaped storage, aliases and source use/double release alongside these C gates.
No M2 resource-lifetime milestone is complete before that implementation passes.
