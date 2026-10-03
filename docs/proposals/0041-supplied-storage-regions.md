# Proposal 0041: Sequential supplied-storage regions and linear byte blocks

- Status: Draft; specification only, no compiler/runtime support
- Requirements: R01, R08, R09, R10, R11, R16, R24, R25
- Decisions: D69 (proposed), D68, D67, D06, D07, D27

## Problem and chosen boundary

[Concrete outcomes](../outcomes.md) provide explicit typed error paths. The next
M2 slice must establish a real allocator lifetime before introducing an owned
resource. [Proposal 0039](0039-typed-failures-resource-contracts.md) rejects using
an ordinary call-scoped allocator loan to back an owner returned from that call.
This proposal chooses a deliberately restricted lexical region experiment.

Choose one explicitly supplied region with one reusable allocation slot and an
owned byte block. Source does not select a process heap or global allocator.
Regions are compiler-managed scope tokens backed by bounded local storage. They
cannot move, be copied, borrowed as ordinary parameters, stored in records or
returned. A block's origin region remains stable until its release obligation is
fulfilled. Blocks can cross synchronous calls only under a consume-and-release
contract; no block or block-bearing outcome can escape through a function result.

This is a candidate first resource profile, not general lifetime syntax, a heap
allocator ABI, a container library, an arena with multiple allocations, or evidence
that arbitrary returned heap owners are safe. The implemented outcome profile
continues to admit only scalar/record payloads; the opaque types and grammar below
require a separate implementation and verification gate.

## Proposed source and operations

A future explicit `m2-supplied-blocks-v1` profile would add a scoped declaration:

~~~text
region storage(64) {
    let attempt = reserve(storage, 16, 8);
    match (attempt) {
        Allocation::Granted(block) {
            release(block);
        }
        Allocation::InvalidRequest { }
        Allocation::Exhausted { }
    }
}
~~~

This is proposed syntax; it does not compile today. A region capacity is a decimal
literal from 1 through 4096 bytes. Initially allow at most eight region declarations
per function, including declarations in mutually exclusive branches. Capacity and
region count are explicit compile-time bounds, with no runtime capacity expression
or automatic capacity growth. Recursive calls may still create an unbounded total
number of frames; these per-function limits are not whole-program RAM guarantees.

The region token is a lexical capability accepted only by `reserve`. It is not an
ordinary `&mut` loan and does not use existing `escapes:false` call metadata as a
lifetime proof. A resource-aware frontend must relate the reservation outcome and
selected block owner to the exact enclosing region declaration.

| Proposed operation | Contract |
| --- | --- |
| `reserve(region, size: i32, alignment: i32) -> Allocation` | Validate request, reserve one slot, initialize the selected byte range, return a typed outcome tied to this region |
| `release(block: Block) -> i32` | Consume the linear owner, release exactly its originating slot, return 0 on the well-typed normal path; detected state/metadata violations trap |
| `read_byte(block: &Block, index: i32) -> ByteRead` | Call-scoped read loan; return `Value(i32)` in 0..255 or `OutOfBounds` |
| `write_byte(block: &mut Block, index: i32, value: i32) -> ByteWrite` | Call-scoped exclusive loan; return `Written`, `OutOfBounds` or `InvalidByte`; failures leave bytes unchanged |

Proposed built-in concrete outcomes are `Allocation { Granted(Block), InvalidRequest,
Exhausted }`, `ByteRead { Value(i32), OutOfBounds }` and
`ByteWrite { Written, OutOfBounds, InvalidByte }`. Outcome/variant names are nominal
and reserved against user redefinition in this profile. A `Block` constructor,
record literal, public fields, scalar conversion and forged pointer are unavailable.
The resource profile would explicitly extend the outcome payload classifier for
this opaque linear type; existing record payloads remain affine scalar aggregates.

`release` is an explicit terminal ownership operation, not a fallible domain
failure to ignore. Its scalar success receipt does not discharge an outcome by
itself; checking must record consumption and the region slot's release. Automatic
release on scope exit, destructors, unwind cleanup and user allocator callbacks
are excluded. A trap terminates execution without a language cleanup guarantee.

## Request and runtime rules

Validate in this order before changing region state:

