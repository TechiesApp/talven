# Current-profile Codex hard-task follow-up

Status: actual live observation on 3 October 2026. Eight trials passed on their first attempt and reproduced under fresh independent native verification. This broadens finite task coverage after the [large-program pilot](codex-pilot-evidence.md); both conditions again hit a ceiling.

The [public archive](../experiments/results/pilot-codex-hard-20261003/README.md) retains exact requests, adapter responses, accepted sources, restricted catalog, [run identities](../experiments/results/pilot-codex-hard-20261003/run.json), [report](../experiments/results/pilot-codex-hard-20261003/report.json) and [native reverification](../experiments/results/pilot-codex-hard-20261003/reverified.json). Public summaries remove local command paths and nested process transcripts; raw CLI diagnostics remain local. All request/response/source hashes were checked, and every retained source passes canonical-format checks.

## Method

| Item | Recorded value |
| --- | --- |
| Model selector / effort | `gpt-6-astra` / `low`; returned backend snapshot and tokenizer unavailable |
| Transport | Codex CLI 0.154.0 through ChatGPT login, same pinned restricted catalog and adapter as the preceding pilot |
| Trusted revision | `38116913e1080601243bf5e96420860127c5b258`, clean |
| Language | `m1-scalar-mutation-v1`, compiler `0.5.0-dev` |
| Corpus / selection | Existing `m1-hard-tasks-v1`: `lcm-no-overflow`, `digit-sum`, `pow-mod`, `multi-error-repair` |
| Conditions | Source-only and existing reference compact compiler context/diagnostics; one repetition, seed 0 interleaving |
| Bounds | Whole-file edits, 16384 additional context bytes, at most one repair per trial |
| Invocation guard | 16 adapter invocations maximum; eight used; no infrastructure failures in this run |
| Acceptance | Independent task structure/native values with macOS ARM64, CPython 3.14.7, Apple clang 21.0.0, C11 `-O2` |
| Start | `2026-10-03T09:26:06.878255+00:00` |

The compiler/harness/input hashes and original CLI/catalog/C toolchain fingerprints are retained. The one-page guide and task sources are the already-public baseline bytes; private chat and user configuration are not injected. The same text-only transport restrictions from [Proposal 0033](proposals/0033-codex-subscription-evaluation.md) apply. These conditions use the existing reference prompt view; this run does not evaluate native focused context or edit-preview benefits.

The selected tasks require dividing before multiplying to avoid representable-LCM intermediate overflow, handling `INT32_MIN` digit magnitudes without negating that value, logarithmic recursion for large exponents, and repairing several syntax/type/borrowing mistakes while preserving intended behavior. The unchanged verifier uses independent C checks of boundary and representative inputs, required declarations/calls and resource mutations. Passing finite checks does not prove all-domain correctness.

## Observation

| Condition | First-attempt / final acceptance | Repairs | Input tokens | Cache-read subset | Output tokens |
| --- | --- | --- | --- | --- | --- |
| Source-only | 4/4 | 0 | 38797 | 8832 | 1018 |
| Compiler context | 4/4 | 0 | 39070 | 8832 | 999 |
| Total | 8/8 | 0 | 77867 | 17664 | 2017 |

Usage comes from CLI `turn.completed` receipts. Cache reads are included in input tokens, not additional tokens. Cache-write counts, dollar costs, verification costs and cost per correct task remain unknown. Invocation caps do not bound quota, tokens or internal retries.

Both conditions pass every pair; there are no discordant outcomes or measurable repair/correctness differences. Reported token differences are small finite observations with uncontrolled cache/scheduler effects, not causal token or cost savings. The harder algorithmic selection still fails to distinguish context effectiveness for this model. More discriminating workload design, repetitions and controlled cache framing remain open. No additional model calls were made after this eight-call run.

Fresh local replay reproduced all eight outcomes with the original C compiler identity, and the normalized public archive itself also reproduced. A separate current-compiler regression test runs all eight retained candidates under required native CI; future results are fresh target evidence, not replacements for the historical run. Historical comparisons with other transports/models/profiles remain separate.
