# Proposal 0019: Current-document call signature help

- Status: Draft; implemented reference LSP experiment
- Author(s): Talven contributors
- Requirements affected: R01, R03, R05, R08, R12, R24
- Decisions affected: D24 (shared frontend), D47 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

Name completion cannot explain parameter order, passing modes or borrow permissions during an incomplete call. Reusing a prior successful document would risk showing an outdated signature after a declaration edit.

## Proposal

Implement `textDocument/signatureHelp` for open editor documents, with `(` and `,` triggers. Use the shared bounded lexer/parser, current checked declarations when available and current recovered declarations otherwise. Return one unambiguous direct named function signature or the `print` contract. Duplicate recovered declarations, unknown callees and unsupported member calls return null. Function declaration parameter lists are not calls.

Track nested parentheses and braces to select the innermost unfinished call. Only commas directly inside its parentheses advance its active argument; nested calls, record initializers, grouping and commas in text/comments do not. A closed call no longer supplies its signature; an enclosing open call can resume. Comments and text interiors suppress the query. A cursor immediately before the opening text quote can still request the containing call contract.

User declarations from invalid source say `Unchecked current source`; their parameters expose declared type spelling only. A successful current analysis uses the same function facts as agent context to describe copied values, moved records, call-scoped shared read permission and exclusive write permission with no escape. Permissions are not evidence of actual writes or a proof that the current argument satisfies types, moves or loans. The normal checker remains authoritative. A stale analysis object is discarded when its source differs.

Use plain signature/parameter labels and string documentation, with top-level `activeSignature: 0` and an `activeParameter` when parameters exist. Extra/trailing argument positions keep the last parameter active without approving arity. Zero-parameter functions omit the active parameter. Return null when a complete compact UTF-8 result exceeds 64 KiB; do not truncate the declaration or parameter list. Existing source/token/tree/nesting and document/message limits apply. Shared lexical/depth failures yield null.

Protocol fields follow the primary [LSP 3.17 signature help source](https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/language/signatureHelp.md). Plain parameter labels are substrings of the containing signature; offset-label/client negotiation is not needed. Requests use UTF-16 document positions. The server recomputes from the current document rather than trusting a client-supplied previous signature. Clients must discard responses after changing their document; signature responses have no independent versioned application mechanism.

No source edit, snippet command, URI fetch, dependency lookup, subprocess or source execution is introduced. There is no overload/type-directed selection, inferred move/loan-state ranking, incremental parsing, workspace lookup or native Rust tooling parity.

## Alternatives considered

- Reuse the previous successful signature: can mislead after a current declaration edit.
- Show signatures only after successful checking: removes help during ordinary incomplete calls.
- Count commas in source strings: misidentifies arguments in nested calls, records and text. Shared tokens supply boundaries without another language parser.
- Guess ambiguous or member-call contracts: exceeds current syntax and semantic evidence.

## Costs and implications

- Agent/human feedback: exposes current argument contracts, with no measured task, token or dollar improvement.
- Runtime/memory: bounded per-request lexing/recovered parsing and response assembly; generated programs gain no editor runtime. No editor latency, memory or incremental benefit is claimed.
- Safety: recovered types are explicitly unchecked; plain strings grant no mutation/loan permission and never validate or apply source.
- Trust/targets: existing editor-supplied text and stdio boundaries, reference-only implementation; no URI/resource loading, new target or enforced OS resource quota.

## Evaluation

Verify nested/grouped calls, record initializer commas, checked borrow/move/copy details, incomplete edits and stale analysis, duplicate/unknown/member callees, text/comment suppression, declaration lists, closed calls, builtin and zero-parameter shapes, trailing arguments, response budget and depth/input failures. Exercise same-line non-BMP/CRLF UTF-16 requests, version updates, closed documents, invalid positions and absence of URI fetch/process execution. Run the full reference suite and documentation checks.

## Unresolved questions

Type-directed ranking, exact live loan-state guidance, overloads, modules/workspaces, richer incomplete syntax recovery, incremental queries and representative editor/agent measurements need separate design and evidence. Proposal acceptance remains separate from experimental implementation.