1. Size must be positive. Zero and negative sizes are `InvalidRequest`; no
   zero-size owner is manufactured.
2. Alignment must be one of 1, 2, 4, 8 or 16. Other values are `InvalidRequest`.
3. A positive size beyond region capacity, an occupied slot, or an exhausted
   allocation-instance counter returns `Exhausted`.
   In well-typed first-slice source a second
   reservation with an outstanding possible owner is rejected statically; the
   runtime result remains defined for the trusted C test boundary.
4. Reserve the validated slot, zero-initialize exactly `size` bytes, then publish
   the initialized owner. No caller may read an uninitialized byte. Capacity beyond
   the selected range remains inaccessible to safe source.

The implementation must select and verify a C target that supports 16-byte local
alignment; it must reject a target that cannot meet the contract. There is no
assumption that every board or C implementation supports this profile. A single
slot always starts at the supplied storage base, so request rounding and pointer
arithmetic are unnecessary. Validate integer inputs before converting to C size
values. Byte bounds require `0 <= index < length` before addressing storage;
write values require 0..255 before conversion. Define write validation precedence
as bounds first, byte value second, with no memory change on either failure.

The initial region backend uses C local storage with its capacity and required
alignment, plus an explicit stable descriptor. A block retains its origin
identity, a nonaliasing allocation-instance token, and the exact validated
length/alignment needed for release. The descriptor and block each carry a
`uint64_t` instance value. A new region starts at zero and increments before each
reservation; `UINT64_MAX` is exhaustion, never wraparound. Failed initialization
rolls back occupancy but does not reuse its instance value. Thus a retained C
copy of a released owner cannot release a later same-size/same-alignment owner
while that origin remains alive. The chosen
representation must be recorded before implementation, including every descriptor,
owner, occupancy field, pointer and padding byte; this proposal does not invent a
measured layout or byte count. Region initialization must initialize metadata before
use; only an allocated block's visible byte range needs initialization. Production
reservation/release has no hidden heap allocation or reference count.

Release verifies the originating slot, allocation instance and owner's exact
validated request before making it reusable. Source cannot select a different region at
release. A slot becomes free before the region ends or the next reservation starts.
Detected state/request/instance mismatches trap at the trusted C test boundary.
The source checker separately rejects wrong-origin transfer, duplicate release
and escape attempts. Trusted C probes require a live origin descriptor; a dangling
origin or a completely forged token indistinguishable from a valid owner is
outside that boundary. This introduces no public foreign-pointer ABI or permission
to manufacture owners. The compiler must reject source double release and use after move.

## Lifetime and linear obligations

A region scope creates stable storage; its lexical token is never movable. A
reservation outcome temporarily holds a possible child-owner obligation. Until
that outcome is consumed, the region cannot be reserved again or leave scope.
Matching `Granted` transfers the same origin relation into its selected `Block`
binding; failure arms create no new block. Failure leaves an initially free region free
and never changes pre-existing occupancy or another live owner in a trusted C
occupied-slot probe. Constructors or
moves that rewrap an existing block must preserve the origin and release obligation.
No source operation can duplicate or erase them.

A block is linear, including an unused function parameter: every normal return or
scope exit must have released it or transferred it to a checked synchronous
consume-and-release parameter. Whole-value reassignment, record storage, copying,
nonconsuming matching and block-bearing function results remain excluded. Returning
a block-bearing outcome is rejected by its type even if a particular unit variant
could contain no block. Initially block-bearing outcomes are local to the region's
function; they cannot themselves be parameters. Ordinary scalar outcomes retain
the implemented transfer/return rules.

A function accepting an owned `Block` must have a scalar, scalar-record or
non-block-bearing outcome result, and must prove release of its block parameters
on every normal return. Delegation to another function with the same checked
consume-and-release contract is allowed. The caller's region remains stable while
that synchronous call runs. Since no block-bearing result can return and there is
no global storage, a block cannot outlive its origin through that call. Borrowed
`&Block`/`&mut Block` parameters use the existing nonescaping call-scoped loan rules;
borrowed parameters cannot release their owner. An exclusive loan requires a
mutable owner or an exclusive parameter. Moving a selected payload with
`let mut writable = block` permits byte mutation while preserving its origin and
linear obligation; whole-value reassignment remains forbidden. No thread/task
transfer is granted.

