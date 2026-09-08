# Canonical formatting

Status: implemented experimental tooling. M1b introduced `m1b-layout-v1` for the owned-value subset, and M1c added borrowing tokens with `m1c-layout-v1`. Compiler `0.4.0-dev` uses `m1-static-text-layout-v1` with `m1-static-text-v1`; it preserves the layout rules below and treats each quoted literal as one token with unchanged spelling. See [borrowing](borrowing.md) and [static text](text-console.md) for the extensions and context contracts; full M1 still needs controlled agent evaluation.

## Commands

From the repository root, with Python 3.11 or later:

~~~sh
python3 -m talven fmt examples/vectors.tal
python3 -m talven fmt examples/vectors.tal --check --json
python3 -m talven fmt examples/vectors.tal --write
~~~

The default prints formatted source to stdout and leaves the file untouched. `--check` returns zero when the file already matches the canonical layout and one when formatting is needed or fails. With `--check --json`, the existing `talven.diagnostics.v1` envelope provides structured diagnostics. `--json` requires `--check`; `--check` and `--write` are mutually exclusive.

`--write` explicitly replaces the source file after formatting succeeds and freshness checks pass. Any mode accepts `--expect-source-hash HASH`, using the same exact UTF-8 SHA-256 identifier as compiler context. A mismatch returns `E0501` before producing formatted source or writing an edit.

Formatting uses the shared lexer and bounded parser. It requires valid syntax, but not correct types, complete return paths, or valid ownership. This lets a human or agent format a program while repairing a type error. Syntax failures produce a diagnostic and no formatted output or write.

## One layout

- Four spaces per indentation level, LF line endings, and a final newline for nonempty output. Whitespace-only input becomes empty output.
- Function bodies, conditional bodies, and record declarations use multiple lines. Top-level declarations are separated by one blank line.
- Calls, parameter lists, and record literals stay inline when they contain no comments. A comment inside a delimited group expands that group to multiple lines.
- Operators and typed bindings use consistent spacing. Statements end their line. Comments following a token on its original line stay attached to that token.
- Code token spelling and order are preserved, including parentheses, leading zeros, trailing commas, declaration order, and field-initializer order. Comment order and text are preserved, except a terminal carriage return is normalized as part of the line ending.

There is no line-length wrapping, configurable indentation, import sorting, parenthesis removal, numeric rewriting, or comment reflow in this profile. Canonical means one whitespace layout for the existing token stream and comment attachment; equivalent programs with different tokens can still format differently. Whitespace inside a comment, including trailing spaces, remains comment data.

~~~text
struct Point {
    x: i32,
    y: i32
}

fn sum(point: Point) -> i32 {
    return point.x + point.y;
}
~~~

The formatter does not honor instructions or formatting directives in comments. It does not load configuration files, plugins, package contents, or external tools. Before returning an edit, it re-lexes the result and verifies token/comment preservation. Input and output are each limited to 256 KiB; the formatter's 16384-token limit includes comments. Parser nesting limits also apply. Expansion beyond the limit fails rather than returning truncated source.

## Editor behavior

The existing stdio server advertises `documentFormattingProvider` and handles `textDocument/formatting`. It formats editor-supplied text from an open document; no URI is fetched and no file is written by the server. It returns either no edits for an already formatted document or one full-document edit with a UTF-16 range. The client applies the edit and sends its normal versioned document update.

The canonical profile overrides editor indentation preferences, so CLI and LSP produce the same output even when a client prefers tabs. Requests still require the standard `tabSize` and `insertSpaces` options. Unsupported/malformed parameters use JSON-RPC error `-32602`; a syntax or formatting-limit failure uses LSP `RequestFailed` (`-32803`) with the compiler diagnostic in `error.data.diagnostics`. Range formatting and on-type formatting are not implemented.

The returned `TextEdit` does not carry a document version. The client must discard an outstanding formatting response if its document changed. This protocol behavior is not an atomic multi-agent edit API. See the [official LSP document-formatting specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_formatting).

## File-write boundary

`--write` is intended for a trusted workspace with externally coordinated writers. It rejects direct symbolic links, files with more than one hard link, and non-regular files. It checks the original file identity, modification time, mode, and bytes before replacing the file, and preserves observed changes by returning `E0501`.

Replacement uses a temporary file in the same directory and `os.replace`; a failed replacement leaves the original file in place and removes the temporary file. POSIX mode bits are copied. An already formatted file keeps its inode and modification time. Ownership, ACLs, extended attributes, and crash-durable directory synchronization are not preserved or guaranteed by this prototype.

The freshness check and replacement are separate operations. There remains a race between the final check and replacement, including changes to ancestor directories. This is not an atomic compare-and-swap or a security boundary against another process controlling the workspace. Use editor-mediated edits or a separately enforced workspace lock when coordinating multiple writers; this increment does not implement that lock.

## Diagnostics and context

| Code | Meaning |
| --- | --- |
| E0001 / E0002 / E0005 | Shared lexical, syntax, or input/nesting-limit failure |
| E0501 | Expected revision mismatch or an observed change before writing |
| E0601 | `fmt --check` found a noncanonical layout |
| E0602 | Formatting would exceed the output byte limit |
| E0603 | In-place target is not a regular file with one link |
| E0604 | Internal token-preservation check failed; no edit is produced |
| E0901 | File, encoding, or replacement failure |

Compiler context includes `formatter_profile` in its identity fields. M1b introduced this in `talven.context.v1`; M1c uses `talven.context.v2` for new borrowed-parameter contracts. The compiler fingerprint also covers the formatter and source-edit modules. Formatting changes exact source bytes, so source/context hashes must be refreshed after applying an edit. A successful formatting check does not establish type correctness. Run `check` and the relevant independent tests after semantic edits.

Consistent formatting is intended to reduce unnecessary diffs and agent style decisions. No token savings, cache-hit improvement, latency target, or model success-rate gain has been measured. The formatter adds build/editor work but does not add code or a runtime dependency to generated native programs.

## Native verification

The new [compiler workflow](../.github/workflows/compiler-check.yml) declares Linux x86-64 with Python 3.11/3.12 and Linux ARM64 with Python 3.12. Each job verifies its actual machine architecture, requires `cc` and `nm`, runs the full suite with no skips, checks example formatting, and builds and executes the CLI vector and borrowing examples. M1c also requires a separate ASan/UBSan check of borrowed lifetimes and observable evaluation order at two optimization levels. A job summary records Python, C compiler/target, compiler fingerprint, and test counts.

The actions use full commit pins verified against official releases: [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) and [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0). The workflow requests read-only repository contents and disables persisted checkout credentials; it neither publishes releases nor changes deployment settings. Pins and runner images still need maintenance. A checked-in workflow is not independent enforcement against someone who can modify it.

[GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) lists `ubuntu-24.04` and `ubuntu-24.04-arm` for public repositories. Declaring a runner does not prove successful execution: consult the [historical M1b record](formatting-validation.md), [current M1c record](borrowing-validation.md), and actual pull-request checks. These jobs do not validate GPUs, Windows/macOS, boards, all ARM/x86 variants, or the broader planned language.
