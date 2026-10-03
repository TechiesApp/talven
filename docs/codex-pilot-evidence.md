# Current-profile Codex pilot

Status: actual live observation on 3 October 2026. Six trials passed on their first attempt, with fresh independent native reverification. This establishes compatibility on these inputs, not general correctness, token savings or cost superiority.

The retained [archive](../experiments/results/pilot-codex-current-20261003/README.md) contains exact requests, adapter responses, accepted sources, the restricted model catalog, [run identities](../experiments/results/pilot-codex-current-20261003/run.json), [report](../experiments/results/pilot-codex-current-20261003/report.json), [reverification](../experiments/results/pilot-codex-current-20261003/reverified.json) and [setup receipts](../experiments/results/pilot-codex-current-20261003/setup.json). Local command paths and nested process transcripts are omitted from the public summaries; complete local archives remain separate.

## Method

| Item | Recorded value |
| --- | --- |
| Model selector / effort | `gpt-6-astra` / `low`; returned backend snapshot unavailable |
| Transport | Codex CLI 0.154.0 through ChatGPT login; executable/catalog hashes retained |
| Trusted revision | `1aa02fc2b30a5817e7198738b919d365f08633b1`, clean |
| Language | `m1-scalar-mutation-v1`, reference compiler `0.5.0-dev` |
| Corpus | Existing `m1-large-tasks-v1`; `pipeline-80`, `pipeline-140`, `pipeline-200` |
| Conditions | Source-only and compiler context, one repetition, seed 0 interleaving |
| Edit / context bounds | Only `pipeline`; 16384 additional context bytes; at most one repair per trial |
| Final run guard | Seven adapter invocations maximum; six used |
| Native acceptance | macOS ARM64, CPython 3.14.7, Apple clang 21.0.0, C11 `-O2` |
| Start | `2026-10-03T08:03:59.298866+00:00` |

The [adapter](../experiments/adapters/codex_cli.py) follows [Proposal 0033](proposals/0033-codex-subscription-evaluation.md): fresh ephemeral read-only sessions, pinned guide replacing built-in instructions, no project/user instruction injection, restricted tools and strict terminal receipts. Both conditions use identical transport framing. Model and tokenizer snapshot identities are not exposed by this CLI.

The unchanged large-task verifier checks protected declarations, required stages, and both result and final account state over 24 native inputs per candidate. Every retained candidate passes canonical-format checks. All six fresh native reverifications pass with the original C toolchain identity. The model returned mutable scalar running values, which the current profile permits; this is not evidence that mutable syntax caused a repair reduction.

## Observation

| Condition | First-attempt / final acceptance | Repairs | Input tokens | Cache-read subset | Output tokens |
| --- | --- | --- | --- | --- | --- |
| Source-only | 3/3 | 0 | 43637 | 17664 | 394 |
| Compiler context | 3/3 | 0 | 50920 | 0 | 394 |
| Total | 6/6 | 0 | 94557 | 17664 | 788 |

Token values come from CLI `turn.completed` receipts, not a local tokenizer. Cache-read tokens are included in input tokens and must not be added again. Cache-write tokens, model/tool dollars, verification costs and cost per correct task remain unknown. Subscription login does not supply a billing receipt.

All three pairs passed in both conditions; there are no discordant pairs. The additional compiler context increased reported input on these samples without a measurable correctness change. The conditions have different cache reuse after earlier setup calls, and the finite public tasks hit a ceiling. These observations cannot establish causal token/cost benefits or compare Codex with historical Anthropic pilots on an older profile.

## Setup failures and total usage

The first eight invocations were rejected because the adapter treated a CLI startup-warning item as an error. A ninth diagnostic invocation identified the warning for `skip_host_skill_discovery`. Codex returned a candidate, but the original rejected outcome is retained; it is not retrospectively scored as accepted. The adapter now suppresses the known unstable-feature startup warning while continuing to reject actual error/tool items. The final six trials used fresh calls after that correction.

Setup used 128507 input and 1127 output tokens. Together with the final trials, all **15** invocations used **223064 input and 1915 output tokens**, within the stated sixteen-invocation plan. These totals include failed integration work; dollar totals remain unknown. The six-trial acceptance result excludes the nine setup infrastructure failures, which remain visible in the archive.
