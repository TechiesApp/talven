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
| 0001 | [M1a reference compiler and agent interface](0001-m1a-reference-compiler.md) | Accepted |
| 0002 | [Canonical formatting and native checks](0002-canonical-formatting-and-native-checks.md) | Accepted |
| 0003 | [Call-scoped borrowing](0003-call-scoped-borrowing.md) | Accepted |
| 0004 | [Reproducible agent evaluation](0004-reproducible-agent-evaluation.md) | Accepted |
| 0005 | [Borrowing evaluation corpus](0005-borrowing-evaluation-corpus.md) | Accepted |
| 0006 | [Anthropic evaluation adapter](0006-anthropic-evaluation-adapter.md) | Accepted |
| 0007 | [Freestanding Linux execution](0007-freestanding-linux-execution.md) | Accepted |
| 0008 | [Revision-checked edit validation](0008-revision-checked-edit-validation.md) | Accepted |
| 0009 | [Offline compiler and tooling baseline](0009-offline-tooling-baseline.md) | Accepted |
| 0010 | [Fast compiler and development reload](0010-fast-compiler-and-development-reload.md) | Accepted |
| 0011 | [Static text and optional console output](0011-static-text-and-console-output.md) | Accepted |
| 0012 | [Development watch and restart](0012-development-watch-and-restart.md) | Accepted |
| 0013 | [Native scalar compiler experiment](0013-native-scalar-compiler.md) | Accepted |
| 0014 | [Live pilot readiness for agent evaluation](0014-live-pilot-readiness.md) | Accepted |
| 0015 | [Mutable scalar locals](0015-mutable-scalar-locals.md) | Draft; implemented experiment |
| 0016 | [Persistent function checking](0016-persistent-function-checking.md) | Draft; implemented experiment |
| 0017 | [Current-document completion](0017-current-document-completion.md) | Draft; implemented experiment |
| 0018 | [Current-document semantic highlighting](0018-semantic-highlighting.md) | Draft; implemented experiment |
| 0019 | [Current-document call signature help](0019-current-call-signatures.md) | Draft; implemented experiment |
| 0020 | [Hosted function C units](0020-hosted-function-c-units.md) | Draft; implemented experiment |
| 0021 | [Preprocessed function units](0021-preprocessed-function-units.md) | Draft; implemented experiment |
| 0022 | [Private object reuse](0022-private-object-reuse.md) | Draft; implemented experiment |
| 0023 | [Pollable compiler commands](0023-pollable-compiler-commands.md) | Draft; implemented experiment |
| 0024 | [Pollable object builds](0024-pollable-object-builds.md) | Draft; implemented experiment |
| 0025 | [Native object watch](0025-native-object-watch.md) | Draft; implemented experiment |
| 0026 | [Local function contracts](0026-local-function-contracts.md) | Draft; implemented experiment |
| 0027 | [Current call type contracts](0027-current-call-type-contracts.md) | Draft; implemented experiment |
| 0028 | [Function body syntax reuse](0028-function-body-syntax-reuse.md) | Draft; implemented experiment |
| 0029 | [Native test manifests](0029-native-test-manifests.md) | Draft; implemented experiment |
| 0030 | [Incremental editor synchronization](0030-incremental-editor-synchronization.md) | Draft; implemented experiment |
| 0031 | [Native compact agent context](0031-native-compact-agent-context.md) | Draft; implemented experiment |
| 0032 | [Native canonical formatting](0032-native-canonical-formatting.md) | Draft; implemented experiment |
| 0033 | [Codex subscription evaluation](0033-codex-subscription-evaluation.md) | Draft; implemented experiment |
| 0034 | [Native focused context](0034-native-focused-context.md) | Draft; implemented experiment |
| 0035 | [Native read-only edit previews](0035-native-edit-previews.md) | Draft; implemented experiment |
| 0036 | [Hosted scalar C API units](0036-hosted-scalar-c-api.md) | Draft; implemented experiment |
| 0037 | [Bounded local source modules](0037-bounded-local-modules.md) | Draft; implemented experiment |
| 0038 | [Multi-file agent evaluation](0038-module-agent-evaluation.md) | Draft; implemented corpus/harness |
