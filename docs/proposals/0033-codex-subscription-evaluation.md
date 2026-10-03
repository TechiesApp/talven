# 0033: Bounded Codex subscription evaluation

Status: Proposed; implemented experiment. Adapter tests and live observations are separate evidence.

## Problem and scope

R01, R02 and R06 require model trials with explicit context, independent acceptance and trustworthy accounting. The owner requested Codex testing on 3 October 2026. Add an optional ChatGPT-authenticated Codex CLI transport and explicit invocation guard to the existing runner. Preserve pairing, language guides, source/edit boundaries, native acceptance, provenance and reverification.

## Transport

Pin CLI 0.154.0, its executable SHA-256, bundled model selector and reasoning effort. Archive a restricted bundled catalog with patch/experimental tool declarations removed and direct tool mode selected; disable other tools, web search, apps, plugins, hooks and host skill discovery through the pinned CLI controls. Unexpected tool events are errors.

Each attempt uses a fresh temporary directory, read-only sandboxing, ignored user configuration, zero project-document bytes, ephemeral history and forced ChatGPT login with API-key overrides removed. The runner's system message replaces built-in model instructions. Repairs use the same chronological transcript framing as the Claude CLI transport. These controls require a trusted CLI/host; they are not hostile-process isolation or an override of managed requirements.

The edit schema requests only `edits.task.tal`. Strict bounded JSONL requires one completed turn and preserves available terminal token receipts on errors. Input/cache-read/output tokens come from `turn.completed`; cache-write tokens and dollar costs remain unknown. The model selector is pinned, but returned model snapshot and tokenizer identity are unavailable.

## Invocation guard

Live runs require `--max-cost-usd`, `--max-calls`, or both. The invocation guard counts every adapter invocation once, including malformed/failed responses, and refuses another invocation at the limit. Unknown cost does not stop an explicit call-only run. When a dollar guard is selected, its unknown-cost stop remains mandatory. Invocation limits do not bound tokens, quota, billing or hidden CLI retries. Interrupted runs remain incomplete and withhold aggregate rates; historical dollar-only records keep their shape. Correct the existing unknown-usage failure path that could account one invocation twice.

## Alternatives and evidence

A direct API adapter needs separate API/pricing settings and measures a different transport. Assigning zero cost to subscription use invents evidence. Bounded CLI invocations meet the owner's requested test while retaining unknown costs.

Offline tests cover receipt bounds, unexpected tools, catalog restrictions, exact guide forwarding, removed key overrides, binary/catalog drift, failed invocations, exact limits and combined guards. Existing compiler, protected-declaration and native checks determine actual task correctness. Small public-task pilots cannot establish general savings or cross-provider superiority.

Primary sources: [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [configuration](https://learn.chatgpt.com/docs/config-file/config-reference), matching [tool registry](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/spec_plan.rs) and [model schema](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/protocol/src/openai_models.rs).
