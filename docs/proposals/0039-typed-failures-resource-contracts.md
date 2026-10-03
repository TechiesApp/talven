# Proposal 0039: Typed failures before allocator-backed resources

- Status: Draft; semantic design only, no new compiler/runtime support
- Requirements affected: R01, R08, R10, R11, R16, R18, R24, R25
- Decisions affected: D67 (proposed), D06, D07, D24, D27, D28

Implementation follow-up: [Proposal 0040](0040-concrete-typed-outcomes.md) now
implements the bounded typed-outcome slice. Allocation, cleanup and concurrency
contracts in this document remain design-only.

[Proposal 0041](0041-supplied-storage-regions.md) chooses a candidate stable lexical
region approach for one sequential supplied-storage byte block. It specifies linear
release/delegation, instance identity and fault/ledger gates, without implementing
allocation or permitting block-bearing function results.

## Problem

The current profiles check scalar arithmetic and call-scoped record loans, but
trap on arithmetic failure and provide neither recoverable sum types nor owned
heap resources. Adding containers first would force accidental choices about OOM,
partially initialized objects and cleanup. Starting tasks first would also leave
cancellation and resource lifetimes undefined.

This proposal orders M2 implementation around independently testable contracts.
It adopts no new source grammar, generic type system, allocator ABI or executor.
The [implemented core reference](../language-reference.md),
[borrowing rules](../borrowing.md) and [module profile](../modules.md) remain authoritative.

## First implementation slice: concrete typed outcomes

Design and implement nominal, finite tagged alternatives with explicit concrete
payload types before adding allocator-backed values. Initially admit scalar and
existing owned-record payloads; reject reference payloads and nested/generic sums
until their layout, move and parser bounds are separately specified. A declaration
names every variant; a function's explicit result type names the outcome it returns.
An error variant is ordinary typed data, not a hidden nonlocal jump or exception.

Choose one constructor and exhaustive branch syntax in a follow-up implementation
proposal. Every reachable variant must be handled exactly once; duplicate and
missing alternatives fail checking. The tag is checked before payload extraction;
there is no nullable or unchecked payload access. Variant payload bindings have
the same copy/move rules as their payload types. Moving an outcome invalidates its
old binding even when its runtime variant has a copyable payload.

In the first slice, exhaustive branching consumes its owned scrutinee. The old
outcome binding becomes unavailable on all continuing paths. Only the selected
variant's payload is initialized: scalar fields can be copied into branch bindings,
and a record payload transfers once into its owned branch binding. Reusing the
outcome or extracting its moved payload again fails ownership checking. The
implementation proposal must define the exact binding syntax and control-flow
join rules; borrowed/nonconsuming matching remains excluded.

For a deliberately small first slice, outcome parameters/locals are owned values;
outcome borrowing, whole-value reassignment, reference storage, user cleanup hooks,
implicit conversions and propagation shorthand remain excluded. Branch analysis
retains the current conservative ownership join on every continuing path. Returning
an outcome transfers it to the caller. A discarded recoverable outcome must produce
a diagnostic; precisely define whether a retained but uninspected binding is also
rejected before describing this as complete must-handle enforcement.

Checked arithmetic continues to trap in existing profiles. Recoverable arithmetic
requires separately named operations returning explicit outcomes; a typed result
must not silently catch a process trap, foreign exception or future cancellation.
An adapter reports documented domain failures without conflating them with compiler
errors. No unwind or catch boundary is implied.

### Verification gate

Implement one shared semantic path for CLI, context and LSP; record nominal outcome
identity and alternatives in versioned interfaces. Match reference/native checking
and emission under an explicitly selected new profile. Preserve existing profiles.
Use independent C drivers for each variant and exhaustive control flow, payload
moves and continuing-branch joins. Test missing/duplicate variants, wrong payload
types, extraction without a checked branch and ignored outcomes. Run sanitizers
at O0/O2 and report actual Linux x86-64/ARM64 execution. Do not treat syntax-only
formatter acceptance as proof of type or error-path correctness.

## Second slice: allocator and ownership contracts

