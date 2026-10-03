# Codex multi-file pilot evidence

Status: retained live evidence, 3 October 2026. All eight finite module-editing
trials passed at the first attempt. Both conditions reached a correctness ceiling;
the added context increased input tokens and did not demonstrate lower agent cost.

The [archive](../experiments/results/pilot-codex-modules-20261003/README.md) retains
exact requests, adapter responses, accepted sources, restricted model catalog,
[run identities](../experiments/results/pilot-codex-modules-20261003/run.json),
[report](../experiments/results/pilot-codex-modules-20261003/report.json) and
[fresh reverification](../experiments/results/pilot-codex-modules-20261003/reverified.json).
Private local execution paths/transcripts are omitted from public summaries;
original hashes and exact model/source artifacts remain retained.

## Method and acceptance

[Proposal 0038](proposals/0038-module-agent-evaluation.md) defines the controlled
`m1-module-tasks-v1` corpus. Each task edits only `pipeline`, in an entry importing
aliases from two immutable dependencies. Three equally shaped records have distinct
nominal identities. The eight/twelve required stages cover exclusive/shared
borrows, by-value moves and scalar-only calls. Mutated temporary fields must be
copied back before the next stage, and each actual helper return must feed it.

Both conditions receive the same instructions, entry/dependency sources, core guide
and [module guide](module-reference.md). Only the compiler condition adds fresh
focused `talven.project-context.v1` or original-file diagnostics. Initial context
is 21,916 UTF-8 bytes, within the selected 65,536-byte budget. This measures adding
reference project context; it does not test replacing source with shorter interfaces,
native focused context or native edit previews.

The shared project frontend checks types/moves/loans. The trusted C11 driver checks
24 input rows, executed exported-helper order/count/arguments, independent final
values and all final account fields. Separate probes perturb each stage's actual
return and propagate it through the oracle, rejecting ignored returns and inline
recomputation. There were 88 successful native acceptance executions across the
eight initial candidates, followed by fresh acceptance of every final candidate.
These finite tests cannot prove arbitrary correctness or prevent public-corpus overfitting.

## Recorded configuration

| Input | Recorded value |
| --- | --- |
| Compiler/harness revision | `dc5cba341d427b812133b170f2420ac3d5d87636`, clean tree |
| Compiler/profile | `0.5.0-dev`, `m1-local-modules-v1` |
| Model selector/provider | `gpt-6-astra`, `openai-codex-cli` through ChatGPT login |
| Effort/transport | `low`, pinned `codex-cli 0.154.0`; executable/catalog SHA-256 in archive |
| Provider snapshot/tokenizer | Not exposed; unknown |
| Host | Apple M4, `Mac16,1`, arm64 Darwin `27.0.0`, 10 logical CPUs |
| Python | CPython `3.14.7` |
| Native compiler/target | Apple clang `21.0.0`, `arm64-apple-darwin27.0.0`; executable SHA-256 retained |
| C flags | `-std=c11 -O2` |
| Trial plan | 2 tasks × 2 conditions × 2 repetitions, seed `20261003` |
| Bounds | 1 repair maximum per trial; 16 invocation cap; 900-second adapter, 120-second verifier, 5-second native-command, 3600-second task deadlines |
| Actual calls | 8; no setup-model calls, repairs or infrastructure failures in this run |
| Tools available to model | Text-only edit response; tools/apps/plugins/hooks disabled by pinned adapter |
| Dollar cost | Unknown; invocation cap is not a dollar/token/quota guarantee |

Hardware model/CPU were read from the host, without device identifiers. Usage comes
from Codex CLI `turn.completed` receipts. Input tokens include any cache-read tokens;
all eight receipts reported zero cache reads. Cache-write usage was unavailable.
Engineering-session/reviewer-agent usage is outside this experiment's accounting.

## Observations

| Condition | Correct trials | First-attempt passes | Repairs/errors | Input tokens | Output tokens | Mean whole-trial seconds |
| --- | --- | --- | --- | --- | --- | --- |
| Source | 4/4 | 4/4 | 0/0 | 46,416 | 1,870 | 25.6 |
| Source + compiler context | 4/4 | 4/4 | 0/0 | 73,126 | 1,870 | 27.9 |
| Total | 8/8 | 8/8 | 0/0 | 119,542 | 3,740 | — |

Four matched pairs both passed; no discordant pair exists, so the report leaves
the exact McNemar p-value undefined. The 95% Wilson interval for aggregate
correctness is approximately 67.6%–100%, and each condition's is 51.0%–100%.
These descriptive intervals do not establish population independence for two
related tasks under one model selector.

Added context used 26,710 more input tokens (about 57.5%) with equal output totals.
The observed mean whole-trial time includes model and native verification; its
small condition difference is not a reliable causal latency result. Dollar/tokenizer
unknowns prevent priced comparisons. All eight exact sources passed
`python3 -m talven fmt FILE --module --check`; formatting is not task acceptance.

## What remains

This pilot verifies useful module edit cases and the measurement pipeline. It
does not demonstrate a context benefit, cross-language advantage, native tooling
benefit, general model coverage or M1 completion. Subsequent work needs tasks with
discriminating failures, larger/more varied graphs, interface substitution as a
separately controlled condition, tool-based edits and enough repetitions/models
to assess correctness and total cost. The preceding pilots remain separate
evidence with their original denominators and failures.
