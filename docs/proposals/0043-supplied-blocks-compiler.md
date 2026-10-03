# Proposal 0043: Checked supplied-block compiler profile

- Status: Implemented experimental profile; explicit `m2-supplied-blocks-v1` companion
- Requirements: R01, R03, R04, R08, R09, R10, R11, R16
- Decisions: D71, D69, D70

## Scope

Implement [Proposal 0041](0041-supplied-storage-regions.md) using the standalone
[C runtime](0042-supplied-storage-c-runtime.md). Select `--resources` explicitly for
check, format, context, C emission and hosted build. The profile includes concrete
outcomes and adds `region name(capacity) { statements }`, opaque `Block`, and the
built-in outcomes/operations below. Ordinary M1 and outcome-only commands retain
their grammar and behavior. Combining resource selection with `--outcomes`, module
formatting, freestanding execution or ordinary compact/focused context is rejected.
Modules, export units, edit/test/watch/reuse/reload and native resource context are
not part of this first companion. No concurrency or heap containers are added.

Capacity is a decimal literal 1..4096; at most eight region declarations occur in
one function, counting all branches. A region is stable lexical storage, not an
ordinary value, parameter or return type. Its name is accepted only as the first
argument to `reserve`. The per-function bounds do not bound recursive total RAM.

| Built-in | Contract |
| --- | --- |
| `Allocation { Granted(Block), InvalidRequest, Exhausted }` | Linear possible child obligation tied to one origin |
| `ByteRead { Value(i32), OutOfBounds }` | Ordinary must-handle concrete outcome |
| `ByteWrite { Written, OutOfBounds, InvalidByte }` | Ordinary must-handle concrete outcome |
| `reserve(region, i32, i32) -> Allocation` | Free slot to pending outcome; request failures remain runtime alternatives |
| `release(Block) -> i32` | Consume live owner and free its origin; normal result 0 |
| `read_byte(&Block, i32) -> ByteRead` | Existing synchronous shared call loan |
| `write_byte(&mut Block, i32, i32) -> ByteWrite` | Existing synchronous exclusive call loan |

Reserve all built-in type and operation names against user declarations in this
profile. Block has no constructor, fields, conversion, copying or reassignment.
User records/outcomes cannot store Block or Allocation. Allocation cannot be a
function parameter or result, even when its current variant contains no owner.
Block results are prohibited. Owned Block parameters impose a consume-and-release
contract checked independently on every normal return; delegation is allowed.
Borrowed Block parameters cannot consume/release owners and cannot escape calls.

`Allocation::Granted(real_owner)` may rewrap a live owned Block, transferring its
same origin into a pending outcome. Its failure constructors are unavailable to
source: failures come from reserve. This keeps every Allocation value attached to
an actual lexical origin rather than inventing provenance for an ownerless value.
ByteRead/ByteWrite constructors retain ordinary concrete-outcome rules.

## Shared frontend state and obligations

Add a region statement to the shared AST and explicit resource mode to the parser
and checker. Preserve bounded depth, spans, token-preserving formatting and the
original declaration/error order. Built-ins are compiler facts rather than source
declarations or field-bearing ordinary records.

Track resource provenance separately from nominal types and moved binding names.
Each lexical origin and owning Block parameter has a slot state: free, pending
Allocation, or live Block. Local moves transfer the same unique obligation.
Matching a pending Allocation sets Granted to live and failure branches to free.
Release or a checked owning-parameter call sets the transferred origin free.
Moving or rewrapping alone never discharges release. A second reserve while its
origin is pending/live is rejected even though the C runtime defines occupied-slot
exhaustion for trusted drivers.

Every Block binding, including a match payload bound before the arm body, must be
consumed by release/delegation before its lexical binding scope exits. Every region
exit and normal return requires no pending/live child or active loan. Match arms
explicitly include their payload in exit obligations; the existing block-new-local
set alone is insufficient. Source cannot move owners into outer bindings because
whole-owner assignment and returned Block-bearing values are unavailable.

