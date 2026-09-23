# Optional provider adapters

The [evaluation harness](../README.md) stays provider-neutral. The optional [Anthropic Messages adapter](anthropic_messages.py) translates its text-only edit protocol to one Messages request per attempt. Python 3.11+ standard-library HTTP is sufficient; no provider SDK is required. Implementation and synthetic fixtures do not establish live API compatibility or model effectiveness.

## Offline verification

Run from the repository root with the usual Python/C11 toolchain. These commands need no credentials or provider connection:

~~~sh
python3 experiments/adapters/anthropic_messages.py --fixture tests/fixtures/anthropic_messages.json \
  --model fixture-messages-v1 --tokenizer 'fixture: no tokenizer' \
  --write-config build/anthropic-fixture.json
python3 -m experiments run --adapter build/anthropic-fixture.json --task strict-type \
  --context both --max-repairs 1 --out build/anthropic-type
python3 -m experiments reverify build/anthropic-type --out build/anthropic-type-reverified.json
python3 -m experiments run --corpus m1c-borrowing-tasks-v1 --task borrow-permission \
  --adapter build/anthropic-fixture.json --context both --max-repairs 1 --out build/anthropic-borrow
python3 -m experiments reverify build/anthropic-borrow --out build/anthropic-borrow-reverified.json
~~~

Use fresh config/output paths. The [fixture](../../tests/fixtures/anthropic_messages.json) contains hand-written, synthetic Messages responses for **only** `strict-type` and `borrow-permission`. Attempt 0 returns the unchanged failing source; attempt 1 returns an independently checked repair. Entries are selected by task and attempt, with no fallback or repeated last response. Missing entries and a mismatched fixture model are errors.

The fixture runs the same request/response translation as live mode, but never reads an API key or opens HTTP. Its metadata says `synthetic:true`, its envelope usage is null, and the runner records `measurement_kind:fixture`. Numeric examples inside the synthetic receipt test parsing only; **they are not measured token usage**. Fixture completion counts describe scripted harness behavior.

## Claude Code CLI transport (subscription)

[`claude_code_cli.py`](claude_code_cli.py) runs each attempt through the signed-in Claude Code CLI (`claude -p`), so a Claude subscription such as Max can be used instead of an API key. It removes `ANTHROPIC_API_KEY` from the CLI's environment so the subscription login is used.

~~~sh
python3 experiments/adapters/claude_code_cli.py --write-config build/cli-live.json \
  --model claude-opus-5-5 --effort high
python3 -m experiments run --adapter build/cli-live.json --max-cost-usd 10 --out build/cli-pilot
~~~

Each attempt is one headless session with `--safe-mode` (no CLAUDE.md, skills, plugins, hooks, or MCP servers), `--tools ""`, `--no-session-persistence`, the pinned `--model` and `--effort`, the runner's system prompt, and the edit JSON schema. The CLI cannot inject earlier assistant turns, so repair attempts render the conversation, oldest first, into one user message with labeled runner and model turns; both conditions receive the same framing. The CLI's own system prompt, structured-output mechanism and retries are part of this transport, so results are **not interchangeable with raw Messages API runs**; archives record `transport: claude-code-cli`.

Usage comes from the CLI's result record and is priced with the same [pricing table](anthropic-pricing.json); the CLI's own list-price estimate is kept as `cli_list_cost_usd` for cross-checking. Under a subscription these are **API-equivalent list-price figures, not charges**; the spend cap then limits API-equivalent usage, and subscription rate limits still apply. A response from a different model than requested is an error.

## Preparing a future live run

Configuration creation does not call the API or read credentials. A real run requires a separately selected model, explicit effort, declared tokenizer identity or unavailable reason, a verified pricing entry, and an approved spend cap. For example, this creates a configuration only:

~~~sh
python3 experiments/adapters/anthropic_messages.py --live \
  --model claude-opus-5-5 --effort high \
  --tokenizer 'unavailable: provider tokenizer version not disclosed' \
  --write-config build/anthropic-live.json
