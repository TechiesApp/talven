# Live pilots: Claude Opus 5.5, Sonnet 5, and Haiku 4.5

Status: actual results of three controlled pilot runs on 24 September 2026, the first live model evidence for the [evaluation harness](../experiments/README.md). They validate the pipeline end to end and show that a frontier model learns Talven's rules from one page. Only the third, with smaller models, separates the source-only and compiler-context conditions at all. The difference it shows is small and points against the current context format.

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

## Third pilot: smaller models on the hard corpus

The same hard corpus and design ran from clean revision `de2427c` on **Claude Sonnet 5** at efforts `low` and `high`, and on **Claude Haiku 4.5**, which does not take an effort setting. Records are in [`experiments/results/pilot-hard-sonnet-haiku-20260924`](../experiments/results/pilot-hard-sonnet-haiku-20260924/), and all three archives reverified.

| Model | Condition | First-attempt passes | Final passes | Attempts | Input tokens | Output tokens | List-price cost (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku 4.5 | source | 15 / 16 | 16 / 16 | 17 | 70,038 | 76,595 | 0.474731 |
| Haiku 4.5 | compiler | 12 / 16 | 16 / 16 | 22 | 113,576 | 90,204 | 0.677974 |
| Sonnet 5, low | source | 13 / 16 | 16 / 16 | 21 | 117,098 | 16,824 | 0.327722 |
| Sonnet 5, low | compiler | 11 / 16 | 15 / 16 | 24 | 156,118 | 12,371 | 0.409848 |
| Sonnet 5, high | source | 16 / 16 | 16 / 16 | 16 | 81,010 | 21,851 | 0.307190 |
| Sonnet 5, high | compiler | 16 / 16 | 16 / 16 | 16 | 95,741 | 28,212 | 0.444430 |

The run cost $2.64 in total at list-price equivalent.

**The traps worked.** Smaller models fell into the habits the corpus targets, then repaired them from feedback:
- **Scalar reassignment** (`x = …`), which Talven does not have, was the most common mistake (E0002).
- **Implicit reborrows** (E0304), **`let mut` on a scalar** (E0305), and **overflow traps at run time** in `digit-sum` and `pow-mod` followed.

Every trial ended in a pass except one: Sonnet 5 at `low`, with compiler context, ran out of repairs on the six-error program.

**Compiler context did not help first attempts, and may have hurt.** Five task pairs had different first-attempt outcomes between the conditions, and all five favored source-only: three for Haiku and two for Sonnet at `low`. With five discordant pairs the exact McNemar p-value is 0.06, so this is a signal to investigate, not a conclusion. The records suggest two causes:

- **First-error anchoring.** The checker reports only the first error. On the six-error program, the compiler condition's first prompt carried one diagnostic, and the model fixed that one error. The source-only condition had to read the whole program against the reference and fixed more of it.
- **Noisy context.** The compiler context is about 1.5 KB of JSON, and much of it (cache keys, hashes, runtime versions) is machine metadata. In these runs the compiler condition used 18–62% more input tokens, partly because it needed more repairs, without adding facts the source lacks.

## Next steps

1. **Report several independent errors per check,** so compiler feedback shows the whole problem instead of anchoring on the first error.
2. **Give models a compact context view:** facts only, without cache keys, hashes, or runtime versions. Measure its token cost against source-only.
3. **Rerun the smaller models with more repetitions** to confirm or refute the first-attempt effect, choosing the count from the variance above.
4. **Grow the corpus toward larger programs,** where compiler context carries facts the visible source does not.
