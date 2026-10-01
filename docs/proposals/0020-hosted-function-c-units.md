# Proposal 0020: Hosted function C units

- Status: Draft; implemented reference lowering experiment
- Author(s): Talven contributors
- Requirements affected: R08, R12, R24, R25
- Decisions affected: D22, D38, D48 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

Persistent checking still generates and compiles one complete C translation unit. Before adding native object reuse, the backend needs a defined function-unit boundary whose generated text stays stable after unrelated body edits. The current whole-program temporary counter makes later function text depend on earlier bodies.

## Proposal

Add opt-in `emit-c-units SOURCE [--console]`, returning `talven.c-units.v1` JSON for the experimental `hosted-c11-units-v1` emission profile. The ordinary shared frontend fully validates source; hosted main and console requirements remain identical to `emit-c`. The command emits text only and never invokes a compiler, linker or program.

Emit one unit per function, in declaration order, with ID `fn:NAME`, then a separate `entry` unit defining the C entry wrapper. Each function definition appears exactly once. Every unit repeats all current record layouts and function declarations, preserving a conservative global contract boundary. Arithmetic helpers and optional console definitions occur only in units that reference them. Each function's emitter starts its temporary/text counter at zero. A source function named `entry` has the distinct ID `fn:entry`.

Factor header/contracts, function lowering and helper insertion from the ordinary emitter. Full single-unit emission retains its exact bytes and global counter; expression evaluation order, scalar snapshots, checked arithmetic, record moves, call-scoped loans and static text storage remain shared. Unit emission does not expose an unchecked parsing path.

All objects in a resulting program must be compiled for the same target, C mode, toolchain configuration and compatible ABI options. Repeated record and static-text-view declarations use identical types/member names/order. The primary [N1570 C11 committee draft](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf), section 6.2.7, describes cross-translation-unit type compatibility; this is a committee draft, not a claim of general foreign ABI compatibility. Internal object interoperability is tested on declared native hosts.

Receipts identify exact source, compiler checkout, language/emission profiles, selected console option, unit IDs and SHA-256 hashes of each C text. These are byte identities, not authenticated build evidence or safe cache keys. Limit this experiment to 256 functions plus entry, 16 MiB total C text and 16 MiB final compact receipt. Emit no partial successful result on failure. Existing source/token/depth limits remain. No file-writing option is added.

## Invalidation boundary

Whitespace/comments and unrelated function-body edits leave other function-unit bytes unchanged when global declarations stay identical. All record/function declarations appear in every unit, so signature, parameter-name, record-layout and declaration-order changes conservatively affect every unit. A body changing its selected arithmetic/console helpers affects that unit. The entry wrapper does not depend on body temporary counts.

This is an emission boundary, not object caching. Later reuse must separately pin exact generated/preprocessed input, compiler/schema versions, target/options, toolchain and headers, environment assumptions, object integrity, dependency changes and publication freshness. A C-text hash alone is insufficient. Invalid source cannot reuse an old analysis. Reuse must preserve independent native acceptance and process-restart rules.

## Alternatives considered

- Slice the existing C by string matching: risks function boundaries and incidental formatting; use shared structured lowering.
- Reset counters in ordinary emission too: needlessly changes reference/native byte identity. Keep the new behavior within the explicit unit experiment.
- Share one mutable output header file: adds file lifetime/revision coordination before object reuse is designed; repeat current contracts in each receipt unit.
- Cache objects immediately by source hash: omits headers, toolchain state and object integrity. Define and verify units first.

## Costs and implications

- Agent interfaces: deterministic unit IDs/text help inspect affected work; no model/token/dollar improvement is measured.
- Compiler/runtime: repeated declarations and separate C processes can increase output/build cost and inhibit cross-function optimization without LTO. No compilation speedup, binary-size or memory saving is claimed.
- Safety: full current analysis and existing lowering remain authoritative. Separate objects preserve direct native calls; no loader, dispatch, new borrow lifetime or runtime loan registry is added.
- Targets: hosted C11 experiment with existing Linux ARM64/x86-64 CI; no freestanding units, new target, package ABI or native Rust unit-emission parity.
- Trust: compiler output remains data. Receipts do not authenticate a compiler or grant process/file/resource access. Resource bounds are not OS quotas.

## Evaluation

Require ordinary output equality against the native compiler on the existing 840-case corpus. Compile every unit independently with C11 warnings as errors and no LTO; link and verify complete integer values, forward calls/recursion, record results, scalar mutation, checked traps/short-circuit, exact UTF-8/NUL/order output and static text views across functions. Exercise all three borrow/order/reborrow fixtures at `-O0` and `-O2` with ASan/UBSan. Test stable unrelated units, conservative global changes, helper/console selection, deterministic source/code receipts, output limits, invalid sources and absence of external execution. Run the full reference suite and documentation checks.

## Unresolved questions

Preprocessing/header identity, toolchain pinning, artifact storage/integrity, object-cache bounds and eviction, development cancellation/publication, linking, representative build/rebuild cost and finer contract dependencies remain separate work. Design acceptance is separate from this lowering experiment.
