# Proposal 0027: Current call type contracts for persistent checking

- Status: Draft; implemented opt-in reference experiment
- Author(s): Talven contributors
- Requirements affected: R01, R08, R10, R24, R25
- Decisions affected: D44, D55 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem and scope

The [persistent checker](0016-persistent-function-checking.md) includes parameter names in direct-callee dependency signatures because cached reference descriptions expose those names. Positional call validation uses parameter count/types, borrow modes and result type. Rechecking unchanged callers for a parameter rename is conservative work; dropping names without refreshing descriptions would expose stale editor/context facts.

## Proposal

Add explicit `IncrementalFrontend(call_type_contracts=True)` and `dev --incremental-check --call-type-contracts`. Keep the existing default signature identity and full-check modes. The option cannot accompany native object mode: check reuse and object reuse remain separate experiments.

Use ordered exact parameter-type spellings and result type for direct-function dependencies in the selected mode. Exact own function source remains mandatory, including own parameter names/body. Fresh parsing and declaration validation remain; record schemas and missing/type/borrow/arity dependencies still invalidate. Reconstruct every cached function-reference description from the current callee declaration as well as remapping its current definition span. No old displayed signature or mutable AST is returned. Invalid revisions retain only last-successful facts, current first diagnostics and existing compiler/source bounds.

Add selected mode to session/measurement receipts. Current context, references, signatures and full generated C must match fresh analysis across repeated parameter renames, declaration shifts/reordering, recursion, borrowed parameters, changed arity/types/modes/results and invalid/repair sequences. The current language has positional direct calls; named arguments, default parameters, effects or other future rules would require revisiting this dependency contract.

## Evaluation and limits

Verify complete analysis equality, current spans/descriptions, deterministic context and byte-identical ordinary C against full checking; execute a real check-reuse watcher and inspect current output/work receipts. Preserve default tests and sanitizer/native suites. Extend the correctness-gated checking measurement runner with an explicit option; retain comparative timings before claiming latency or task-cost improvements. Parsing and native C builds remain full; this adds no module system, object reuse, hot reload, authenticated cache or new target support.

[Three paired local comparisons](../call-contracts-evidence.md) retain current native-accepted workloads, exact complete analysis/context/C and 2,016 samples including warmups. Recheck counts improve for parameter renames; timings remain mixed and defaults remain unchanged.
