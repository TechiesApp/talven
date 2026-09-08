# Design proposals

This directory holds design proposals for Talven. A proposal is the unit of design change: it names the problem, the requirements it affects, the proposed semantics, the alternatives, the costs, and how the claim will be evaluated.

## Lifecycle

| Status | Meaning |
| --- | --- |
| Draft | Open for discussion; may change freely |
| Accepted | Direction adopted; a row is added to the [decision register](../decisions.md) |
| Rejected | Not adopted; the reason is recorded in the proposal and the register |
| Deferred | Waiting on evidence or another decision named in the proposal |
| Superseded | Replaced by a later proposal, which is linked |

Acceptance is a decision about direction. It is not evidence that anything is implemented. Implementation status lives in the documents under `docs/`, not in the proposal.

## How to submit

1. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md`, where `NNNN` is the next unused number.
2. Fill every section. Label illustrative syntax and hypothetical APIs as such.
3. Open a pull request. Discussion happens on the pull request or in a linked GitHub Discussion.
4. Maintainers set the status per [GOVERNANCE.md](../../GOVERNANCE.md).

Small ideas that are not ready for a full proposal can start as a GitHub Discussion in the Ideas category.

## Index

| Number | Title | Status |
| --- | --- | --- |
| 0000 | [Template](0000-template.md) | Template |
| 0001 | [M1a reference compiler and agent interface](0001-m1a-reference-compiler.md) | Draft |
| 0002 | [Canonical formatting and native checks](0002-canonical-formatting-and-native-checks.md) | Draft |
| 0003 | [Call-scoped borrowing](0003-call-scoped-borrowing.md) | Draft |
| 0004 | [Reproducible agent evaluation](0004-reproducible-agent-evaluation.md) | Draft |
| 0005 | [Borrowing evaluation corpus](0005-borrowing-evaluation-corpus.md) | Draft |
| 0006 | [Anthropic evaluation adapter](0006-anthropic-evaluation-adapter.md) | Draft |
