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
