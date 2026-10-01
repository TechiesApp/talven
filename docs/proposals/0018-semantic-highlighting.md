# Proposal 0018: Current-document semantic highlighting

- Status: Draft; implemented reference LSP experiment
- Author(s): Talven contributors
- Requirements affected: R01, R02, R04, R08, R12, R24
- Decisions affected: D22 (shared frontend), D46 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

Editor users cannot distinguish resolved Talven functions, parameters, local bindings and record fields through the LSP. Highlighting inferred from spelling alone can also misclassify same-named symbols or leave old semantic facts visible after an invalid edit.

## Proposal

Support `textDocument/semanticTokens/full` with a fixed legend and complete current-document results. Use the shared lexer for keywords, numbers, text, comments, operators and built-in type spellings. For a successful current analysis, classify identifiers through the same declaration identities and checked references used by navigation. Distinguish functions, parameters, locals, record types and fields; mark declarations and explicit assignment destinations. Mark builtin type names and resolved `print` calls as default-library facts. Binding resolution overrides builtin spelling when a valid local/parameter uses that name.

The token type legend is `keyword`, `number`, `string`, `comment`, `operator`, `type`, `function`, `variable`, `parameter`, `property`. Modifier bits identify `declaration`, `modification`, `defaultLibrary`. Do not claim readonly, loan eligibility, liveness or effect guarantees through colors. A modification marker identifies an explicit assignment destination, not all transitive effects of a call.

Invalid revisions retain only current lexical colors. Unresolved identifiers are omitted; no prior successful semantic result is reused. Lexical/input/token-limit failures return an empty current result. Existing diagnostics remain authoritative and unchanged. Comments count toward this lexer's token limit, and invalid depth/semantic source cannot supply resolved identifier facts.

Encode ordered, nonoverlapping, single-line tokens as LSP relative integer tuples with UTF-16 start/length units. Advance positions through source gaps once, rather than repeatedly rescanning the whole prefix for every token. Current 256 KiB source and 16,384-token limits bound the result to at most 81,920 integers and below 512 KiB compact UTF-8 JSON. This is a data bound, not an OS CPU/RAM quota or latency guarantee.

Advertise full support and no range/delta support. Compute each result from the current open document without a token-result cache. Closed/unknown documents return invalid parameters; unsupported range/delta methods retain method-not-supported errors. Existing lifecycle and increasing document versions apply. The server never fetches document URIs, executes a compiler/program, loads a dependency or applies source edits.

## Examples

For implemented `p.value = p.value + 1;`, the first field name is a property with the modification bit; the second is an ordinary property use. The named receiver is a parameter or variable according to its checked declaration. In `let mut x = 0; x = 1;`, the first `x` is a variable declaration and the second an explicit modification. `&mut Counter` remains separate operator, keyword and resolved record-type tokens, without overlaps.

The relative encoding and legend follow the primary [LSP 3.17 semantic-token specification source](https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/language/semanticTokens.md). Literal non-BMP characters occupy two UTF-16 units; escape sequences occupy their source spelling's units.

## Alternatives considered

- Classify all identifiers by name/nearby tokens: misses nominal fields, local namespaces and same-named parameters.
- Reuse old classifications during invalid edits: hides current semantic uncertainty and risks obsolete positions.
- Add deltas and range caches now: separate result-generation, invalidation and lifecycle contracts; full results first establish correctness.
- Infer readonly/effects from syntax: conflates binding permission, pointee mutation and loan state; those need more precise queries.

## Costs and implications

- Agent context: current classifications can assist editor navigation; no model/token/task benefit is measured.
- Runtime and memory: development-only lexical/reference traversal and bounded token data; no generated-program runtime or allocation change.
- Security: source and comments remain untrusted inert data; no foreign execution or filesystem authority is introduced.
- Targets: reference stdio LSP, without a new native execution target or Rust tooling parity claim.
- Ecosystem and interoperability: standard full semantic-token results, with client themes controlling rendering; no bundled extension.

## Evaluation

Decode outputs independently and verify actual source substrings, UTF-16 positions, CRLF, non-BMP text/comments, order and lack of overlap. Check declaration/reference classifications, borrowed type spans, field/scalar assignment markers and local names overriding builtin spelling. Verify invalid edits clear semantic identifiers, old versions cannot overwrite newer documents, repair restores facts and closed documents fail. Exercise all valid examples/fixtures and maximum token/source limits, and prohibit URI/process access in tests. Run the full reference and documentation suites.

## Unresolved questions

Range/delta requests, richer modifier semantics, semantic facts for partially invalid functions, incremental parsing, workspace identity, native integration and representative editor latency/memory require further work. Design acceptance remains separate from implementation.
