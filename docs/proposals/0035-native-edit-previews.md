# Proposal 0035: Native read-only edit previews

- Status: Implemented native experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R01, R05, R08, R12, R24
- Decisions affected: D63 (proposed), D33, D41, D62
- Discussion: the pull request introducing this proposal and implementation

## Problem

Native agents need source identities for invalid programs and a revision-bound preview of complete repairs. The reference implements this through read-only snapshots and candidate validation. Port that behavior using the native frontend and its embedded identity, retaining independent acceptance and external writer coordination.

## Contract

`talven-native edit snapshot SOURCE [--include-source] [--max-bytes N]` emits `talven.native-edit-snapshot.v1`. Read bounded regular-file UTF-8 source without analysis, identify its exact bytes, reread it and reject any observed content difference or read failure. Return `ok`, `validation: not-run`, `source_hash`, `compiler_hash`, native/language profiles, `source_bytes`, and `diagnostics`. Optional source echo is labeled `untrusted_source_text` and withheld on failure. Invalid language syntax is valid snapshot input. Use the same embedded compiler identity as [native focused context](0034-native-focused-context.md), with the new input/edit modules included.

`talven-native edit validate SOURCE --candidate FILE --expect-source-hash HASH --expect-compiler-hash HASH [--max-bytes N]` emits `talven.native-edit-validation.v1`. The candidate is a complete source file; a source/candidate path may coincide. Validate hash syntax/budget first, then the loaded compiler identity, source read/hash, and candidate read. Analyze both exact buffers through the shared native frontend. Invalid-base repairs are permitted; successful candidate analysis can coexist with a failed base and null declaration comparison.

When both inputs pass, compare sorted declaration contracts by kind/name. `changes` contains `added`, `removed`, `contracts_changed`, and `calls_changed`. Contracts use the same signatures, ordered parameters, passing/borrow permissions and record fields as native context; direct calls are compared separately. Kind changes are removals/additions. Comments, layout and body-only edits can leave all four arrays empty. This is not a semantic-equivalence, transitive-impact, ABI-compatibility or test-selection analysis.

Reread both inputs before returning the preview. An observed difference or read failure clears `base`, `candidate`, and `changes` and returns an input-tagged operation diagnostic. Compiler identity is embedded in the loaded process and cannot change during the request; replacing a disk executable does not replace its currently loaded embedded source. A different compiler on the next invocation rejects the old expected identity. Source reads, checking and context reuse one native implementation; no Python or external compiler runs.

## Receipts and failures

Validation receipts contain `ok`, `validation: frontend-only`, expected/observed source/compiler hashes, candidate hash, source/candidate byte lengths, `candidate_changed`, native/language profiles, `base`, `candidate`, `changes`, and operation `diagnostics`. Each frontend result carries `ok` and its first ordinary native diagnostic; positions refer to that input in zero-based UTF-16. Operation diagnostics additionally name `input` as request/source/candidate/compiler. Receipts omit paths/timestamps and source bodies. The native schemas have no Python runtime identity or reference compiler hash.

E0701 means malformed revision hash or invalid 1-byte-through-1-MiB output budget; E0702 means stale compiler identity; E0501 means stale source or an observed source/candidate change. E0703 means the complete UTF-8 receipt (including newline) exceeded the output budget. Default budget is 16384 bytes. Preserve known identities on controlled failures, clear checked facts when freshness or receipt size fails, and never truncate successful JSON. Failure receipts remain outside the requested success budget. E0005 and E0901 retain shared input size/I/O failures; host I/O/decoder message text may differ from Python.

Controlled failures exit 1, successful snapshots/previews exit 0, and missing, duplicate or unsupported CLI options exit 2 before file access. Hash values reach the operation validator so malformed hashes return E0701. The CLI has no apply/write/JSON-mode switch; all edit receipts are JSON.

## Implemented usage

~~~sh
experiments/native-compiler/target/release/talven-native edit snapshot examples/invalid/type.tal
experiments/native-compiler/target/release/talven-native edit validate examples/invalid/type.tal --candidate build/candidate.tal --expect-source-hash SOURCE_SHA256 --expect-compiler-hash NATIVE_COMPILER_SHA256
~~~

Replace the illustrative hash placeholders with the exact snapshot values and create a separate complete candidate. Frontend success alone cannot establish the repair's expected behavior.

## Alternatives and costs

Launching Python would lose standalone native tooling. Reusing reference schemas with a different compiler/runtime identity would mislead consumers; share semantic contracts under explicit native schemas instead. Atomic application needs independently enforced writer coordination, so this increment remains read-only.

The compiler holds bounded source/candidate buffers and both checked programs and builds sorted JSON in Rust heap memory. Final receipt-size checks are not a general memory/time quota. Native source/compiler hashes are identifiers, not signatures or authentication. Source echo, comments and retrieved candidates are untrusted data. The shared regular-file reader opens nonblocking on the already inspected Linux x86-64/aarch64 and macOS input ABIs; unsupported platforms fail explicitly. The new modules enter build-source manifests and stale-executable tests. No third-party crate, filesystem cache, native build, provider call or generated-program runtime dependency is introduced. Latency, memory and agent benefits are unmeasured.

## Verification and unresolved work

Rust tests deterministically inject source/candidate reread changes and failures, verify that checked facts/source echo disappear, and prove stale guards precede candidate reading. CLI fixtures compare current reference declaration/call facts and diagnostic ranges, test invalid-base repairs, type/borrow failures, kind/parameter order changes, same-file noops, unchanged bytes/inode/mtime, Unicode CRLF snapshots, hash/byte boundaries and nonregular/oversized/invalid UTF-8 inputs.

Independent native C drivers exercise record mutation/result checks at O0/O2, accepting a correct repair and rejecting a frontend-valid off-by-one repair. The existing diagnostics/context/formatter/C differential suite, sanitizers and required target CI remain gates. This is finite conformance evidence, not equivalence proof or live-agent improvement.

Rereads detect only observed changes. There are no locks or atomic compare-and-swap, files can change immediately afterward, and a hash-matching no-op does not prove absence of an intervening writer. An applying host must independently coordinate writers and verify current identities within that boundary. Atomic application, native LSP integration, caching and broader task acceptance remain open.
