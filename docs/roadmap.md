# Roadmap and evidence gates

Status: proposed sequence. There are no committed dates, staffing estimates, or performance claims.

## M0: Design baseline

Deliver a traceable requirement set, a minimal grammar proposal, ownership rules, capability boundaries, target definitions, and an agent evaluation protocol.

Gate: reviewers can distinguish product requirements from proposals and identify unresolved semantics. The specification is short enough to give to an unfamiliar model.

Current repository contribution: requirements and architecture are documented. The [M1a guide](prototype.md) defines a small implemented grammar and affine value rules, with an [executable agent evaluation protocol](../experiments/README.md). The runner owns source-edit acceptance and records reproducible inputs; hostile-process isolation and a complete language specification remain unfinished.

## M1: Small native subset with agent tooling

Initial increment: **M1a reference compiler**. Implemented parsing, strict scalar types, affine scalar-field records, functions, conditionals, structured diagnostics, deterministic bounded context, C11 lowering, and a basic LSP. See [actual validation](prototype-validation.md). This increment does not complete the full M1 gate.

Developer test workflow: [Proposal 0029](proposals/0029-native-test-manifests.md) adds bounded [native test manifests](testing.md) using the shared frontend and ordinary C lowering, with explicit full signed main-result/output or first-diagnostic expectations. It supplies a test command for the implemented single-file subset; package/documentation tooling and broader M1 evaluation gates remain open.

Following increment: **M1b formatting and native checks**. The CLI and LSP share a token-preserving canonical formatter, with explicit file writes and structured check diagnostics. Native CI declares Linux x86-64 and ARM64 jobs; see [M1b scope](formatting.md) and [its execution evidence](formatting-validation.md). The next increment, **M1c call-scoped borrowing**, implements shared/exclusive record parameters, field mutation, source-order native lowering, and context v2; see [its scope](borrowing.md) and [validation](borrowing-validation.md). Controlled model evaluation remains open.

Prototype parsing, strict types, functions, basic data types, a limited ownership model, deterministic diagnostics, a formatter, and compiler-derived context lookup.

Compile and run a useful small program on the first ARM64 and x86-64 hosts. Keep the source of truth shared between CLI, LSP, and agent interfaces from the beginning.

Gate: a model can make a bounded change using a fixed context budget, and independent checks establish correctness. Invalid ownership and type examples fail predictably.

Evaluation increment: [Proposal 0004](proposals/0004-reproducible-agent-evaluation.md) implements the provider-neutral four-task harness, source-only/compiler-context trials, bounded repairs, independent structural/native checks, archived provenance, and token/cost accounting that preserves unknown values. Scripted fixtures validate execution; controlled live model results remain open, so this does not complete the M1 gate.

