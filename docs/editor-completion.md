# Editor name completion

Status: implemented reference stdio LSP experiment, specified in [Proposal 0017](proposals/0017-current-document-completion.md). Start the server with `python3 -m talven lsp` through your editor's LSP client. No editor extension is bundled.

The server advertises `completionProvider` and handles `textDocument/completion` for an open document. It suggests current functions/records, keywords, `i32`/`bool`/`str`, `print`, and parameters/earlier local declarations in scope. Typing `.` after a named local or parameter suggests fields when the current source identifies its record type. General name completion filters by the current ASCII prefix; it does not synthesize expressions or guarantee that each suggestion is valid at that expression/type position.

Checked source supplies checker descriptions, including shared/exclusive borrow and mutable-binding information. When source does not check, recovered current syntax can still supply declaration names and declared/direct-initializer record types. Such user-defined details explicitly say `unchecked source`. The old successful semantic model is never substituted. Successful completion is not successful compilation; apply the edit and use normal diagnostics to validate types, moves and loans.

Suggestions exclude later declarations in the current local scope, the binding being initialized, sibling-branch locals and locals in ended scopes. Completion is suppressed inside comments, static text literals and numeric tokens. Shared lexer/input/depth failures yield an empty list. Comments participate in the completion lexer's token limit. Unclosed or badly damaged syntax may lack enough recoverable declarations to offer useful candidates.

Each item contains a plain identifier edit replacing the whole current ASCII word on one line. Positions use UTF-16, including text with preceding non-BMP characters. No snippet expansion, extra edit, command, URI lookup, compiler subprocess or program execution occurs. `data.documentVersion` identifies the source used; clients must discard responses after their document changes. It does not enforce safe application by itself.

Lists contain at most 128 items and compact result JSON at most 64 KiB. When candidates are omitted, `isIncomplete` is true and the client can request a narrower prefix. Invalid positions and requests for closed/unknown documents return invalid-parameter errors. Document version updates and existing server initialization/shutdown behavior apply normally.

Temporary/call receiver completion, chained fields, snippets, semantic tokens, incremental parsing, modules, multi-file lookup and move/loan-aware filtering remain open. No native Rust completion parity or measured responsiveness/cost improvement is claimed.

`tests/test_completion.py` covers scope, typing recovery, field/borrow details, whole-word edits, same-line UTF-16 translation, inert text, stale analysis/versions, limits and lifecycle. A returned edit repairs a real invalid call through the shared checker, while the server's document remains unchanged.
