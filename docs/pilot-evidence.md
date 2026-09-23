# Live pilots: Claude Opus 5.5

Status: actual results of two controlled pilot runs on 24 September 2026, the first live model evidence for the [evaluation harness](../experiments/README.md). They validate the pipeline end to end and show that a frontier model learns Talven's rules from one page. They are **not** a comparison of the source-only and compiler-context conditions: every trial passed in both, so there is nothing to separate them.

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

## Second pilot: the hard corpus

To get below the ceiling, the [hard corpus](../experiments/README.md#hard-corpus) (`m1-hard-tasks-v1`) asks for eight tasks where habits from other languages fail in Talven:
- loops, which do not exist;
- shadowing, including of parameters;
- `else if`;
- `let mut` on a scalar;
- implicit reborrows;
- reading a field after moving its record;
- intermediate `i32` overflow: `a * b / gcd`, negating the most negative value, and squaring an unreduced base.

One task repairs a program containing six such errors at once.

The run used Claude Opus 5.5 through the same transport, from clean revision `6314fee`: both conditions, 2 repetitions, up to 2 repairs, at efforts `low` and `high`. Records are in [`experiments/results/pilot-hard-opus-5-5-20260924`](../experiments/results/pilot-hard-opus-5-5-20260924/).

| Effort | Condition | Passed | First-attempt passes | Input tokens | Output tokens | List-price cost (USD) |
| --- | --- | --- | --- | --- | --- | --- |
| low | source | 16 / 16 | 16 | 80,509 | 9,589 | 0.313756 |
| low | compiler | 16 / 16 | 16 | 96,269 | 10,314 | 0.478937 |
| high | source | 16 / 16 | 16 | 92,025 | 14,243 | 0.425752 |
| high | compiler | 16 / 16 | 16 | 110,223 | 15,299 | 0.571373 |

All 64 trials passed on the first attempt. This includes the six-error repair in the source-only condition, where the model saw no diagnostic at all. Both archives reverified with matching verdicts and toolchain. The total was $1.79 at list-price equivalent: $0.025 per task at `low` and $0.031 at `high`.

What this shows:

- **The one-page reference is enough for this model to avoid other languages' habits.** It never produced shadowing, `else if`, a scalar `let mut`, an implicit reborrow, or an overflowing intermediate. It also recursed by halving where a loop is impossible.
- **Compiler context was pure overhead here.** It cost about 20% more input tokens at both effort levels, with no correctness difference. For a frontier model on programs this small, the source and the reference already carry the information the context adds.
- **The comparison still has no discordant pairs.** Separating the conditions needs weaker models, larger programs, or tasks whose facts are only in compiler output. The corpus stays in the repository for exactly those runs.

## Next steps

For a frontier model, neither corpus is hard enough to separate the conditions. The next runs should use smaller or cheaper models (for example Claude Haiku 4.5 or Sonnet 5) on the hard corpus. They should also use tasks whose needed facts live across many functions or only in compiler output, such as larger multi-file programs once modules exist. Choose repetition counts from the variance those runs show.