Only after typed outcomes, specify one bounded sequential allocator experiment.
Start with an owned byte block or one concrete container over supplied storage;
defer general containers and sharing. An allocator is explicitly selected by the
caller, with no implicit global fallback or mandatory heap in the base core.

| Obligation | Required contract before implementation |
| --- | --- |
| Request | Checked size/capacity arithmetic, alignment validity, maximum request and zero-size behavior |
| Failure | Distinguish exhaustion, invalid request and other supported failures using concrete typed outcomes |
| Ownership | A successful allocation has exactly one owner; moves transfer its release obligation |
| Lifetime | Storage and allocator state remain alive and stable until every dependent owner has released |
| Access | Bounds and initialization are checked; aliases obey shared/exclusive rules |
| Release | Return memory to the originating allocator with the exact required size/alignment; no double release |
| Initialization | On failure, destroy only successfully initialized elements and release acquired storage |
| Effects | Public contracts identify allocation/release, maximum bounds where known and possible failure types |

The existing loan model cannot express an owner that outlives the allocator call.
Do not reinterpret `escapes:false` as permission to retain its pointer. Before
returning allocated owners, choose and validate a concrete lifetime representation:
lexically tied allocator regions or a separately owned stable allocator handle.
Explain whether allocator movement is forbidden while owners exist, or how handle
stability is preserved, including every counter/allocation cost. This remains an
open design choice, not a claim that omitting lifetime syntax solves the problem.

Define cleanup order for normal returns and typed error returns. Each ownership
obligation must be released or transferred exactly once on every returning path;
returning an owner transfers its live allocation and release obligation to the
caller. Early implementation can require
explicit checked release; automatic release needs a dedicated elaboration and
validation design. User-defined destructors, cleanup that fails/blocks, panic
unwinding and partially moved aggregate resources remain separate. A trap terminates
execution; do not promise language cleanup or safe in-process recovery after it.

A no-heap target rejects allocator-requiring operations unless it selects an
explicit supplied-storage allocator experiment. Allocation profiles expose
capacity/metadata and dependency costs. No benchmark may label hidden bookkeeping,
retained arena capacity or an executor's storage as zero cost.

### Resource verification gate

Use deterministic fault injection at every allocation/initialization step, a
counting allocator and an independent live-allocation ledger. Cover exhaustion,
invalid alignment, capacity overflow, moves, wrong-allocator release, partial
initialization and every typed return path. Require no live entries after each
complete test workload's normal or error completion, including callers releasing
returned owners; intermediate successful allocation returns legitimately leave
transferred entries live. Reject use/double release statically where representable.
Sanitizer evidence complements rather than replaces the ledger and type checks.
Measure selected binary size, allocations/metadata, retained and peak bytes, and
allocation/release latency on a declared target and workload.

## Concurrency boundary

This sequential experiment grants no thread transfer, cross-suspension borrow,
detached operation, callback or GPU lifetime permission. Cancellation is not an
arbitrary exception injected while a resource is borrowed. Before concurrency,
specify its memory model, task owner/scope, cancellation observation points,
quiescence before release, bounded work queues and allowed transfer/shared types.
An optional executor must have explicit storage and scheduling costs.

## Agent context and development tools

Public failure alternatives and allocator obligations are dependency contracts,
not comments agents may omit. Version their receipt schemas and invalidate callers
when an applicable contract changes. Exact source remains authoritative. An edit
preview must check the entire candidate and relevant resource/error paths before
reporting frontend validity; a valid preview is not execution evidence.

Outcome layout and allocator/lifetime changes initially require development
restart. Do not hot-reload live resources under an incompatible owner, tag, layout
or cleanup implementation. General module reuse/reload remains separate work.

## Alternatives and next step

Exceptions/unwinding would introduce cleanup and foreign-boundary obligations
before the core has resources. Global allocators would hide target and cost
selection. A universal reference count would add sharing/cycle obligations to
every resource. Defer these mechanisms until a concrete workload needs them.

The next implementation proposal should fix bounded concrete-outcome grammar,
layout, must-handle rules, diagnostics, lowering and tool schemas, then implement
the typed-outcome verification gate. Allocator-backed containers and concurrency
must follow their own verified lifetime designs. This document begins M2 planning;
it does not pass the M2 resource-lifetime milestone gate.
