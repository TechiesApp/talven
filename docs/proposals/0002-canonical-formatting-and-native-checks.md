# Proposal 0002: Canonical formatting and native checks

- Status: Draft
- Author(s): Codex, implementing the project owner's request to continue the next increment
- Requirements affected: R01, R03-R08, R12, R15, R21-R22 from [requirements.md](../requirements.md)
- Decisions affected: proposed D25 and D26 in [decisions.md](../decisions.md)
- Discussion: implementation pull request for branch `prototype/m1b-formatting`, building on Proposal 0001

## Problem

The M1a compiler gives agents checked types and context, but leaves layout decisions and formatting edits to each human or model. The LSP cannot yet apply the same formatter as the CLI. Local x86-64 tests also provide no ongoing ARM64 execution evidence.

## Proposal

Implement the experimental layout profile `m1b-layout-v1` through one shared lexer/parser-based formatter. Preserve code token spelling/order and comment text/attachment, normalize whitespace, and verify token preservation before returning an edit. Formatting is syntax-only, allowing users to format while repairing semantic errors.

Provide stdout, check-only, and explicit in-place CLI modes, plus whole-document LSP formatting. Document limits and file-write assumptions in [formatting.md](../formatting.md). Keep language semantics at `m1a-owned-values-v1`; borrowed references remain outside this increment.

Add read-only GitHub CI jobs for Linux x86-64 and ARM64 native conformance. Pin new actions to full official release commits, reject missing native tools/skipped tests in these jobs, and record the actual host, compiler, and test evidence.

## Examples

The following commands are implemented prototype interfaces:

~~~sh
python3 -m talven fmt examples/vectors.tal
python3 -m talven fmt examples/vectors.tal --check --json
python3 -m talven fmt examples/vectors.tal --write
~~~

Only `--write` modifies the source. An agent may add `--expect-source-hash HASH` to reject an unexpected revision. After a semantic edit and formatting, the agent still needs compilation and independently controlled task tests.

## Alternatives considered

- Ask agents to follow a prose style guide. This leaves repeated style decisions and inconsistent diffs without a deterministic check.
- Print only the semantic AST. The current AST discards comments and redundant parentheses, so that approach would lose source data without a richer syntax representation.
- Allow formatter plugins or project-specific styles. These increase configuration/context costs and the executable dependency surface; reconsider only with concrete requirements.
- Use configurable indentation from each editor. This would let identical source produce different CLI and editor results. The proposed profile fixes four spaces and documents the override.
- Add cross-compilation alone. It does not establish native execution behavior; actual hosted ARM64 jobs give stronger but still target-limited evidence.

## Costs and implications

- Agent context: one layout profile and structured check diagnostics; the formatter identity joins compiler-context cache inputs. Formatting invalidates exact-byte source hashes.
- Runtime and memory: bounded parsing, token retention, layout, and re-lexing add compiler/editor CPU and memory work. Generated native programs gain no formatting runtime.
- Security: no formatter plugins, source execution, or config discovery. Explicit writes reject direct symlinks/multiple links and check freshness. Final compare-and-replace is not atomic; external writer coordination is required. CI permissions and commit pins do not make mutable repository checks independent policy enforcement.
- Targets: new CI jobs declare Linux x86-64 and ARM64, recording actual execution results. OS, ABI, board, GPU, and other compiler support remain separate evidence requirements.
- Ecosystem and interoperability: no package or foreign-runtime adapter is introduced. Formatting comments does not authorize instructions inside them.

## Evaluation

Verify exact expected layouts, idempotence, comments at every token boundary, CRLF/Unicode preservation, and unchanged C lowering across seeded whitespace variants. Exercise type-invalid but parseable programs, syntax failures, output/input limits, stale hashes, write failures, linked files, UTF-16 LSP edits, and no-op editor/file behavior. The [validation record](../formatting-validation.md) records observed results; there is no LLM token/cost benchmark yet.

## Unresolved questions

Which wrapping rules improve human readability without increasing model errors? When should the parser retain a lossless syntax tree? What separately enforced compare-and-swap edit API should multiple agents use? What diagnostics and semantics should the first borrowing subset adopt? Comparative agent evaluation and future proposals must decide these questions.
