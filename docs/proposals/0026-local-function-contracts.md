# Proposal 0026: Opt-in local function contracts for hosted units

- Status: Draft; implemented opt-in reference experiment
- Author(s): Talven contributors
- Requirements affected: R08, R12, R24, R25
- Decisions affected: D48, D49, D50, D53, D54 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

Every existing hosted function unit repeats every source function declaration. Parameter-name, unrelated function-signature and declaration-order edits therefore invalidate all objects. The retained [rebuild](../object-rebuild-evidence.md) and [watcher](../native-watch-evidence.md) observations show high native global-change costs. Shorter [polling candidates](../watch-polling-evidence.md) did not establish a better default. Refine actual generated dependency boundaries separately, with native correctness evidence.

## Proposal

Add explicit `--local-contracts` to hosted unit emission/preparation and to opt-in native watch mode. The watch flag requires `--incremental-build --stable-toolchain`; it cannot apply to ordinary full/check-reuse mode. Add a matching private `UnitBuildSession(local_contracts=True)` option. Keep ordinary full C and all existing default experimental profiles unchanged.

Use new emission/preparation/object profiles `hosted-c11-local-contracts-v1`, `hosted-preprocessed-local-contracts-v1` and `hosted-object-local-contracts-v1`, with existing bounded receipt schemas. Profile/configuration identities separate eligibility from legacy global-contract objects.

Each unit retains all current record/static-text layouts and required headers. Its function declarations include the current function plus source-function callees from the current checked direct-call graph, sorted by name; the entry unit declares main. Prototype parameters carry their exact C types/borrow qualifiers without names, while definitions keep named bindings and shared checked lowering. The [N1570 C11 committee draft](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf), 6.7.6.3, permits optional identifiers in prototype parameter lists and specifies function-type compatibility; this is draft guidance, not general foreign ABI or target support.

For one fresh preprocessing pass, common headers/layouts precede the shared boundary; selected prototypes live inside each function segment before its definition/helpers. Normalize own line markers only after preprocessing, preserve system markers and existing boundaries, and fully check current source before invoking the driver. Existing console/entry rules, unit/input/output/artifact limits, fixed flags, aggregate timeouts, integrity checks, fresh linking, last-successful retention, cancellation and publication freshness remain.

## Invalidation and limits

Renaming a callee parameter changes its definition unit, while a caller whose ABI declaration/body is unchanged can remain eligible. Changing a signature's types affects that definition and direct callers; caller bodies and further dependencies can also change. Added/removed/reordered unrelated functions need not change existing selected prototypes; every current function still gets an object and fresh linking. Record layouts remain global and conservatively invalidate all units. Header/macro/console dependencies remain represented by expanded bytes. No transitive call-graph, ABI-only hash, stale analysis or unchecked object is substituted for current lowered/preprocessed input.

This remains a single checked source module with explicit stable-toolchain assumptions. There is no import resolver, FFI, shared persistent cache, record-layout refinement, runtime loader, readiness or state-preserving reload. Omitted C parameter identifiers do not remove current source parameter names from language checks, context or editor signatures.

## Evaluation

Require unchanged ordinary C bytes and legacy profile behavior. Verify strict separate C units and fresh prepared units, recursion/forward calls, parameter-name and signature edits, declaration insertion/reordering, global record changes and missing/invalid calls. Execute actual reused objects against independent integer/owner oracles; verify profile separation, invalid-edit/repair retention, pollable cancellation and native watch output/work decisions. Preserve sanitizer coverage and enforce Linux native evidence without skips. Retain fresh comparative measurements before claiming latency, memory or task-cost improvement or changing defaults.

[Three same-checkout paired comparisons](../local-contracts-evidence.md) retain actual native acceptance and reduced parameter-rename invalidation, with mixed cold/other edit costs. Existing defaults remain unchanged.
