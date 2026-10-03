# Proposal 0032: Read-only native canonical formatting

- Status: Implemented native experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R01, R03, R08, R12, R24
- Decisions affected: D60 (proposed), D25, D41
- Discussion: the pull request introducing this proposal and implementation

## Problem and contract

The standalone Rust checker/context tool still requires Python to produce canonical layout. Port the existing formatter as a syntax-only native library and read-only CLI increment, preserving the reference's token/comment contract without introducing a second style.

Add `format_source(&str)` and `talven-native fmt SOURCE [--check [--json]]`. Default mode returns canonical source to stdout. Check mode returns success only when source bytes already match, otherwise E0601; JSON check mode uses the existing native diagnostic envelope. Require `--check` for `--json`, reject duplicate/unsupported options before I/O, and never write source. Default errors are human-readable and produce no formatted stdout. Syntax errors, malformed UTF-8 and source/token/depth limits fail; semantic type, move, declaration-validity and return-path errors do not prevent formatting valid grammar.

Use the native parser's existing bounded syntax validation and extend its shared lexer with an explicit comment-retaining mode. Ordinary checking keeps comment-free tokens and unchanged limits. Formatting counts comments toward the reference's 16384-token bound. Match `m1-scalar-mutation-layout-v1`: four-space indentation, LF endings, nonempty final newline, declaration separation, operator spacing, inline groups expanded by comments and original trailing-comment attachment. Preserve every code token's spelling/order and comment text/order, with only the reference's terminal-CR normalization. No wrapping, literal rewriting, declaration sorting or configurable layout is added.

Track expanded output bytes, including indentation and newlines, before returning. More than 256 KiB is E0602; never return a truncated edit. Re-lex the full result with comments and compare token kind/text identity before producing output; mismatch is E0604. Check mode remains a layout check rather than semantic or task acceptance. Its E0601 message names the supported native preview command rather than the reference's in-place writer.

## Alternatives, costs and trust

Delegation to Python would retain one renderer but defeat standalone native tooling. Formatting from a semantically checked program would block layout during common repair tasks and lose original token/comment spelling. A second layout would require agents and humans to make tool-dependent style decisions. Porting the existing grouping/writer behavior with corpus comparisons is the bounded choice.

Native in-place writes and revision guards would require a separate filesystem freshness, link, replacement and writer-coordination boundary; those remain with the reference tool. Editor integration, configuration/plugins, range formatting, token budgets and performance measurements are separate. Source comments never grant tool authority or control formatting. The compiler uses its existing Rust heap/standard library, and generated Talven programs gain no runtime or allocation cost. Bounds are resource guards rather than CPU quotas or independent access policy.

Put the renderer in `src/format.rs`, embed that exact file in `--build-info`, archive it with measurement inputs and require the comparison verifier to reject stale/missing/unexpected build sources. This preserves provenance without authenticated build or complete host-toolchain claims. No measured speed, memory, token saving or model-effectiveness claim is made.

## Verification

The [native guide](../../experiments/native-compiler/README.md#canonical-formatting) and [reference layout guide](../formatting.md) distinguish supported modes. Rust unit tests cover exact layout, CRLF/comment attachment, syntax-only semantic repairs and comment/output limits. The [native formatting suite](../../experiments/native-compiler/tests/formatting.py) checks exact Unicode/literal bytes, empty/comment-only files, every comment boundary in a borrowing/mutation program, seeded whitespace variants, idempotence, reference token identity and unchanged native lowering. It exercises layout-needed/check success, malformed/unsupported options, syntax/encoding/nesting/byte/token/output failures, missing/nonregular sources and source preservation in every mode.

The full differential corpus compares native/reference default formatting for every source, including semantic errors and token mutations; accepted bytes and failure codes/messages/ranges must agree except the existing invalid-UTF-8 host-message allowance. Existing check/context/C/runtime oracle tests, stale-build checks, sanitizer checks and full reference regression tests remain required. The declared native Linux CI jobs explicitly run the formatting suite; local macOS evidence is not substituted for those targets. This does not complete native tooling parity or the live-agent M1 gate.