The checker needs region provenance in addition to the current moved-binding set.
At continuing joins, live/released child obligations and occupied/free region state
must agree. Each returning branch discharges all resource obligations before it is
excluded from a join. Optional `&&`/`||` calls cannot be the only release path.
Preserve the exact provenance across constructor, match payload and owner moves;
do not infer release merely because a binding has become unavailable.

A region may exit only when it has no outstanding reservation outcome, block owner
or active loan. Every early scalar/typed return from its scope enforces this rule.
Leaving the scope releases its supplied local storage lifetime; no hidden destructor
runs. Callees are checked independently, so a scalar return from an owning-block
callee implies fulfillment of the consume-and-release contract on that path.

## Failure injection and independent acceptance

Use a trusted test build that can fail after slot reservation and before each byte
initialization/owner-publication step. Such injected exhaustion must roll back the
reserved slot before returning `Exhausted`, with no published owner and no live
ledger entry. Production zero filling has no ordinary fallible operation; the test
hook exercises rollback and must not become a source-accessible control or hidden
production allocation. Archive the selected test-build controls separately.

The independent C driver owns a ledger recording origin, requested size/alignment,
owner publication, release and slot reuse. It observes exact requests/releases,
checks storage bounds/alignment, sentinel bytes outside the visible range, zero
initialization and byte-write/read behavior. It must not derive expected behavior
from the compiler's emitted bookkeeping. After each complete normal/typed-error
workload, require an empty ledger and free occupancy. Nonsaturated origins must
be reusable; the saturation fixture instead requires permanent instance exhaustion
without a live allocation. Intermediate published
owners legitimately leave one live entry until their caller releases them.

Required cases include all invalid sizes/alignments, every boundary index and byte
value, exhaustion, each injected failure point, moves, rewrapping/consuming outcomes,
live-origin metadata mismatch probes, stale owner copies after same-request
slot reuse, instance-counter saturation, borrowed read/write alias conflicts,
double release, early returns, continuing joins, delegation and attempted
function/scope escape. Reject static violations through the shared CLI/context/LSP path and
independent native checker. Run valid drivers under ASan/UBSan at O0/O2 on actual
Linux x86-64/ARM64 hosts and report local limitations separately. Sanitizers do not
replace provenance checking or the ledger.

## Agent, cost and development contracts

Version the new context/interface schemas and explicitly record opaque linear
payloads, per-origin obligations, owning-parameter consume-and-release effects,
borrow scopes, capacity/alignment bounds and supported typed failures. Exact source
and complete applicable contracts must invalidate affected callers when a resource
contract changes. Ordinary M1, outcome-only, module, C export, edit/reuse/watch and
native receipt profiles must not silently inherit these operations.

Record selected C layout, frame/descriptor capacity, initialization work, storage
retained until region exit, allocation/release counts, actual binary/stack/peak bytes
where measurable, and reserve/release latency with compiler settings and hardware.
Count both 64-bit instance fields and their target padding, as well as the whole
region's reserved capacity, including inaccessible bytes, instead
of labelling an 8-byte owner an 8-byte total cost. Separate trusted fault/ledger test
instrumentation from production measurements. No numbers are claimed in this draft.

Initial development requires full check/build/restart. Layout or origin-provenance
changes cannot reuse a previous checked interface or reload a live block. Module
composition, C ownership exports, heap storage, containers, dynamic region capacities,
multiple slots, automatic cleanup and concurrency require separate proposals.

## Alternatives and next step

A stable separately owned allocator handle could support returned owners but would
add descriptor ownership and potentially additional allocation/counting costs.
Defer it until returned dynamic resources are required. General lifetime annotations
would widen the grammar and proof model before this single-slot workload needs them.
An ordinary `&mut` allocator argument is insufficient because its existing loan ends
at the call. A mandatory process-global allocator would hide supply and target costs.

Before implementing, fix the exact opaque C descriptor/owner representation and
region-aware frontend state/diagnostics in an implementation proposal, with bounded
source tests and ledger fixtures. Then implement the sequential supplied-block gate.
This draft chooses the initial lifetime approach; it supplies no allocation execution
evidence and does not complete M2's resource or concurrency milestones.