python3 -m experiments run --adapter build/anthropic-live.json --max-cost-usd 20 --out build/live-pilot
~~~

There is no default model. Live configs must pin `--effort` (`low`, `medium`, `high`, `xhigh`, `max`), because model defaults differ and change. Optional settings are `--max-tokens` (1–128000, default 32000), `--thinking` (adaptive), and one of `--temperature` or `--top-p` for models that accept sampling parameters; Opus 4.7 and later, Opus 5.x, Sonnet 5, and Fable/Mythos models reject them, so the adapter refuses those combinations. A live config also requires the model in the [pricing table](anthropic-pricing.json). The tokenizer label is provenance, not a local token-counting implementation.

Actual `--live` execution reads `ANTHROPIC_API_KEY` after validating the request. Use a workspace-scoped Console API key. Multi-workspace headers, OAuth, Bedrock, other cloud endpoints, and tools are outside this adapter's scope. Never put a key in a config, argument, prompt, or receipt.

## Translation and accounting

The initial system message becomes the API's top-level `system`; the alternating user/assistant history is forwarded unchanged. An `output_config.format` JSON schema requests only `edits.task.tal`, alongside the pinned `output_config.effort` and optional `thinking: {type: adaptive}`. No prompt suffix, provider session, tools, or extra calls are added. These choices follow the [Messages reference](https://platform.claude.com/docs/en/api/http/messages/create) and [structured-output guide](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

The adapter hashes the exact encoded HTTP payload. The runner separately archives its original request, the adapter envelope, accepted source, and pinned adapter/fixture/pricing bytes. Selected completed text, response hash, sanitized identifiers, API version, retries, and allowed usage fields provide audit context. Provider error explanations and arbitrary metadata/headers are not copied into archives.

Anthropic's input count excludes cache creation and cache reads. Normalize total input by summing `input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` **only when all three are known**. Cache reads and cache writes are separate reported subsets of that total. Preserve partial components in receipt metadata; missing or null components are never assumed to be zero. Output tokens are copied directly; thinking and cache-duration details are never added again. See the provider's [cache accounting](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

`model_cost_usd` is computed from the receipt and the pinned [pricing table](anthropic-pricing.json): uncached input, 5-minute and 1-hour cache writes, cache reads, and output, each at its USD-per-million rate. It is null when the model has no entry, any component is unknown, or cache writes lack a TTL breakdown. `model_cost_source` names the table file, its SHA-256, and its documented source. These are **list-price estimates, not billing receipts**; check the table against the [pricing page](https://www.anthropic.com/pricing) before a paid run and update it when prices change.

A Message ending with `end_turn` can supply a candidate. A `max_tokens` cut-off or a refusal is recorded as `model_failure`; no edit is accepted and the runner may repair. Thinking blocks are ignored for source extraction. Tool or unknown blocks, inconsistent refusal details, missing text, and other stop reasons end the trial as errors, retaining available usage. A completed text response containing invalid edit JSON is a failed candidate eligible for repair. Model-written usage/metadata cannot replace provider receipts. Compiler, structural, and native checks remain the source of correctness.

The transport streams one HTTPS POST to `api.anthropic.com/v1/messages` with API version `2023-06-01` and never follows redirects. Connection failures before response headers, and 408/429/500/502/503/504/529 responses, are retried up to three times after `retry-after` or exponential backoff (capped at 60 s) and recorded in `retries`; these calls produce no model output. A stream that has started is never retried: an error event or early end is a `stream_error` whose usage stays unknown because tokens may have been consumed. Request/payload bytes are capped at 4 MiB and response bytes at 1 MiB; `--timeout` (up to 600 s, default 300) bounds connecting and each streamed read. The runner adds a process deadline (`--adapter-timeout`) and the spend cap.

The trusted adapter/compiler/host boundary and public finite acceptance tests are unchanged. This increment does not add hostile-process isolation, cross-provider comparisons, statistical conclusions, or complete M1. See [Proposal 0006](../../docs/proposals/0006-anthropic-evaluation-adapter.md) and [actual offline validation](../../docs/anthropic-adapter-validation.md).