Only continuing branches join. They must agree on pending/live/free state and
linear ownership. Returning branches validate obligations before exclusion from
the join. Optional `&&`/`||` operands must preserve the same resource state as the
path that does not evaluate them. Existing loan conflicts and mutable-owner rules
apply to opaque Block: `let mut writable = block` permits an exclusive byte loan
while transferring the obligation, not whole-value assignment.

E0320 reports resource shape/capacity/forgery/escape restrictions; E0321 reports
unreleased owners, outstanding reservations, inconsistent resource branches and
optional handling. Existing E0102, E0201, E0301..E0305 and outcome errors retain
their original meaning. CLI/context/LSP share analysis; Rust independently checks
the same source. Exact source ranges and diagnostic parity are acceptance gates.

## Ordered C emission and identity

Emit the exact runtime header before type declarations. Opaque Block uses `tv_block`
(and const/mutable pointers for loans). Emit built-in nominal outcome declarations
in Allocation, ByteRead, ByteWrite order, before user outcomes and after scalar
record declarations. Emit the exact shared source adapter after type declarations
and before function prototypes. It marshals runtime discriminators to checked
`tv_tag`/selected-union-member layouts; no failed allocation payload is read.
Adapters have ordinary C linkage so unused operations remain warning-free without
nonstandard unused attributes. Their prefixed names are internal implementation
details, not a stable ownership export ABI; separate resource C units are excluded.

A region emits an ordinary C block containing `_Alignas(16) uint8_t
tv_storage_NAME[CAPACITY]`, `tv_region tv_region_NAME`, and a call to
`tv_source_init(&tv_region_NAME, tv_storage_NAME, CAPACITY)`. Reserve uses that stable
descriptor address; other arguments and owners are evaluated once in existing
source order. Each resource function ends with an unreachable terminal trap after
its checked body, making total source returns explicit for strict C compiler flow
analysis. Other intrinsics call `tv_source_reserve`, `tv_source_release`,
`tv_source_read`, and `tv_source_write`. A C compiler unable to satisfy required
alignment rejects the build; frontend-only success is not target evidence.

Reference context `talven.resource-context.v1` and LSP `talven/resourceContext`
include exact source/compiler and runtime-header/adapter identities, opaque linear
passing, owning-parameter release effects, lexical origins/capacities and bounds.
Whole-program facts require a sufficient budget and expected-source match. Runtime
identities are additional inputs, not replacements for source/compiler checks.
Rust emission embeds the same header/adapter and includes them in its compiler
identity. The source gate compares every embedded source against a fixed public
checkout manifest, archives build information, and rechecks binary/build identities
after execution; stale or changed producers cannot issue successful receipts. Initial development uses full check/build/restart.

## Independent acceptance and limits

Use original Talven source for reference/Rust checking, canonical formatting and
byte-identical C emission. Positive sources exercise invalid dynamic requests,
zero filling, bounded read/write, moves, rewrapping, delegation, nested regions,
typed early returns, consistent continuing joins, release/reuse and counter
saturation. Negative sources exercise leaked locals/parameters/payloads, scope or
result escape, forged types, duplicate release, aliases, outstanding reservations
and optional/inconsistent release paths.

A trusted `TV_REGION_SOURCE_TEST` adapter build reports initialization and completed
reserve/release/read/write operations to a separate C ledger. The ledger derives
expected states, byte contents, requests and normal return values from test inputs,
not observed runtime metadata. It can initialize sentinel contents and saturate an
instance at an origin's creation. Pair this with the runtime's separately gated
initialization-fault hook, exercising every step for bounded workloads. Production
builds contain neither source-visible hooks nor hidden allocation. Run O0/O2
ASan/UBSan drivers and inspect production object dependencies on actual declared
hosts. The standalone runtime guard/stale-token tests remain required.

Keep descriptor/backing capacity, temporaries and ledger costs distinct. No total
stack, latency, binary-size, agent benefit, cancellation or concurrency milestone
is established by this sequential profile.
