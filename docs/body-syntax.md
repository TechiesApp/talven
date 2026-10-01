# Experimental function-body syntax reuse

Status: implemented opt-in reference experiment under [Proposal 0028](proposals/0028-function-body-syntax-reuse.md), Proposed D56. It refines the [persistent frontend](development.md#persistent-function-checks) with exact body grammar reuse. It does not incrementally tokenize source, replace the shared grammar or change recovery parsing in the editor.

~~~sh
python3 -m talven dev examples/hello.tal --console \
  --incremental-check --reuse-body-syntax
~~~

The API accepts `IncrementalFrontend(reuse_body_syntax=True)`. The watcher option requires check reuse and cannot accompany native object mode. The [current call type option](call-type-contracts.md) can be selected independently. Native C emission/builds remain full; default full/persistent parsing is unchanged.

Every attempt freshly scans the complete current source with the shared lexer, retaining byte/token bounds, literal validation and hidden-control rejection. The shared parser parses all records and function headers afresh. A current function body can reuse only exact current text from the last semantically successful revision, with the expected closing token and token count. Comments/whitespace/CRLF changes inside its body are misses. Header-only edits can reuse body grammar but still require current semantic validation; an obsolete parameter reference fails normally. Changed/new bodies follow ordinary parsing. The full current AST receives the shared depth check.

Immutable cached facts retain literal values, tokens/spans, child order, statement/branch/store structure and body boundaries. Children are stored before parents and reconstructed iteratively. Each revision gets fresh mutable expressions/statements/lists and empty expression types; only immutable strings/tokens/spans may be shared. Translate positions from the retained body origin to the current origin. Current headers/names/types remain freshly parsed. The semantic checker separately checks or restores current types/references under its own exact-source/dependency rules.

Promote both grammar and semantic facts only after successful analysis. Lexical, syntax or semantic failures preserve the last successful snapshot; removed functions leave the successful cache. Returning a mutable analysis never exposes mutable cache nodes. Compiler source drift requires restart with E0501. Input/token/depth limits bound each generation; syntax facts add retained memory and reconstruction work whose cost must be measured, not presumed lower. There is no external/disk cache, module loader, object combination, state preservation or new target support.

`parse_stats` separates `parsed` and `reused` body names from semantic check work. Session-start events record `reuse_body_syntax`; successful checked events add `parsing`, while existing `checked`/`reused` lists keep their semantic meaning. Partial failed work is informational and never indicates successful cache promotion. The [checking runner](incremental-checking-baseline.md) accepts `--reuse-body-syntax`, retains both work kinds and verifies complete current analysis/diagnostics/context/C against full checking on independently native-accepted workloads.

Eight focused tests cover untyped restored program equality, current complete facts through Unicode/CRLF movement and declaration reordering, header/body/comment edits, current type/record/borrow errors, recursion, mutation of returned ASTs, lexical/token/nesting/depth failures and invalid repair. All valid example/fixture bodies are compared against fresh analysis/context/C. Real watcher tests verify output, header-only grammar reuse, semantic invalidation and repair; flag tests require explicit check mode. Default shared CLI/context/LSP/native checks remain required, including Linux native evidence without skips. These tests establish correctness and work decisions, not latency, memory or agent benefit.

[Three paired local comparisons](body-syntax-evidence.md) retain native-accepted workloads, current complete analysis/context/C and 2,016 samples including warmups. Warm edit and initial/invalid/schema costs remain mixed; default parsing stays unchanged.
