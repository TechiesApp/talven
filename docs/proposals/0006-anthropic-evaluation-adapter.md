# Proposal 0006: Anthropic evaluation adapter

- Status: Draft
- Author(s): Talven contributors
- Requirements affected: R01, R02, R04, R05, R06
- Decisions affected: D01, D03, D17, D29, new D31
- Discussion: Pull request introducing this proposal

## Problem

The provider-neutral harness and two independent corpora can verify scripted repairs, but a provider integration is still needed before controlled model trials. Provider-specific message structure, failure semantics, and usage definitions must not silently change the meaning of an experiment.

## Proposal

Add an optional Anthropic Messages command adapter, selected by the project owner. Keep the runner, compiler, and both corpora unchanged. Use standard-library HTTPS with one request per attempt, explicit live/fixture modes, declared model/settings, bounded input/output, and no retries or tools. Configuration creation is offline and records absolute commands and artifact paths. The runner hashes and archives those artifacts before execution.

Forward the original system prompt and conversation without added instructions. Request structured source-edit JSON. Extract candidate text separately from usage receipts: invalid completed edit JSON can enter the existing repair loop, while refusal, truncation, HTTP/transport failure, and unsupported response blocks terminate the trial as errors. Preserve valid usage even when no candidate is accepted. Model-produced accounting fields have no authority.

Normalize total input from uncached, cache-creation, and cache-read components only when all are known. Cache reads remain a subset; output totals already include thinking. Unknown components and dollar charges remain null. Preserve sanitized receipt details, identifiers, response hash, and the exact translated request hash. Do not log credentials or raw provider error explanations.

Synthetic Messages fixtures exercise the same translation for one original-corpus task and one borrowing task in both context modes. Fixtures have no network or credential path and always suppress normalized usage. Keep independent native acceptance and historical tests intact. The [adapter guide](../../experiments/adapters/README.md) defines the executable interface and links the official API sources consulted.

## Examples

The guide provides runnable offline commands for `strict-type` and `borrow-permission`. Each fixture supplies a failing first candidate and a hand-written repair, then the runner independently reverifies the result. The live configuration example creates a file only and uses an illustrative model placeholder. No live model result is supplied by this proposal.

## Alternatives considered

- A provider SDK would simplify broad feature support but introduce a dependency and default retries to audit. The narrow, single-request HTTP boundary is sufficient here.
- Putting provider behavior in the runner would couple experiment semantics to one API. A command adapter preserves the existing protocol.
- Counting only the provider's uncached field would undercount input when caching occurs. Treating missing counts as zero would manufacture evidence.
- Executing a paid pilot now would combine integration validation with model/budget choices. Offline verification keeps those decisions separate.

## Costs and implications

- Agent context: original guides/history remain unchanged; the API schema adds provider-side request material captured by the payload hash and eventual provider usage. There is no token-savings claim.
- Runtime and memory: bounded HTTP/JSON buffers and an adapter subprocess; no Talven runtime or compiler changes.
- Security: fixed HTTPS endpoint, environment-owned key, explicit live execution, sanitized metadata, no redirects/retries/tools. These controls do not replace host isolation or account spending limits.
- Targets: Python 3.11+ adapter; the existing native acceptance still requires its C11 toolchain and actual target evidence.
- Interoperability: only direct Anthropic Messages text/JSON output is in scope. No claim covers every model, cloud provider, or future API revision.

## Evaluation

Mock every network/authentication interaction. Test history preservation, strict settings, input/response caps, cache accounting, partial/malformed receipts, thinking/text extraction, failed calls, invalid candidate repair, secret-safe errors, fixture selection, and exclusive config creation. Run fixture integration with networking blocked, both context modes, both selected tasks, archived-byte checks, and fresh independent reverification. Preserve the full existing suite, Linux targets, sanitizer runs, formatting, examples, and documentation checks. Record actual outcomes separately from planned checks in the [validation record](../anthropic-adapter-validation.md).

## Unresolved questions

Live API/model compatibility, a pinned model and tokenizer declaration, approved spending limits, billing-receipt integration, provider caching experiments, statistical sample sizes, and cross-language baselines remain open. Offline success is not evidence of agent effectiveness or completion of the M1 gate.
