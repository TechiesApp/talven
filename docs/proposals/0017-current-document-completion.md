# Proposal 0017: Current-document completion

- Status: Draft; implemented reference LSP experiment
- Author(s): Talven contributors
- Requirements affected: R01, R02, R04, R05, R08, R12, R24
- Decisions affected: D22 (shared frontend), D45 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

The LSP exposes diagnostics and navigation but cannot suggest names while an agent or human types. Completed documents can supply semantic facts; an incomplete or invalid revision must not inherit stale names, locations or borrowing details from a previous successful revision.

## Proposal

Implement `textDocument/completion` using the current editor-supplied source and the shared bounded lexer/parser. Advertise plain completion with `.` as a trigger and no resolve handler. Suggest keywords, scalar/static-text types, `print`, current functions and records, and parameters/previous completed local declarations in the cursor's lexical scope. Suggestions filter by the ASCII identifier prefix and sort deterministically.

For `local.field` or `parameter.field`, suggest only fields of that named receiver's current record type. Checked expressions and declarations supply types and existing checker descriptions, including mutation and call-scoped borrowing. Invalid revisions use recovered current syntax: declared parameter types, explicit local annotations and direct record initializers can supply field-name candidates. Mark all user declaration/binding details from such source as `unchecked source`. Suggestions are not evidence that a proposed use satisfies types, moves, loans, or control flow; the ordinary checker validates the completed edit.

Parse recovery does not alter or hide diagnostics. Lexical/depth/size failures return no suggestions. Comments, text literals and numeric tokens suppress completion. Declarations after the cursor, sibling branch locals and locals in ended scopes are excluded. General name completion does not implement type-directed expression synthesis.

Return plain identifier `textEdit`s replacing the entire current ASCII word on one line, with UTF-16 positions and the current document version in item data. The server never applies edits. Clients must discard stale responses after a document change; the data field is provenance, not independently enforced compare-and-swap. Limit the list to 128 items and its compact UTF-8 JSON result to 64 KiB. Omitted candidates set `isIncomplete: true`.

No filesystem lookup, document-URI fetch, compiler process, source execution, snippet command, import edit or dependency loading is added. Existing document/message limits and lifecycle/version handling remain in force. Completion after temporary/call receivers or chained scalar fields, semantic tokens, incremental parsing, move/loan-aware ranking, modules and multi-file completion remain open.

## Examples

These editor interactions use implemented Talven syntax:

- At `ad` in `return adwrong(4);`, suggest current function `adjust` and replace `adwrong`, preserving the call argument.
- At `p.va` with `p: &Counter`, suggest current field `value` with its scalar type. An invalid current document marks the description unchecked.
- Inside one branch, suggest its earlier locals and outer bindings, excluding sibling-branch locals and later declarations.

Protocol shapes follow the primary [LSP 3.17 completion specification source](https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/language/completion.md). Record/type suggestions use the original `Class` item kind for clients without newer item-kind negotiation; details retain Talven's record terminology.

## Alternatives considered

- Require complete successful checking: would disable suggestions at many ordinary intermediate edits.
- Keep the prior successful semantic model for invalid edits: risks stale names, types and edit positions.
- Build a second completion parser/type system: duplicates grammar and safety logic. This increment uses shared syntax and labels recovered details without claiming successful semantics.
- Add snippets, auto-imports or source application: separate editing/workspace contracts, beyond identifier completion.

## Costs and implications

- Agent context: deterministic candidates and current positions help propose edits; no token/task-cost improvement is inferred.
- Runtime and memory: bounded per-request syntax work and candidate output; generated programs gain no completion runtime. Editor latency and memory are unmeasured.
- Security: editor-supplied text remains untrusted; signatures are plain strings and no command or foreign resource is accessed. Limits are not OS quotas or a sandbox.
- Targets: reference-only stdio editor functionality, with no new native target or Rust tooling parity claim.
- Ecosystem and interoperability: plain LSP text edits, no editor extension, package integration or foreign ABI change.

## Evaluation

Verify global/prefix suggestions, parameter/local scope, declaration order and initializer visibility, branch isolation, record/borrow field details, typing recovery, current-source replacement, complete-word edits, same-line non-BMP UTF-16 positions, comments/text/numeric suppression, limits and incomplete-list receipts. Apply a returned edit to an invalid call and verify it checks. Confirm old versions cannot overwrite a newer document and closed documents cannot supply candidates. Check that requests never fetch URIs or execute code. Run the full reference suite and documentation checks.

## Unresolved questions

Type-directed ranking, precise move/loan-state filtering, temporary receivers, richer incomplete-syntax recovery, semantic highlighting, workspace symbols/imports, native parity and representative editor latency need further design/evidence. Proposal acceptance remains separate from the experimental implementation.
