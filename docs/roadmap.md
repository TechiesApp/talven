# Roadmap and evidence gates

Status: proposed sequence. There are no committed dates, staffing estimates, or performance claims.

## M0: Design baseline

Deliver a traceable requirement set, a minimal grammar proposal, ownership rules, capability boundaries, target definitions, and an agent evaluation protocol.

Gate: reviewers can distinguish product requirements from proposals and identify unresolved semantics. The specification is short enough to give to an unfamiliar model.

Current repository contribution: the requirements and architecture discussion are documented. Grammar, formal rules, and implementation remain unfinished.

## M1: Small native subset with agent tooling

Prototype parsing, strict types, functions, basic data types, a limited ownership model, deterministic diagnostics, a formatter, and compiler-derived context lookup.

Compile and run a useful small program on the first ARM64 and x86-64 hosts. Keep the source of truth shared between CLI, LSP, and agent interfaces from the beginning.

Gate: a model can make a bounded change using a fixed context budget, and independent checks establish correctness. Invalid ownership and type examples fail predictably.

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

## Initial work items

1. Propose the minimum type and ownership rules with a small set of valid and invalid examples.
2. Define a bounded compiler-context schema and structured diagnostic format.
3. Evaluate a backend and bootstrap compiler implementation with the first targets.
4. Establish a task corpus and comparison protocol for agent cost and success.
5. Specify capability transfer and protected policy enforcement.
6. Choose the first foreign library and first GPU experiment from concrete workloads.
7. Populate the design proposal process with the first grammar, ownership, and context-schema proposals. (The language name and Apache-2.0 license were decided on 7 September 2026.)

These are planning items, not automatically created issues or assigned commitments.

