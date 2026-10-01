# Proposal 0028: Exact function-body syntax reuse

- Status: Draft; implemented opt-in reference experiment
- Author(s): Talven contributors
- Requirements affected: R01, R08, R10, R24, R25
- Decisions affected: D44, D55, D56 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Scope

The persistent frontend still parses every body on every revision. Add explicit `IncrementalFrontend(reuse_body_syntax=True)` and `dev --incremental-check --reuse-body-syntax`, independently of the current call type contract option. Keep full/default persistent parsing and native rebuilding unchanged. This is single-file body syntax reuse, not incremental tokenization or an editor recovery parser.

## Contract

Lex the whole exact current source using the shared lexer and its byte/token/text/control-character rules. Parse record/function headers afresh with the shared parser. For a top-level function body, reuse only an exact current source-text match to a body from the last semantically successful revision, under pinned compiler inputs. Verify the current closing-token boundary/count. Otherwise run ordinary body parsing. Check the complete reconstructed current AST against the shared depth limits every time.

Store immutable grammar facts, including tokens/spans, statement order, branches, mutation/assignment structure, literal values and child indices. Reconstruct fresh mutable AST/list objects, translating immutable positions to the current body origin and clearing expression types. Keep current header names/types/spans. Successful semantic checking separately governs its own exact-source/dependency cache; body syntax never substitutes for current type/borrow validation. Promote syntax facts only with a completely successful analysis, drop removed functions, preserve the previous successful cache on any lexical/syntax/semantic failure, and reject compiler drift.

Use a small default-preserving parser hook for top-level bodies; retain one grammar and lexer for CLI/context/LSP. Recovery parsing remains unchanged. Syntax work lists distinguish parsed/reused bodies from checked/reused semantic functions. Current source/depth limits bound each retained generation; no external cache input or mutable returned AST seeds reuse.

## Evaluation

Compare complete program/analysis, exact current first diagnostics, context and emitted C with ordinary parsing/checking. Cover source/header/body edits, Unicode/CRLF movement, declaration reorder/removal, repeated invalid/repair, caller mutation, recursion, text escapes, stores/branches/record literals, boundary/token/nesting/depth limits and compiler drift. Execute real check-reuse watcher revisions and native acceptance. Extend the correctness-gated checking measurement with explicit selection and retain full/default-persistent controls before claiming latency, memory or task-cost improvement. No module system, native object combination, state preservation, new syntax or target support is added.

[Three paired local comparisons](../body-syntax-evidence.md) retain native-accepted workloads, current complete analysis/context/C and 2,016 samples including warmups. Warm edit and initial/invalid/schema costs remain mixed; default parsing stays unchanged.