Borrowing evaluation increment: [Proposal 0005](proposals/0005-borrowing-evaluation-corpus.md) adds a separately versioned four-task corpus for overlapping loans, missing write permission, explicit reborrowing, and evaluation order. The original corpus remains the default. Independent checks include mutation, call order, and dependence on helper return values; both corpora can be exercised offline. See [actual borrowing evaluation validation](borrowing-evaluation-validation.md). Provider integration increment: [Proposal 0006](proposals/0006-anthropic-evaluation-adapter.md) adds an optional [Anthropic Messages adapter](../experiments/adapters/README.md) with synthetic protocol fixtures, explicit live execution, and receipt-aware accounting. Live API compatibility and model results remain unmeasured. [Proposal 0014](proposals/0014-live-pilot-readiness.md) prepares a pilot: a hint-free default corpus and source-only feedback without diagnostics, priced streaming calls with pinned effort, a required spend cap, interleaved trials, and paired statistics. The [first live pilot](pilot-evidence.md) (Claude Opus 5.5, effort high, both corpora) passed 16 of 16 trials on the first attempt for $0.33 at list-price equivalent: the pipeline works, but the tasks sit at a ceiling and cannot separate the two conditions. A [hard corpus](pilot-evidence.md#second-pilot-the-hard-corpus) run on Opus 5.5, Sonnet 5 and Haiku 4.5 showed the language is learnable from one page. On first attempts it favored source-only over the current compiler context (5–0 discordant pairs, p = 0.06). Multi-error reporting and a compact context view ([PR #30](https://github.com/TechiesApp/talven/pull/30)) removed that penalty: in a rerun, compiler context matched or beat source-only on first attempts at equal or lower cost. On a [large-program corpus](pilot-evidence.md#fifth-run-the-large-program-corpus), compiler context doubled Haiku 4.5's first-attempt success (5 to 10 of 16, p = 0.13) at lower cost. Scalar reassignment was the most common failure under the recorded compiler. [Proposal 0015](proposals/0015-mutable-scalar-locals.md) now specifies an implemented experiment for fixed-type mutable integer/boolean locals in both compilers. Next: evaluate this profile with more repetitions under an explicit budget. Use actual results to guide language/tooling changes before claiming the M1 gate is complete.

The no-heap/freestanding increment, [Proposal 0007](proposals/0007-freestanding-linux-execution.md), adds a [bounded Linux execution probe](freestanding.md): explicit startup/traps, linking without libc or an allocator, artifact dependency checks, and measured file/section sizes. It exercises the existing compiler and keeps Linux process services explicit. Board startup, bounded stack use, and a broader embedded target matrix remain later work; this does not satisfy the separate live-agent gate.

The edit-preview increment, [Proposal 0008](proposals/0008-revision-checked-edit-validation.md), adds [read-only snapshots and candidate validation](edit-validation.md) against exact source/compiler revisions. It supports invalid-source repairs and bounded declaration/direct-call comparisons through the shared frontend. Atomic file application, multi-file transactions, broad impact analysis and controlled model effectiveness remain open; a successful preview does not replace independent correctness checks.

The offline tooling increment, [Proposal 0009](proposals/0009-offline-tooling-baseline.md), adds a [repeatable CLI/build baseline](tooling-baseline.md) with fixed inputs, native acceptance, raw samples, and byte-size reporting. It measures the current bootstrap without selecting a production replacement or supplying model-effectiveness evidence.

The static-text increment, [Proposal 0011](proposals/0011-static-text-and-console-output.md), adds [Hello World](text-console.md): immutable UTF-8 literal views, optional POSIX output with explicit error behavior, shared frontend/tooling support, and native exact-output/lifetime/dependency checks. Literal storage and emitted output support do not allocate a heap; the hosted process still uses the host library and OS. This is a small M1 increment, not the completion of M1 or development reload.

The [watch/restart increment](development.md), specified in [Proposal 0012](proposals/0012-development-watch-and-restart.md), adds a single-file development session with full builds, observed revision receipts, failed-edit recovery, stale candidate suppression, and process cleanup. It does not implement incremental compilation or preserve application state.

[Proposal 0016](proposals/0016-persistent-function-checking.md) adds opt-in persistent reference function checking to that session. Exact source and dependency contracts govern reuse; fresh parsing and declaration validation preserve current references and diagnostics. Native C builds still run in full. Incremental parsing, consistently improved performance and state preservation remain open; the separate [native object watcher](native-watch.md) does not combine check reuse with native reuse.

The [in-process edit baseline](incremental-checking-baseline.md) now checks full/reused analyses against independent native acceptance and retains CI receipts. Its [local observations](incremental-checking-evidence.md) show that reuse is often slower on small functions and does not establish a consistent speedup. Keep the mode opt-in and investigate parsing/allocation/native integration before claiming the speed requirement is met.

The [editor completion increment](editor-completion.md), specified in [Proposal 0017](proposals/0017-current-document-completion.md), adds scoped current names and named-record fields through the shared frontend. Recovered invalid source is explicitly unchecked and never reuses stale semantic facts. Richer type-directed queries and workspace/incremental parsing remain open; no editor latency or agent-cost result is claimed.

[Proposal 0030](proposals/0030-incremental-editor-synchronization.md) adds bounded [sequential UTF-16 document changes](editor-synchronization.md), with full-replacement recovery after rejected batches and fresh shared checking after each accepted notification. Receiving editor deltas does not implement incremental parsing/check reuse or establish a latency benefit.

[Proposal 0018](proposals/0018-semantic-highlighting.md) adds [full semantic highlighting](semantic-highlighting.md) from current checked declarations/references, with lexical-only fallback on invalid edits. Range/delta requests, richer modifiers, incremental parsing and measured editor responsiveness remain open.

[Proposal 0019](proposals/0019-current-call-signatures.md) adds [current call signatures](editor-signatures.md) and active argument selection through shared syntax. Checked declarations expose parameter passing and borrow permission; recovered invalid-source declarations remain explicitly unchecked. Richer type/loan-aware queries and measured responsiveness remain open.

The [native scalar compiler experiment](../experiments/native-compiler/README.md), specified in [Proposal 0013](proposals/0013-native-scalar-compiler.md), adds an independent Rust checker/C emitter for a declared scalar/static-text overlap and a correctness-gated comparison runner. The native experiment now checks by-value records, moves, call-scoped borrowing, record mutation, and scalar reassignment against the reference with differential and sanitizer tests. Shared tooling parity, production selection and incremental compilation remain open.

The [native phase baseline](native-phase-baseline.md) now isolates full lex/parse/depth checking, declaration/body checking and C emission inside one process on verified initial workloads. It keeps correctness and input/build identities explicit, without inferring startup, C build or incremental performance from those phase timings.

[Proposal 0031](proposals/0031-native-compact-agent-context.md) adds the standalone native [compact agent index](../experiments/native-compiler/README.md#compact-agent-context), checked against reference output throughout the differential corpus. Full context v2, native editor/formatter parity and measured context costs remain open.

[Proposal 0032](proposals/0032-native-canonical-formatting.md) adds read-only native [canonical formatting/check mode](../experiments/native-compiler/README.md#canonical-formatting), with syntax-only validation, token/comment preservation and output limits. Native formatter replacement/revision guards and editor integration remain open; core formatter latency and agent-cost benefits remain unmeasured.

The separate [native agent-tool CLI baseline](native-agent-tools-baseline.md) now retains correctness-gated compact context and canonical formatting costs on fixed inputs, including startup and source I/O. Its finite local samples do not establish core phase, editor or live-model benefits.

The [current-profile Codex pilot](codex-pilot-evidence.md), using the optional transport in [Proposal 0033](proposals/0033-codex-subscription-evaluation.md), now supplies six fresh paired large-program trials with independent native acceptance: all passed on the first attempt. It establishes this finite current-profile compatibility evidence while costs remain unknown and both conditions hit a ceiling. Representative task difficulty, controlled cache behavior and broader M1 evidence remain open.

[Proposal 0034](proposals/0034-native-focused-context.md) adds bounded native symbol/direct-dependency context, exact optional bodies and source/build identities. [Proposal 0035](proposals/0035-native-edit-previews.md) adds read-only native snapshots and revision-checked complete-candidate previews with observed reread rejection. Atomic application, native LSP and measured agent benefits remain open.

The [Codex hard-task follow-up](codex-hard-pilot-evidence.md) passed eight additional algorithmic/repair trials on the first attempt; both conditions again hit a ceiling. It broadens finite compatibility evidence while leaving context effectiveness and total task-cost claims unresolved.

### Planned next increments

[Proposal 0020](proposals/0020-hosted-function-c-units.md) now defines [hosted function C units](c-units.md) through the shared reference lowering. Stable local temporary numbering and conservative repeated contracts provide an independently tested emission boundary. [Proposal 0021](proposals/0021-preprocessed-function-units.md) adds [fresh prepared units](preprocessed-units.md) with strict boundaries and expanded input identities. [Proposal 0022](proposals/0022-private-object-reuse.md) adds a [private object-reuse API](object-reuse.md) with fresh linking and last-successful retention under explicit toolchain assumptions; the [opt-in native watcher](native-watch.md) now integrates cancellable builds and restart freshness. [Measured rebuild costs](object-rebuild-evidence.md) are mixed; the [actual watcher runner](native-watch-baseline.md) now retains edit-to-receipt timings and actual native task checks.

These are proposed follow-ups, not implemented features or a new claim that M1 is complete. [Proposal 0010](proposals/0010-fast-compiler-and-development-reload.md) records the owner-requested fast compiler and development refresh requirements.

1. Extend the native experiment toward tooling parity and measure persistent function checking before broad runtime expansion. Define native artifact reuse separately. Preserve reference behavior and independent acceptance; evaluate Rust and fast backend candidates such as Cranelift using representative measurements. Neither is selected yet.
   The [private-object rebuild comparison](object-rebuild-baseline.md) now retains fresh native acceptance of actual reused objects; [local evidence](object-rebuild-evidence.md) shows mixed edit costs and substantially higher cold/contract costs, without a consistent improvement. A separate [opt-in native watcher](native-watch.md) now verifies current deployment/cancellation while default watch/build remain full; the [first actual watcher comparison](native-watch-evidence.md) also shows mixed edit costs and substantially higher native cold/global costs.
2. Add restricted, opt-in hot reload after module/state contracts and safe execution boundaries are defined. Interface/layout/initialization changes may require restart. Concurrency participation needs the later M2 lifetime rules.

Measure actual save-to-diagnostic and save-to-running-revision latency, cache reuse, memory and correctness. Release builds should omit development reload support. This work starts before the broader M5 toolkit; controlled agent evaluation remains a separate M1 gate, with no paid run authorized by this plan.

[Proposal 0026](proposals/0026-local-function-contracts.md) adds explicit [local function contracts](local-function-contracts.md) for hosted units and native watch mode. It retains current full checks, global record layouts and default profiles while allowing unrelated declarations and parameter names to stop invalidating callers. Both native measurement runners accept `--local-contracts`; performance conclusions require retained comparative evidence.

[Proposal 0027](proposals/0027-current-call-type-contracts.md) adds [current call type contracts](call-type-contracts.md) for persistent checks. This remains separate from object reuse: current descriptions are refreshed, full source is parsed, and native C rebuilds in full.

[Proposal 0028](proposals/0028-function-body-syntax-reuse.md) adds explicit [function-body syntax reuse](body-syntax.md): fresh whole-source lexing/current declarations, exact last-successful immutable grammar and current mutable reconstruction. Semantic checks remain independent and native builds full; default parsing and editor recovery are unchanged.

[Proposal 0036](proposals/0036-hosted-scalar-c-api.md) adds explicitly named [scalar C export units](c-api.md), generated headers and independently executed two-unit/libc callers. This begins a bounded foreign-interface contract; project C API integration, foreign imports/ownership/pointers, additional wrappers and M3 bridge-cost evidence remain open.

[Proposal 0037](proposals/0037-bounded-local-modules.md) now implements a separate reference [local-module profile](modules.md): bounded explicit imports/public declarations, nominal record identities, whole-project builds/context and original cross-file navigation. Shared checking preserves ownership rules; Rust independently checks/emits the resolved core source. Native graph resolution, project edit/test/watch integration, persistent reuse/reload and controlled agent effectiveness remain open.

The [module pilot](codex-module-pilot-evidence.md) under [Proposal 0038](proposals/0038-module-agent-evaluation.md) passed eight finite multi-file edits in both conditions at the first attempt. Added context used more input tokens with no correctness difference; this leaves the M1 agent-cost gate open.

## M2: Memory and concurrency foundations

[Proposal 0039](proposals/0039-typed-failures-resource-contracts.md) begins the
semantic foundation: concrete typed outcomes first, then explicit allocation and
verified release/transfer paths, then concurrency after its lifetime/memory model.
Its broader resource/concurrency plan remains a design contract; bounded companions
implement the slices below. [Proposal 0040](proposals/0040-concrete-typed-outcomes.md)
implements the first [concrete outcome slice](outcomes.md) under an explicit
companion profile: nominal alternatives, scalar/record payloads, exhaustive consuming
matches and must-handle checking in reference and native compilers.
[Proposal 0041](proposals/0041-supplied-storage-regions.md) specifies stable lexical
supplied-storage regions, one linear byte block per slot, explicit release and no
block-bearing function results. [Proposal 0042](proposals/0042-supplied-storage-c-runtime.md)
implements the standalone C descriptor/owner with independent ledger, rollback and
sanitizer/trap gates. [Proposal 0043](proposals/0043-supplied-blocks-compiler.md)
implements the [supplied-block companion](resources.md) in reference and Rust
compilers: original-source checks, canonical formatting, exact hosted C11 parity,
normal-path release/delegation obligations and versioned source/compiler/runtime
context. Regions are bounded to eight declarations per function and literal
capacities 1..4096, with one reusable slot each. These are per-function limits,
not recursive total RAM bounds. Actual Linux x86-64/ARM64 resource execution with
no skipped checks is required before merge. [Proposal 0044](proposals/0044-supplied-block-production-costs.md)
adds a [production cost runner](resource-costs.md) for fixed sequential source
workloads: target C layouts, compiler-reported static stack usage, artifact sizes
and verified complete-call batch timing. These costs remain distinct from total
RAM, isolated intrinsic latency, tail latency and agent benefit. Heap containers,
general allocator lifetimes, cancellation and an executor remain later work.

Continue with general allocator interfaces, containers, structured tasks, cancellation, synchronization, and a selected optional executor.

Gate: resource lifetimes remain sound across errors, task cancellation, and concurrent operations. Measure binary size, allocations, RAM, task overhead, and tail latency.

Specify the memory model and public effect information before exposing broad concurrency APIs.

## M3: Native package integration

Implement a defined foreign ABI boundary, one C library adapter, and one additional native wrapper. Record reproducible build inputs and adapter contracts.

Gate: documented ownership, error propagation, allocator, target, and unsafe-code obligations; measured foreign-call and data-conversion costs.

## M4: One GPU backend

Implement host integration for one backend, explicit buffers, transfers, submission, and completion.

Gate: correct computation, explicit resource costs, and safe handling of cancellation while work is in flight. Cover exhaustion and device failures appropriate to the backend.

Portable kernel compilation and additional vendors follow this evidence; they are separate milestones.

## M5: One managed ecosystem and developer toolkit

Add one optional JS, Python, or JVM integration selected from actual demand. Expand the coherent build/test/format/documentation/package workflow.

Gate: representative packages work with documented limitations, isolated execution where required, and measured runtime footprint. A native-only build remains independent of that foreign runtime.

## M6: Broader platforms and security hardening

Expand target and backend coverage, add stronger protected build/release enforcement, fuzzing, audits, signed updates, and a verified vulnerability response process.

Gate: each target has a tested support statement, and each security claim names its enforcement layer and trust assumptions.

## Evaluation matrix

| Dimension | Measurements |
| --- | --- |
| Agent effectiveness | Correct completion rate, total input/output tokens, repair count, tool calls, latency |
| Context | Relevant context size, retrieval latency, invalidation correctness, cache hit behavior |
| Human experience | Readability, navigation, diagnostics, rename correctness, editor responsiveness |
| Development loop | Cold/warm compiler latency, save-to-diagnostic and save-to-running-revision latency, affected work, cache invalidation, state/restart correctness, retained memory |
| Native performance | Throughput, latency distribution, generated code, startup, binary size |
| Memory | Peak RSS or applicable device metric, allocations, fragmentation, cleanup behavior |
| Concurrency | Scheduling overhead, queue growth, backpressure, cancellation, contention |
| GPU | Kernel time, transfer time, synchronization, VRAM use, end-to-end throughput |
| Interoperability | Call and copy overhead, runtime footprint, supported API surface, failure behavior |
| Security | Enforced negative cases, unsafe surface, sandbox escape assumptions, supply-chain controls |
| Portability | Actual builds and execution for each declared CPU/ABI/OS/board combination |

No numeric target is claimed until a baseline exists. Report the model, tokenizer, hardware, compiler flags, workload, and correctness criteria alongside every benchmark.

## Remaining foundation work

1. Evaluate M1c call-scoped borrowing diagnostics and context v2 with controlled agents. Escaping references, heap lifetimes, and field-sensitive borrowing need separate designs.
2. Evaluate bounded context, diagnostics and edit previews with agents, then define atomic file application with independently enforced writer coordination.
3. Review the native CI evidence and use the offline tooling baseline to investigate bootstrap/backend costs on representative workloads before deciding production implementation choices.
4. Run the initial task corpus with live agents using the implemented harness, then establish equivalent cross-language baselines for agent cost and success. Offline fixture runs are not model measurements.
5. Specify capability transfer and protected policy enforcement.
6. Choose the first foreign library and first GPU experiment from concrete workloads.
7. Proposals 0001–0014 were accepted by the project owner on 24 September 2026; acceptance adopts their direction, and the open questions they list remain open.
8. Evaluate the [borrowing corpus](proposals/0005-borrowing-evaluation-corpus.md) with live agents; fixtures establish harness behavior only.
9. Validate the [Anthropic Messages adapter](proposals/0006-anthropic-evaluation-adapter.md)'s live API compatibility under an approved budget, and capture actual provider usage and billing evidence.

These are planning items, not automatically created issues or assigned commitments.
