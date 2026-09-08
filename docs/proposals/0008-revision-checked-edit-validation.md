# Proposal 0008: Revision-checked edit validation

- Status: Draft
- Author(s): Talven contributors
- Requirements affected: R01, R03, R04, R05, R08, R12
- Decisions affected: D04, D24, new D33
- Discussion: Pull request introducing this proposal

## Problem

An agent can obtain checked context and submit a complete replacement to the evaluation harness, but ordinary compiler tooling has no revision-bound candidate preview. Checking a replacement alone does not identify its base revision or explain changed declarations. Invalid source also cannot produce normal semantic context, despite being a common starting point for repairs.

## Proposal

Provide two read-only operations through `talven edit`. `snapshot` returns exact source/compiler identities even for invalid source, with raw source available only by explicit opt-in. `validate` checks a complete candidate against required source/compiler hashes, analyzes both snapshots through the existing frontend, and returns structured diagnostics and a bounded declaration/direct-call comparison.

The [guide](../edit-validation.md) defines the commands, receipt schemas, error codes, budgets and field meanings. The two schemas are `talven.edit-snapshot.v1` and `talven.edit-validation.v1`. Snapshots perform no semantic validation. A candidate is accepted by the preview only when revision guards, observed freshness, output budget, and frontend checks pass. A broken base may be repaired successfully; its diagnostics remain available and its declaration comparison is null.

Compare function parameters, return types and borrowing contracts, record fields, added/removed declarations, and changed direct-call sets. Reuse existing compiler facts, preserve significant parameter/field order, and sort output deterministically. Do not infer renames, behavioral equivalence, ABI compatibility, transitive impact or complete effects. A body-only change can leave the declaration comparison empty while changing the source hash.

No source application is performed. Re-reading inputs catches observed concurrent changes, but does not lock a file or establish atomic compare-and-swap. A protected applying host would need to check the exact candidate and current source/compiler identities within its own writer-coordination boundary. A successful preview cannot authorize a later write or replace independent task acceptance.

## Examples

The [guide's repair example](../edit-validation.md#preview-a-repair) snapshots the existing invalid type fixture and validates a separately stored candidate. It leaves the original file unchanged. The commands use the implemented prototype interface; the future applying-host workflow remains a proposal.

## Alternatives considered

- Using `check` alone validates the candidate but supplies neither an expected base/compiler guard nor a declaration comparison.
- Requiring a valid base would prevent the tool from handling syntax, type and borrowing repairs.
- Replacing source after a final hash check would retain a race with other writers; an atomic rename alone is not compare-and-swap.
- A patch/range protocol would need explicit offset, overlap and encoding rules. Complete candidate files keep this first contract compatible with the existing evaluation harness.
- A multi-file transaction or LSP apply extension requires broader workspace/version semantics and independent writer coordination.

## Costs and implications

- Agent context: two revision hashes and explicit candidate content; byte budgets include the complete receipt. No tokenizer or token-saving claim is made.
- Runtime and memory: bounded source reads and up to two frontend analyses; no generated-program or runtime change. Analysis latency and memory are unmeasured.
- Security: inputs, compiler and filesystem remain trusted. Hashes identify bytes without authenticating them; no sandbox, release authority or concurrent-write guarantee is added.
- Targets: frontend-only previews need no C compiler and declare no native target compatibility. Existing native tests retain their own target requirements.
- Interoperability: existing CLI, context v2, LSP, formatter, evaluation protocols and acceptance rules retain their behavior. Adding compiler tooling changes its aggregate hash and invalidates old pinned context/archive identities normally.

## Evaluation

Verify exact source hashes, invalid-source snapshots, valid repairs, candidate diagnostics, stale-source/compiler rejection, input/output limits, deterministic declaration comparisons and read-only behavior. Inject source/candidate/compiler changes during validation and verify controlled rejection without overwriting current bytes. Preserve existing tests and independent acceptance rules.

Independently execute a valid borrowing repair and reject a type-valid but behaviorally wrong candidate at both optimization levels. Both candidates should pass the frontend preview; only the correct one should pass the task's native oracle. Run full native conformance, offline fixtures/reverification, sanitizer/freestanding regressions, formatting and documentation checks, and report only completed measurements.

The [validation evidence](../edit-validation-evidence.md) records actual tests, input/toolchain identities and remaining unmeasured claims.

## Unresolved questions

Atomic file application, cooperating versus arbitrary writers, multi-file snapshots, patch offsets, public effect/ABI information, dependency impact, LSP integration, controlled model effectiveness, and the applying host's protected policy remain open.
