# Proposal 0037: Bounded local source modules

- Status: Draft; implemented reference experiment
- Author(s): Talven contributors
- Requirements affected: R01, R04, R08, R11, R12, R16, R24, R25
- Decisions affected: D65 (proposed), D04, D24, D35, D36
- Discussion: the pull request introducing this implementation

## Problem

The implemented language has one global namespace per source file. Concatenation would expose private helpers, collapse record identities and lose original diagnostic/navigation locations. Agents need explicit interfaces and exact dependency sources for realistic multi-file edits. Object reuse and eventual reload need module contracts too, but this increment does not extend either mechanism.

## Proposal

Add an explicitly selected companion profile, `m1-local-modules-v1`, with the current base expressions, types and borrowing rules. Single-file commands and the `m1-scalar-mutation-v1` grammar remain unchanged. Reference `project check/context/emit-c/build` commands take an entry path and mandatory `--root`. The in-memory API takes an explicit source bundle without fetching missing sources.

Each file is a module. Leading imports use `import "root-relative/path.tal" { Name, Other as Alias };`, selecting 1–128 directly declared public names, with optional trailing comma. Imports precede declarations. `pub struct` and `pub fn` export owned declarations; others remain private. `import`, `pub` and `as` are contextual words in the companion, not newly reserved words in the base profile. No wildcard imports, reexports, implicit transitive names, module-qualified source syntax, cycles, packages, network resolution or search paths are added.

Own declarations and imported aliases share a module namespace. Duplicate/reserved bindings fail; local scopes retain existing rules. Same-named records from different files remain nominally distinct, even with identical fields. Public function signatures cannot expose an owned private record. Imported public records keep their original identities in public signatures; consumers explicitly import the record from its defining module. Copy/move/call-scoped borrow contracts and source-order loan conflict checks remain unchanged.

Paths are canonical root-relative ASCII `.tal` paths of at most 128 bytes: letter/digit/underscore/hyphen components separated by `/`, with `.tal` on the final component. Imports resolve from the explicit root regardless of importer directory. Reject absolute paths, `.`/`..`, empty components, backslashes and symlink traversal. Resolve only the entry's reachable closure. Cap it at 32 modules, 16 import levels (entry is level one), 256 KiB aggregate original UTF-8 source and 16384 tokens. Individual parser/nesting/tree limits still apply.

Parse modules with the shared parser, resolve declaration/type/call/construction tokens in explicit scopes, and lower into one core-profile source snapshot. Only parsed global tokens and import/visibility headers change. Strings, comments, locals and field names are not interpreted as globals. Internal globals use sorted module ordinal/name pairs; the entry's owned `fn main` retains the executable entry name. `__talven_module_` is reserved for identifiers in the companion. Internal names are neither a public foreign ABI nor a reusable-object contract.

Fresh ordinary frontend analysis checks the resolved source; ordinary backend emission builds it. The lowered source also obeys core byte/token limits: identifier expansion may reject an original closure that fits. A segment map preserves original file/UTF-16 diagnostic and navigation locations. The Rust executable independently checks/emits resolved core source, with exact C comparison and native execution, but does not resolve the graph or accept raw module syntax itself.

## Receipts and tools

`talven.project-check.v1`, `talven.project-context.v1` and `talven.project-query.v1` identify profile, entry, sorted module paths/exact source hashes, direct import bindings, lowered-source hash, current compiler hash and canonical manifest `graph_hash`. Graph identity excludes compiler identity; consumers retain both. Hashes identify inputs, not authenticated artifacts or authority to execute.

Context labels semantic identities `file.tal::Name`; source uses own/imported names. Focused receipts contain selected function contracts, direct callees, relevant nominal records, direct callers, all public interfaces and whole-closure console requirements. Optional exact selected declarations are `untrusted_source_text`; callee bodies are omitted. Context/query budgets default to 16384 bytes, accept 1 byte through 1 MiB and count complete UTF-8 JSON/newline. Exceeded budgets produce failure envelopes, not partial facts. Success is frontend-only, not task acceptance.

The explicit `talven/projectQuery` LSP extension accepts a bounded in-memory source bundle and freshly checks each hover/definition/reference request. It does not open source URIs or discover filesystem dependencies. Imported names/aliases navigate to the actual declaration. This extension is separate from standard single-document requests; automatic workspace synchronization, project rename/completion/signature help and transactions remain open. `fmt --module` selects syntax-only module layout with the ordinary revision-checked write path, without loading dependencies.

Disk loading pins a root directory descriptor and opens every component with no-follow directory-relative operations. Bounded regular-file reads are nonblocking. Successful analysis rereads captured sources and rejects observed changes/unavailability. Builds keep that root descriptor, compile the snapshot, reread before publishing and preserve an existing output on compiler/freshness failure. Outputs cannot overwrite captured source or an existing hardlink alias. Rereads/publication are not an atomic transaction; another writer requires independent coordination. Unsupported no-follow/dirfd facilities fail explicitly.

E1101 rejects malformed paths/requests/internal names; E1102 unavailable modules/cycles; E1103 private exports/signature declarations; E1104 graph/resource limits. Ordinary name/type/ownership diagnostics map to original locations. E0501 rejects expected graph mismatch/observed source changes; E0502 enforces context/query budgets. Failed checks return no success facts.

## Examples

The [module guide](../modules.md) and [three-file program](../../examples/modules/main.tal) are implemented examples. Public borrowed mutation, import aliases and unrelated private helpers compose through the shared checker. The program executes through C11 with independent result/mutation checks.

## Alternatives considered

Concatenation erases privacy/nominal identity. Ambient lookup inside the existing checker/LSP would make queries depend on hidden state. Another ownership checker risks different safety rules. Qualified source calls, cycles and a package manifest add separate decisions. Explicit closure resolution into the shared core checker provides a smaller inspectable starting contract.

## Costs and implications

The compiler heap stores original syntax/sources, a lowered snapshot, segment maps and analysis. Input/output limits are not comprehensive memory quotas. Generated programs gain no heap, loader, module runtime, foreign boundary or executor. Whole closures currently check/build in full. Startup/check/build time, memory and agent effectiveness need measurements; no speedup or completed milestone gate is claimed.

The selected C compiler remains trusted native software. Root-relative loading is not a hostile-process sandbox or protected release enforcement. Source/body text is untrusted input. The in-memory API uses supplied sources; identity receipts read compiler-owned implementation files. Disk loading requires inspected POSIX facilities; no new target support is inferred.

## Evaluation

Verify imports/aliases/privacy, public signature types, distinct records, moves/reborrows/loan order, exact original UTF-16 locations, dependency changes/stale identities, deterministic ordering, output budgets, graph depth/count/byte/token limits, malformed paths, symlinks/directories/FIFOs and observed source changes. Ensure failed compilation/source changes preserve output and forbid input overwrite.

Run all reference regressions. Required Linux jobs format/check/build/execute the example without skips. Compare C from both frontends for resolved core source and execute both at O0/O2 under ASan/UBSan, using an independent oracle including i32 boundaries and actual mutation. This validates the lowered boundary, not independent native module resolution.

## Unresolved questions

Native graph/parser support; full workspace LSP integration; project edit/test/watch receipts; atomic multi-file application; persistent interface/dependency reuse and state/reload contracts; qualified syntax/reexports/cycles/packages/foreign imports; public effects/typed failures; and controlled agent evaluations remain open.
