# Proposal 0014: Live pilot readiness for agent evaluation

- Status: Accepted by the project owner on 24 September 2026; implemented in the evaluation harness
- Author(s): Talven contributors
- Requirements affected: R01, R02, R05; see [requirements](../requirements.md)
- Decisions affected: D29–D31, new D42; see [decisions](../decisions.md)
- Discussion: Implementation pull request

## Problem

The roadmap's next M1 step is a paid pilot with a pinned model. An audit of the harness found that such a pilot would not have produced trustworthy evidence:

- **The control was contaminated.** Source-only repairs received the compiler's diagnostic text as feedback, and two starting sources contained comments naming the expected diagnostic (`// E0201: …`). After one repair the two conditions were nearly the same.
- **Cost was always unknown.** The Anthropic adapter hard-coded `model_cost_usd` to null, so the primary metric, cost per correct task, could never be computed.
- **The adapter did not match current models.** It made non-streaming calls with a 30 s timeout and a 2048-token cap, accepted sampling parameters that current models reject, could not pin effort or thinking, and scored a cut-off answer as an infrastructure error.
- **The design could not support conclusions.** Trials ran in a fixed order with source-only always first. Infrastructure errors counted as incorrect answers, the report had no uncertainty or paired analysis, `reverify` checked for "all passed" instead of "matches the archive", and child processes inherited the API key.

## Proposal

The [experiment guide](../../experiments/README.md) and [adapter guide](../../experiments/adapters/README.md) specify the implemented contract.

1. **Clean control.** Add the default corpus `m1-agent-tasks-v2`: the same task IDs, instructions and acceptance as `m1c-agent-tasks-v1`, starting from copies without diagnostic comments. After a frontend rejection, source-only repairs are told only that the language checks rejected the candidate. The compiler condition still receives the diagnostic. v1 stays selectable so archived runs can be reverified.
2. **Priced cost.** A pinned, hashed [pricing table](../../experiments/adapters/anthropic-pricing.json) computes `model_cost_usd` from each usage receipt: uncached input, cache writes by TTL, cache reads, and output. Missing prices or an unpriced cache-write TTL leave the cost null. Cache writes are reported as their own subset of input tokens. List prices are not billing receipts; the table records its source and must be checked before a paid run.
3. **Current API behavior.** The adapter streams responses and accepts `max_tokens` up to 128000 (default 32000). It pins `output_config.effort` (required for live configs) and optional adaptive thinking, and rejects `temperature`/`top_p` for models that return a 400 on them. A `max_tokens` cut-off or a refusal is a failed attempt the runner may repair, with feedback naming the stop reason. Connection failures and 408/429/5xx/529 responses are retried up to three times, honoring `retry-after`. A stream that has started is never retried, because it may be billed. The runner replays the model's own text in repair turns.
4. **Run discipline.** Trials run in a seeded, recorded order that interleaves tasks and conditions (`--fixed-order` restores declaration order). Live runs require `--max-cost-usd` and a clean working tree. The run stops before any call where the spend so far plus the most expensive call so far would exceed the cap, and stops outright after a call whose cost is unknown. The verifier, C compiler, and candidate programs get an allow-listed environment without credentials. Candidate programs also run under CPU-time and file-size limits.
5. **Reporting.** Reports add correctness excluding infrastructure errors, with a 95% Wilson interval, and a paired comparison by task and repetition with an exact McNemar test. Pairs with an infrastructure error are excluded and counted. `reverify` compares fresh verdicts and the C compiler hash against the archive, and succeeds when the archive reproduces, including recorded failures.

## Alternatives

- *Remove diagnostics from `examples/invalid`.* Those comments teach human readers; a separate corpus keeps both uses and preserves v1 archives.
- *Give source-only repairs no feedback at all.* That conflates "no compiler" with "no test harness"; both conditions still learn pass or fail.
- *Import billing receipts instead of list prices.* Billing exports lag and are not per-request. List-price cost is labeled with its provenance and can be superseded by `report --verification-costs`-style receipts later.
- *Use the Anthropic SDK.* The harness is deliberately standard-library-only and provider-neutral; streaming over `http.client` keeps that property.

## Costs and risks

Streaming parsing and retries add code to a trusted adapter. A spend cap based on the largest call so far can still be overshot by one unusually expensive call; the cap bounds planning, not billing. The pricing table goes stale and must be re-verified. Randomized order changes nothing for offline fixtures but makes live runs depend on the recorded seed for reproduction.

## Validation

Offline tests cover:

- streamed assembly, early stream end, and retry scheduling;
- cost arithmetic for every token class, and sampling and effort validation;
- cut-offs and refusals as repairable attempts;
- source-only feedback without diagnostic text;
- seeded order, budget stop rules, and credential-free child environments with CPU limits;
- paired statistics, and archive-matching reverification.

The CI fixture runs exercise the v2 corpus. No live model call, measured cost, or model result is claimed.

## Remaining before a paid pilot

The owner must pick the pinned model and effort, approve a spend cap, and verify the pricing table. The corpus is still eight tasks. A pilot of this size can show whether the pipeline works end to end, but it cannot detect realistic differences between conditions. Choose repetitions and corpus growth from the pilot's observed variance before making comparative claims.
