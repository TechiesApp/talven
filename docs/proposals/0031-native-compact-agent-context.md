# Proposal 0031: Native compact agent context

- Status: Implemented native experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R01, R05, R06, R12, R24
- Decisions affected: D59 (proposed), D41
- Discussion: the pull request introducing this proposal and implementation

## Problem and contract

The Rust experiment checks the reference's current bounded language but lacks its agent-facing compact program index. Port this existing view before selecting a production compiler or broadening runtime features. Keep the Python reference, full context API and independent native acceptance.

Add `talven-native context SOURCE --compact [--json]` and library `agent_context(&Program)`. Read source through the existing bounded regular-file UTF-8 path and perform complete native analysis before emitting facts. Successful output is byte-identical to the reference's `context --compact`: a `talven.agent-context.v2` JSON object with sorted `functions`, sorted `records` and `schema` keys, compact separators and one final newline. Function signatures retain parameter names, order and borrow modes; record descriptions retain field order and the existing by-value move reminder. Empty programs are valid. Checking does not require an executable entry point or console selection.

Invalid programs produce no facts. Report the first error through the existing native diagnostic envelope automatically, matching reference context error behavior; optional `--json` is accepted consistently with native check and does not change context output. Require exactly one `--compact`, allow at most one `--json`, and reject all other options before source I/O. Unsupported full-context options are not silently ignored.

## Alternatives and boundaries

Delegating to Python would keep one serializer but lose a standalone native agent tool. Implementing full context v2 now would also require source/compiler identities, symbol selection, reference/caller/dependency records, body spans, target contracts and output budgets; sharing its schema before those facts exist would misrepresent parity. A new native-only compact schema would force consumers to translate equivalent facts. Reusing the existing compact schema with differential checking is the bounded choice.

There is no source application, program execution, native build, shell invocation, model-provider call, stored cache or language change. The index does not carry source/compiler hashes, revision guards, symbol selection, original source or the full context's byte budget. Output is derived from declarations within the shared input/token/depth limits; no independent output-budget flag is introduced. It cannot serve as an authenticated or revision-bound cache record. Source comments and text literals remain data and do not enter this declaration-only index.

The compiler uses its existing Rust heap and standard library to sort references and construct strings. Emitted Talven programs gain no allocation or runtime dependency. No speed, memory, token-cost or production-toolchain claim follows from this port; future context measurements must retain inputs, exact native/reference compiler identities and correctness criteria.

## Verification

The [native guide](../../experiments/native-compiler/README.md#compact-agent-context) documents usage and limitations. Rust unit tests and independent CLI fixtures check exact bytes, sorting, parameter/field order, scalar/text types, record results, value moves, shared/exclusive borrows, empty programs and programs without `main` that call `print`. CLI tests reject malformed/duplicate/unsupported flags, invalid UTF-8, oversized input, syntax/type/move errors, missing files and FIFOs; structured failures contain diagnostics rather than facts.

The [differential corpus](../../experiments/native-compiler/tests/differential.py) compares compact context for every existing case, including generated valid programs and token mutations. Accepted outputs must match byte for byte; rejected programs must agree on failure and the first diagnostic's code/message/severity/UTF-16 range except the existing invalid-UTF-8 host-message allowance. Native failures retain their independent implementation profile/source markers and must contain no program facts. Existing native emission, independent runtime oracles, ASan/UBSan borrowing checks, reference tests and CI target checks remain required. This evidence does not establish general equivalence for all inputs or complete the live-agent M1 gate.
