# Roadmap and evidence gates

Status: proposed sequence. There are no committed dates, staffing estimates, or performance claims.

## M0: Design baseline

Deliver a traceable requirement set, a minimal grammar proposal, ownership rules, capability boundaries, target definitions, and an agent evaluation protocol.

Gate: reviewers can distinguish product requirements from proposals and identify unresolved semantics. The specification is short enough to give to an unfamiliar model.

Current repository contribution: requirements and architecture are documented. The [M1a guide](prototype.md) defines a small implemented grammar and affine value rules, with an [executable agent evaluation protocol](../experiments/README.md). The runner owns source-edit acceptance and records reproducible inputs; hostile-process isolation and a complete language specification remain unfinished.

## M1: Small native subset with agent tooling

Initial increment: **M1a reference compiler**. Implemented parsing, strict scalar types, affine scalar-field records, functions, conditionals, structured diagnostics, deterministic bounded context, C11 lowering, and a basic LSP. See [actual validation](prototype-validation.md). This increment does not complete the full M1 gate.

Following increment: **M1b formatting and native checks**. The CLI and LSP share a token-preserving canonical formatter, with explicit file writes and structured check diagnostics. Native CI declares Linux x86-64 and ARM64 jobs; see [M1b scope](formatting.md) and [its execution evidence](formatting-validation.md). The next increment, **M1c call-scoped borrowing**, implements shared/exclusive record parameters, field mutation, source-order native lowering, and context v2; see [its scope](borrowing.md) and [validation](borrowing-validation.md). Controlled model evaluation remains open.

Prototype parsing, strict types, functions, basic data types, a limited ownership model, deterministic diagnostics, a formatter, and compiler-derived context lookup.

Compile and run a useful small program on the first ARM64 and x86-64 hosts. Keep the source of truth shared between CLI, LSP, and agent interfaces from the beginning.

Gate: a model can make a bounded change using a fixed context budget, and independent checks establish correctness. Invalid ownership and type examples fail predictably.

Evaluation increment: [Proposal 0004](proposals/0004-reproducible-agent-evaluation.md) implements the provider-neutral four-task harness, source-only/compiler-context trials, bounded repairs, independent structural/native checks, archived provenance, and token/cost accounting that preserves unknown values. Scripted fixtures validate execution; controlled live model results remain open, so this does not complete the M1 gate.

Borrowing evaluation increment: [Proposal 0005](proposals/0005-borrowing-evaluation-corpus.md) adds a separately versioned four-task corpus for overlapping loans, missing write permission, explicit reborrowing, and evaluation order. The original corpus remains the default. Independent checks include mutation, call order, and dependence on helper return values; both corpora can be exercised offline. See [actual borrowing evaluation validation](borrowing-evaluation-validation.md). Next: implement a selected provider adapter with offline protocol tests, then run a live pilot only with an approved budget. Use actual results to guide language/tooling changes before claiming the M1 gate is complete.

Do an early no-heap/freestanding experiment to discover hidden runtime assumptions. A broad embedded target matrix is not required at this stage.

## M2: Memory and concurrency foundations

Add allocator interfaces, containers, typed failures, structured tasks, cancellation, synchronization, and a selected optional executor.

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
2. Evaluate the bounded context and diagnostics with agents, then define atomic edit validation.
3. Review the new native CI evidence on ARM64/x86-64 and measure bootstrap/backend costs before deciding production implementation choices.
4. Run the initial task corpus with live agents using the implemented harness, then establish equivalent cross-language baselines for agent cost and success. Offline fixture runs are not model measurements.
5. Specify capability transfer and protected policy enforcement.
6. Choose the first foreign library and first GPU experiment from concrete workloads.
7. Review [Proposal 0001](proposals/0001-m1a-reference-compiler.md), [Proposal 0002](proposals/0002-canonical-formatting-and-native-checks.md), [Proposal 0003](proposals/0003-call-scoped-borrowing.md), and [Proposal 0004](proposals/0004-reproducible-agent-evaluation.md), recording decisions from the grammar, ownership, context, formatting, and evaluation experiments. The language name and Apache-2.0 license are already selected.
8. Review [Proposal 0005](proposals/0005-borrowing-evaluation-corpus.md) and evaluate the borrowing corpus with live agents; fixtures establish harness behavior only.

These are planning items, not automatically created issues or assigned commitments.
