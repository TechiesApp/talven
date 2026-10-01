# Proposal 0030: Sequential incremental editor synchronization

- Status: Implemented reference experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R03, R05, R08, R10
- Decisions affected: D58 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Contract

Advertise LSP incremental document synchronization (`change: 2`) while accepting full replacements for compatibility and recovery. Apply content changes sequentially to a temporary current-text candidate: each UTF-16 range refers to the text after earlier changes in the same notification. Validate whole batches before replacing source and running one fresh shared frontend check. Preserve exact LF/CRLF/CR bytes, clamp columns beyond line length per the protocol, reject split surrogate pairs, reversed ranges and invalid positions, and verify optional deprecated `rangeLength` when present.

Bound a notification to 128 changes and each intermediate mirror/replacement to 1 MiB UTF-8. The mirror bound permits the editor to retain and repair a document above the language's 256 KiB source limit; the shared checker still reports E0005. Existing message/document-count bounds remain. This improves synchronization capability without incremental parsing, cache reuse, native execution, language changes or a latency claim.

Ignore old versions before interpreting their edit coordinates. A malformed newer batch preserves the preceding source text but advances the observed version, clears old analysis/diagnostics and marks the mirror unsynchronized. Reject editor queries and further ranged changes until a newer full replacement restores synchronization; close/reopen also starts fresh. Otherwise invalid edit coordinates could leave seemingly valid semantic results about a document the server no longer knows. A valid syntactically/type-invalid edit remains synchronized with current source, producing fresh diagnostics and current unchecked query fallbacks as before.

## Alternatives and costs

Full-only sync is simpler but requires clients to resend a whole document. Parsing/check reuse is a separate, larger contract and is unnecessary to receive protocol deltas correctly. Applying partial batches to shared document state would leave inconsistent text after later validation fails. Silently retaining old query results after a rejected delta risks presenting stale facts. Explicit resynchronization preserves source snapshots while stopping that ambiguity.

The server reconstructs bounded strings and fully checks the final candidate. No throughput or memory improvement is claimed. It reads editor-supplied text only and never fetches a URI, installs dependencies or runs programs. Mirror limits are resource guards, not independent policy enforcement.

## Evidence

The [implementation guide](../editor-synchronization.md) and [behavioral tests](../../tests/test_document_changes.py) cover sequential insert/delete/replace, mixed full/delta batches, UTF-16/emoji, exact line endings, columns clamped to line ends, malformed ranges/lengths, intermediate UTF-8 limits, version replay, source error/repair, rejected-batch resynchronization and every current query. A framed stdio session verifies reconstructed text through hover. The shared frontend/editor/full compiler suites and documentation checks provide regression evidence; no editor latency or model-cost measurement is invented.
