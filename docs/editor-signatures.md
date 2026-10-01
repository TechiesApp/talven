# Editor call signatures

Status: implemented reference stdio LSP experiment under [Proposal 0019](proposals/0019-current-call-signatures.md). Launch `python3 -m talven lsp` through an editor client. The server advertises `signatureHelpProvider` with `(` and `,` triggers and handles `textDocument/signatureHelp` for open documents.

Inside an unfinished direct call, show its current function signature and parameter labels, highlighting the active argument. Nested call/grouping/record delimiters preserve the correct comma count. Closing a nested call restores an enclosing call's argument context. `print` shows its static-text parameter and console requirement. Functions with no parameters omit the active index; extra/trailing arguments keep the last declared parameter visible without approving the argument count.

Checked current declarations describe copy/move passing and shared read/exclusive write permission, with call-scoped nonescaping record loans. Invalid documents can supply recovered current signatures, explicitly marked unchecked. Recovered parameter documentation exposes declared type spelling only. Signature help is not proof that the call is legal; diagnostics still validate arity, types, moves and borrowing. No previous successful semantic model is substituted.

Unknown/ambiguous/member callees, function declaration lists and closed calls yield null. Comments and text interiors are inert; a cursor before the opening quote can show the containing call signature. Shared lexical/source/token/depth failures yield null. Damaged syntax may lack enough recovered declarations to show help.

Results use plain labels and string documentation, with one active signature and at most 64 KiB compact UTF-8 JSON. Oversized declarations return null rather than a partial parameter list. Requests use UTF-16 positions, including non-BMP text and CRLF sources. Invalid positions and closed/unknown documents return invalid-parameter errors. Newer document versions replace older ones; clients must discard stale responses after changing their document. Client-supplied previous signatures do not supply declarations.

The query never edits source, opens a URI, runs a compiler/program or loads a dependency. Existing document/message limits apply. No overload/type-directed selection, current move/loan-state ranking, native Rust parity, workspace lookup, incremental parsing or measured responsiveness benefit is claimed.

`tests/test_signature_help.py` exercises checked/recovered contracts, delimiter ownership, active indices, builtin/zero-parameter cases, stale sources, inert text, input/result bounds, UTF-16/lifecycle behavior and external-action absence. Existing completion, highlighting and navigation continue through the shared frontend.
