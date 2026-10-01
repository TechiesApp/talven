# Editor semantic highlighting

Status: implemented full-document reference LSP experiment, specified in [Proposal 0018](proposals/0018-semantic-highlighting.md). Launch `python3 -m talven lsp` through a client that supports semantic tokens. Client themes decide how classifications appear; no editor extension is bundled.

The server advertises `semanticTokensProvider` with a fixed legend and handles `textDocument/semanticTokens/full`. It colors current lexical keywords, numbers, static text, comments, operators and builtin type spellings. A successful current analysis also supplies resolved record types, functions, parameters, local variables and fields through the same declarations/references as navigation.

The legend's types, in numeric order, are `keyword`, `number`, `string`, `comment`, `operator`, `type`, `function`, `variable`, `parameter`, `property`. Modifier bits 1, 2 and 4 mean declaration, explicit assignment modification and default-library fact, respectively. They can combine. `print` calls and builtin types receive the default-library bit; checked bindings override mere builtin spelling. Field assignment marks the field name and scalar assignment marks the local name. Calls that mutate a borrowed record do not mark their argument as an explicit assignment.

Modifiers do not express readonly permission, current loan eligibility, liveness or complete effects. Checked colors are facts about the current successful analysis, not proof that an arbitrary new use is valid. Normal diagnostics continue to enforce types, moves and borrowing.

Invalid edits clear semantic identifier facts and retain only current lexical colors. Unresolved identifiers are omitted. A lexical or source/token-limit error produces empty data; no old result substitutes for it. Comments count toward the token limit for this query. Repair restores classifications using the newly checked document. Older document versions are ignored, and requests for closed or unknown documents return invalid-parameter errors.

Token data uses relative line/start positions and UTF-16 lengths, including non-BMP source characters and CRLF. Tokens are single-line, ordered and nonoverlapping. Existing source/token limits bound results to 81,920 integers and under 512 KiB compact result JSON. The position encoder advances through source once. These limits establish neither a CPU/RAM quota nor measured responsiveness.

Only full requests are supported. Range and delta requests are not advertised and return method-not-supported errors. No previous token result is retained, document URI fetched, compiler/program run or source edit applied. Multi-file/incremental parsing, richer semantic modifiers and native Rust parity remain open.

`tests/test_semantic_tokens.py` decodes the relative data independently, checks resolved roles and assignment markers, verifies UTF-16/CRLF spans and no overlap, exercises examples/fixtures and limits, and tests invalid edit/version/repair/close behavior without foreign execution or file reads.
