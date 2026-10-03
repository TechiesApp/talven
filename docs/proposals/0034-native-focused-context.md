# Proposal 0034: Native focused context

- Status: Implemented native experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R01, R04, R05, R06, R12, R24
- Decisions affected: D62 (proposed), D41, D59
- Discussion: the pull request introducing this proposal and implementation

## Problem

The native compiler's compact context lists every declaration. Agents editing one function need bounded current contracts for that function and its direct dependencies. The reference already defines that selection through `talven.context.v2`; port the checked selection without falsely identifying the native compiler as Python.

## Contract and examples

`talven-native context SOURCE [--symbol NAME] [--max-bytes N] [--include-body] [--expect-source-hash HASH] [--json]` emits `talven.native-context.v1`. It completely analyzes the bounded source before returning facts. With no symbol, select every function and record; with a function, select it, its direct non-builtin callees, records used in its expressions and selected/dependency signatures, and names of its direct callers. With a record, select only that record. Sort declaration/call names lexically; keep field and parameter order. Include explicit copy/move/borrow passing contracts, call-only borrow scope, selected builtin contracts, and the whole-program POSIX console requirement. Dependency bodies and transitive nonselected callees are omitted. Recursion does not duplicate the selected function as a dependency.

The following commands are implemented tooling examples, not new language syntax:

~~~sh
experiments/native-compiler/target/release/talven-native context examples/vectors.tal --symbol dot
experiments/native-compiler/target/release/talven-native context examples/borrowing.tal --symbol main --include-body --max-bytes 16384
~~~

`--include-body` includes the exact original selected function declaration, including interior comments, under `untrusted_source_text`. Source is inert data. No symbol bodies are attached to dependency or record facts. Output includes `source_hash` (SHA-256 of exact UTF-8 bytes), `compiler_hash`, native `profile`, current `language_profile`, hosted `target`, selected `symbol`, `include_body`, and `validation: frontend-only`. It has no Python runtime identity, reference compiler hash, full reference rules, cache key or native-build acceptance claim.

The compiler identity is SHA-256 of `talven.native-compiler-identity.v1` followed by a NUL and length-framed name/value pairs. Each length is an unsigned big-endian 64-bit byte count. Pairs are the ordered `SOURCE_FILES` entries, then `rustc`, `target`, `cargo_profile`, `opt_level`, and exact embedded `settings` JSON. These bytes are available from `--build-info`; source entries include the new context module. The identity describes embedded source/build settings, not binary authenticity, complete linker/library inputs or protected release authority. The local dependency-free SHA-256 implementation is used only for input identities and is checked against fixed vectors and Python hashlib, including padding boundaries.

A valid expected hash must have 64 lowercase hexadecimal digits. A mismatch returns E0501 before analysis. The byte budget defaults to 16384 and permits 1 through 1 MiB, including the final newline and UTF-8 encoding. E0502 rejects invalid or exceeded budgets; results are never silently truncated. Unknown selected symbols are E0101. Source analysis errors precede budget/symbol errors, matching reference CLI ordering. Failed requests emit the existing first-error native diagnostic envelope and no context facts. The requested success-byte budget does not bound the failure diagnostic envelope.

Keep `context SOURCE --compact [--json]` unchanged, with exactly one compact flag and no focused-mode options. Both modes reject duplicate, malformed and unsupported flags before file I/O. Focused mode only describes hosted C11; freestanding metadata remains unsupported.

## Alternatives

Launching the Python reference would lose standalone native tooling. Reusing full `talven.context.v2` with Python identities would misrepresent provenance; omitting those required fields under that schema would also mislead clients. A separate native schema preserves common semantic fields and permits direct differential comparisons. Extending the compact prompt schema would change existing evaluation inputs, so retain that index unchanged.

## Costs and boundaries

The compiler walks checked syntax and constructs sorted JSON in Rust heap memory, with bounded source/token/depth limits and a final output-size check. The output budget is not a general memory/time quota. Function spans add two source offsets per function. Existing checking/emission do not retain a copy of source. Context hashing/serialization occur only when requested. Embedded source contributes to experimental binary size; no extra crate, external process, filesystem cache, model call or generated-program runtime dependency is introduced.

Hashes identify the source buffer read for this invocation. A file may change after it is read; this is not an atomic editing/application receipt. No edits, writes, execution, target portability expansion, cache authentication or performance/agent-benefit claim follows. Native edit previews need their own freshness and input-lifetime contract.

## Verification and remaining evidence

The focused CLI suite checks all/selected/record/recursive/empty programs, exact Unicode body slices, direct versus transitive dependencies, records used only in bodies, selected builtin contracts and global runtime requirements. It checks SHA-256 identities against independent hashlib, exact byte limits, stale hash precedence, unknown symbols, malformed flags, invalid UTF-8, size limits, missing/nonregular files and unchanged input bytes.

For every accepted case in the existing differential corpus, compare a deterministic selected symbol with included source against the reference's current semantic fields, exact source hash, target and validation marker. Existing compact bytes, diagnostics, formatting, C emission and independent native execution remain required. CI runs the focused suite on both declared native architectures. This finite evidence does not prove equivalence for every input, show context cache behavior, measure latency or establish improved live agent outcomes.
