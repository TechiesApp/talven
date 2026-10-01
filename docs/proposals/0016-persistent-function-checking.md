# Proposal 0016: Persistent function checking

- Status: Draft; implemented opt-in reference-frontend experiment
- Author(s): Talven contributors
- Requirements affected: R01, R08, R10, R24, R25
- Decisions affected: D38 (partial implementation), D44 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

The single-file development watcher repeats every function check after each edit. Agents and humans editing one helper receive no reuse of unaffected semantic work. A reusable checker must also avoid stale diagnostics, source locations, and ownership decisions when declarations change or an invalid edit is repaired.

## Proposal

Add a session-local `IncrementalFrontend` using the shared reference checker and an opt-in `talven dev --incremental-check` mode. Parse each exact source revision afresh and validate every global declaration. Reuse a successful function check only when its exact declaration text, directly called function signatures, and referenced record schemas match. Parameter names participate in signatures because compiler context and editor reference descriptions expose them.

Store immutable expression-type, direct-call and reference facts for only the last successful revision. Reconstruct references against current declaration positions and function-relative local positions. Return a fresh current `Analysis`; do not retain or return an earlier revision's mutable AST. Removed functions leave the cache after a successful revision. Invalid revisions report the same current first diagnostic as full analysis and never publish partial cache changes. Existing source and tree limits remain mandatory on warm revisions.

Pin the session's compiler identity to exact compiler-file hashes. A changed identity rejects analysis with `E0501` and requires a session restart. This is invalidation, not authentication or permission to modify compiler inputs.

The watcher still emits the whole current C translation unit, compiles it in full, and restarts the process. Add `frontend_mode` to session receipts and a `checked` event with function-name lists `checked` and `reused`. Preserve `build_mode: full` for C builds. Reuse can precede a failed or superseded native build; receipts identify those later events separately.

This increment implements function-check reuse within the persistent-compilation stage of Proposal 0010. Incremental parsing, native compiler reuse, C object caching, modules, multi-file dependency tracking, state-preserving hot reload, and broader tooling integration remain open. The default development mode remains full checking.

## Examples

This command is implemented:

~~~sh
python3 -m talven dev examples/hello.tal --console --incremental-check
~~~

Changing only a helper body rechecks that helper and can reuse callers with unchanged dependency contracts. Changing its parameter type rechecks its callers. Moving an otherwise unchanged declaration updates source references while reusing its check. Each successful candidate still produces a fresh native executable and starts from initialization.

## Alternatives considered

- Cache complete `Analysis` objects: leaves mutable AST sharing and obsolete reference locations across revisions.
- Reuse by function source alone: misses changed callee contracts and record layouts.
- Invalidate all transitive callers for every body edit: necessary for some compiled-artifact caches, but unnecessary for this checker's signature-based call validation. Generated C is always refreshed here.
- Cache native objects or introduce an incremental parser first: larger backend/parser contracts; neither is required to isolate and verify semantic reuse.

## Costs and implications

- Agent context: current context and diagnostics retain existing schemas and semantic profiles. Receipts explicitly distinguish frontend reuse from full native rebuilding.
- Runtime and memory: cache facts are bounded to one successful source revision, with current parsing and declaration checking still performed. Generated programs gain no cache or reload runtime.
- Security: cache data stays in the current process; there is no disk-cache deserialization, untrusted cache acceptance, or new execution authority.
- Targets: reference analysis is host independent; watcher execution retains its POSIX/C11 boundary and declared Linux CI hosts.
- Ecosystem and interoperability: no foreign ABI, package, or language syntax change.

## Evaluation

Compare complete analyses, reference spans/descriptions, deterministic context and byte-identical emitted C against full checking through edit sequences. Test body edits, changed signatures and record schemas, added/removed declarations, source movement, compiler changes, invalid-edit recovery, input limits, and mutation of previously returned results. Execute a real development session and inspect both cache receipts and changed program output. Run the full reference suite and native differential suite.

Correctness tests establish reuse behavior; they do not establish a latency or memory improvement. The [persistent-checking baseline](../incremental-checking-baseline.md) retains source revisions and edits, compiler identity, hardware, Python/C versions, flags, full/reuse condition order, repetitions, failed attempts, current-output correctness and raw timings. Memory and end-to-end development feedback remain separate measurements.

## Unresolved questions

Representative measurement, native/tooling integration, declaration-level dependencies, bounded cache accounting, C artifact reuse and hot-reload state contracts remain separate work. Acceptance of this proposal remains separate from its experimental implementation.

The explicit [current call type contract option](../call-type-contracts.md) allows parameter-name changes to preserve caller checks while rebuilding displayed signatures from current declarations. Default signature identities remain unchanged; full current parsing and native rebuilding still apply.
