# Agent-first workflow

Status: broader proposed interfaces and evaluation plan. [M1a](prototype.md) implements bounded context lookup, structured diagnostics, and basic LSP features through one frontend. [M1b](formatting.md) adds shared CLI/LSP formatting. [M1c](borrowing.md) adds call-scoped borrow contracts to context v2 and matching LSP diagnostics/hover. [Read-only edit previews](edit-validation.md) add source/compiler revision guards and candidate diagnostics. Provider caching, persistent semantic caches, atomic file application, and comparative model evaluations remain future work.

## Optimize completed work

A language is useful to an agent when the agent can understand a small relevant context, make a correct change, and get precise feedback quickly.

Count input context, generated code, diagnostics, repair loops, tests, tool calls, latency, and success rate. Keep raw token counts separate from provider billing and cached-token discounts. Subscription consumption must not be inferred from API token prices.

Familiar identifiers, conventional control flow, one formatter, and a limited number of equivalent constructs are initial hypotheses. Extremely short names or dense punctuation may increase mistakes and need tokenizer-specific evaluation.

## Compiler-generated context

A context request should be able to return a bounded view of:

- The requested symbol's signature, types, ownership, and effects.
- Direct dependencies and relevant callers.
- Applicable capabilities and target constraints.
- Public contracts and nearby verification evidence.
- The exact revision and context schema version.

Use stable symbol identity within a defined revision scheme, deterministic ordering, and dependency-aware invalidation. Expand implementations only when the task needs them.

The current context v2 reports copy/move/shared-borrow/exclusive-borrow parameter modes, call scope, nonescape, and permitted mutation. Mutation permission is not a complete effect analysis. Consumers must recognize the schema/profile and obtain fresh context after changing source or upgrading the compiler.

Comments and natural-language summaries may supplement these facts. They cannot override checked semantics.

## Proposed tool operations

These names describe capabilities. The prototype implements context/diagnostic queries and a bounded [edit snapshot/validation interface](edit-validation.md); broad impact analysis and protected execution remain proposals:

| Operation | Purpose |
| --- | --- |
| Context lookup | Retrieve checked context for a symbol, target, and bounded task |
| Diagnostic query | Return stable diagnostic codes, locations, causes, and relevant constraints |
| Edit proposal | Prepare a small change against an expected source revision |
| Edit validation | Parse and type-check the resulting program; check affected contracts |
| Impact query | Identify changed public interfaces, effects, dependencies, and relevant tests |
| Verification | Run the applicable checks in a restricted execution environment |

A diagnostic should explain why a borrow, capability, type, or task lifetime is invalid. Suggested fixes must themselves be checked; an automatically generated fix is not proof of correctness.

Revision checks must prevent stale edits from overwriting unrelated changes. The same rule applies to multiple agents working concurrently.

The current edit validator is read-only. It checks full candidates against exact source/compiler hashes, permits repairs of invalid source, and compares checked declarations and direct-call sets when both versions are valid. Re-reading input files detects observed changes but is not atomic compare-and-swap. An applying host still needs independently enforced writer coordination, fresh identities and independent task acceptance. An empty declaration comparison does not mean unchanged behavior.

## Three different caches

| Cache | What it reuses | Required limits |
| --- | --- | --- |
| Provider prompt cache | Provider-supported repeated request content, often matching a prefix | Provider-specific eligibility, retention, routing, tokenizer, and billing behavior |
| Semantic context cache | Compiler-derived symbol and dependency information | Source, dependency, compiler, target, policy, and schema versions |
| Build cache | Compiled or intermediate artifacts | Complete build inputs, flags, toolchains, environment assumptions, and trust checks |

A source hash is an identifier, not a way for an LLM to recover missing source content. Prompt caching does not mean a model has permanently learned the language or repository.

Put stable language rules and module interfaces before task-specific material when compatible with the provider. Keep a provider-independent path that works without prompt caching.

Cache integrity and isolation matter. Do not share secrets across users or projects through caches, and do not let a cached successful check replace verification under a changed policy.

## Human LSP

Prioritize incremental parsing and diagnostics, completion, definition, references, rename, formatting, documentation, and contextual ownership/effect information.

Use the compiler's semantic model for both human and agent tooling so they do not disagree about types or permissions. Editor responsiveness and context retrieval latency are explicit evaluation criteria.

The implemented formatter uses the shared parser without requiring successful type checking. It preserves tokens/comments and returns version-independent LSP text edits; clients must discard a formatting response if their document changed. Exact source/context hashes must be refreshed after an applied edit. The CLI's freshness checks are not atomic compare-and-swap enforcement.

## Protected agent execution

The agent can read allowed context, propose patches, and execute approved classes of tools in a restricted workspace. It must not gain production credentials or release-signing authority merely by editing source or repository policy.

Retrieved documentation, package content, compiler inputs, and tool output are untrusted input. Instructions found there do not authorize new actions.

Repository agent guidance is advisory. Real restrictions require an independent executor, build policy, or platform boundary the agent cannot rewrite.

## Model compatibility

Use ordinary source text and documented, compact tool schemas. Evaluate several current open and proprietary models with a pinned specification in context.

No proprietary tokenizer, vendor-only model feature, fine-tuning requirement, or assumed permanent model memory should be necessary for basic use. Optional provider adapters may improve efficiency without defining program semantics.

## Initial experiments

Compare a small proposed syntax against equivalent Rust, C, and TypeScript tasks where comparison is meaningful. Include unfamiliar API use, a type change, an ownership error, a concurrency fix, and a security-relevant dependency change.

Give each system the same task and verification criteria. Report failure rates and repair costs, not just the shortest successful example.
