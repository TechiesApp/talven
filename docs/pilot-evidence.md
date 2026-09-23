# First live pilot: Claude Opus 5.5 on both corpora

Status: actual results of one controlled pilot run on 24 September 2026. This is the first live model evidence for the [evaluation harness](../experiments/README.md). It validates the pipeline end to end; it is **not** a comparison of the source-only and compiler-context conditions, which these results cannot distinguish.

## Setup

| Item | Value |
| --- | --- |
| Model | `claude-opus-5-5`, effort `high`, adaptive thinking (always on for this model) |
| Transport | [Claude Code CLI](../experiments/adapters/README.md#claude-code-cli-transport-subscription) 2.1.280 in `--safe-mode`, no tools, owner's Max subscription |
| Repository | revision `b0b5f04`, clean working tree |
| Corpora | `m1-agent-tasks-v2` (4 tasks) and `m1c-borrowing-tasks-v1` (4 tasks) |
| Design | both conditions per task, 1 repetition, up to 2 repairs, seeded order (seed 0), spend cap $10 per corpus |
| Guide | the one-page [language reference](language-reference.md) |
| Host | macOS ARM64, Python 3.14.7, Apple clang 21.0.0 for acceptance builds |

Archived run records, reports, and reverification outputs are in [`experiments/results/pilot-opus-5-5-20260924`](../experiments/results/pilot-opus-5-5-20260924/). Home and scratch directory paths are replaced with `~` and `<scratch>`. Full per-attempt transcripts were kept locally, not committed.

## Results

Every trial passed independent native acceptance on its first attempt; no repair was needed and no infrastructure error occurred.

| Corpus | Condition | Passed | Attempts | Input tokens | Output tokens | List-price cost (USD) |
| --- | --- | --- | --- | --- | --- | --- |
| agent v2 | source | 4 / 4 | 4 | 18,533 | 1,846 | 0.063628 |
| agent v2 | compiler | 4 / 4 | 4 | 21,013 | 1,779 | 0.082128 |
| borrowing | source | 4 / 4 | 4 | 19,854 | 2,664 | 0.090556 |
| borrowing | compiler | 4 / 4 | 4 | 21,946 | 1,977 | 0.093552 |
| **All** | | **16 / 16** | **16** | **81,346** | **8,266** | **0.329864** |

Per corpus, correctness was 8/8 with a 95% Wilson interval of 0.68–1.00. The paired comparison had 4 pairs per corpus, all passing in both conditions, so there is no discordant pair and no McNemar test. Of the input tokens, 62,320 were cache reads and 18,994 cache writes; the harness's system prompt is shared across calls. Per-call cost ranged from $0.0074 (`strict-type`, source) to $0.0351 (`squared-length`, compiler), and wall time from 3.9 to 13.3 seconds per trial.

Both archives reverified on the same host: all 16 fresh verdicts matched the archive, with the same C toolchain hash.

## What this shows and does not show

- **The pipeline works live.** Isolation, structured output, pricing, the spend cap, seeded order, independent acceptance, and archive reverification all behaved as specified. Model costs are priced from the pinned table and matched the CLI's own estimates.
- **The tasks are too easy for this model.** A 100% first-attempt pass rate in both conditions is a ceiling effect. It gives no evidence about whether compiler context helps.
- **Compiler context cost more input on these tasks.** The compiler condition used 13% more input tokens on the agent corpus and 11% more on the borrowing corpus, with equal correctness. With n = 4 pairs per corpus this is an observation about these tasks, not a general claim.
- **Costs are list-price equivalents.** The subscription is not billed per token. `cost_per_correct_task_usd` stays null in the reports because verification cost was not supplied. Model-only cost per correct task was $0.0182 (agent) and $0.0230 (borrowing).
- **This transport is not the raw Messages API.** The CLI adds its own system prompt and structured-output mechanism, and repairs would be rendered into one message; results are not interchangeable with API-adapter runs.

## Next steps

To make the comparison informative, the corpus needs tasks that current models fail without help: larger programs, multi-function borrow errors, and edits that need information only the compiler context provides. It also needs more repetitions and lower effort levels to move below the ceiling. Choose repetition counts from the variance observed there.
