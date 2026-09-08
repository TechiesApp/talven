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

## Preparing a future live run

Configuration creation does not call the API or read credentials. A real run requires a separately selected model, declared tokenizer identity or unavailable reason, and an approved spending budget. For example, this creates a configuration only; replace the illustrative identity before use:

~~~sh
python3 experiments/adapters/anthropic_messages.py --live \
  --model EXACT_MODEL_ID --tokenizer 'unavailable: provider tokenizer version not disclosed' \
  --max-tokens 2048 --timeout 30 --write-config build/anthropic-live.json
~~~

There is no default model. Use a model that supports JSON structured output and the selected sampling settings. Only `max_tokens` (1–32768, generator default 2048) and optionally one of `temperature` or `top_p` (0–1) are supported. Other provider settings, including thinking, effort, caching, and service tier, are omitted; their provider/model defaults apply. Model aliases and defaults may change, so record a pinned model identity where available and retain returned model metadata. The tokenizer label is provenance, not a local token-counting implementation.

Actual `--live` execution reads `ANTHROPIC_API_KEY` after validating the request. Use a workspace-scoped Console API key. Multi-workspace headers, OAuth, Bedrock, other cloud endpoints, proxies, streaming, tools, and SDK retry behavior are outside this adapter's scope. Never put a key in a config, argument, prompt, or receipt.

## Translation and accounting

The initial system message becomes the API's top-level `system`; the alternating user/assistant history is forwarded unchanged. An `output_config.format` JSON schema requests only `edits.task.tal`. No prompt suffix, provider session, tools, or extra calls are added. These choices follow the [Messages reference](https://platform.claude.com/docs/en/api/http/messages/create) and [structured-output guide](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), consulted on 8 September 2026.

The adapter hashes the exact encoded HTTP payload. The runner separately archives its original request, the adapter envelope, accepted source, and pinned adapter/fixture bytes. Selected completed text, response hash, sanitized identifiers, API version, and allowed usage fields provide audit context. Provider error explanations and arbitrary metadata/headers are not copied into archives.

Anthropic's input count excludes cache creation and cache reads. Normalize total input by summing `input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` **only when all three are known**. Normalize cached input from cache reads, as a subset of that total. Preserve partial components in receipt metadata; if total input is unknown, normalized cached input also remains unknown. Missing or null components are never assumed to be zero. Output tokens are copied directly; thinking and cache-duration details are never added again. See the provider's [cache accounting](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

Usage is parsed before accepting output. Valid components survive HTTP failures, refusals, truncation, or malformed response fields. Invalid known counts end the call as an error while retaining independently valid observations. No character-based token estimate or list-price calculation is performed. Dollar amounts remain unknown without actual billing evidence; the current adapter does not import billing receipts.

Only an assistant Message ending with `end_turn` can supply a candidate. Thinking blocks are ignored for source extraction. Tool/unknown blocks, refusal details, missing text, and other stop reasons end the trial as errors, retaining available usage. A completed text response containing invalid edit JSON is a failed candidate eligible for the runner's bounded repair loop. Model-written usage/metadata cannot replace provider receipts. Compiler, structural, and native checks remain the source of correctness.

The transport makes one verified HTTPS POST to `api.anthropic.com/v1/messages`, with API version `2023-06-01`, and never retries or follows redirects. It caps request/payload bytes at 4 MiB and response bytes at 1 MiB, and uses a configurable socket timeout up to 300 seconds. The runner adds a process deadline; neither limit is a dollar budget. A timeout or unreadable response may have consumed tokens even when no receipt was received. Such usage stays unknown. Authentication/header handling follows the [API overview](https://platform.claude.com/docs/en/api/overview); refusal and request-ID handling follows [API errors](https://platform.claude.com/docs/en/api/errors).

The trusted adapter/compiler/host boundary and public finite acceptance tests are unchanged. This increment does not add hostile-process isolation, cross-provider comparisons, statistical conclusions, or complete M1. See [Proposal 0006](../../docs/proposals/0006-anthropic-evaluation-adapter.md) and [actual offline validation](../../docs/anthropic-adapter-validation.md).
