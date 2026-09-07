# Requirements

Status: recorded product requirements and proposed acceptance evidence. [M1a](prototype.md) implements a small language subset, [M1b](formatting.md) adds formatting/native checks, and [M1c](borrowing.md) adds call-scoped borrowing; the table remains the broader intended scope, not a list of completed features.

The priority order is agent effectiveness, semantic clarity and safety, native control and efficiency, then breadth of convenience and ecosystem support. All requirements remain part of the vision; implementation is staged.

## Traceability

| ID | Requirement from the design discussion | Proposed evidence |
| --- | --- | --- |
| R01 | LLM and agentic coding is the primary focus | Controlled coding tasks measuring correctness, context size, repairs, and total tokens |
| R02 | Reduce token use | Compare total task tokens across tokenizers and models, including specification and repair overhead |
| R03 | Excellent LSP | Incremental diagnostics, completion, definition, references, rename, ownership and effect information |
| R04 | Make context easy to cache and reuse | Deterministic context records, versioned keys, precise invalidation, and measured cache behavior |
| R05 | Be context-driven | Compiler-generated task context; program semantics remain defined by source and dependencies |
| R06 | Work with current open and proprietary models | Ordinary text/tool interfaces and a concise specification; evaluate without requiring model retraining |
| R07 | Offer approachable TypeScript-like syntax | A small regular grammar and usability studies with both humans and models |
| R08 | Enforce strict types and safety | Explicit public contracts, checked conversions, exhaustive cases, and unsafe boundaries |
| R09 | Provide low-level flexibility and native performance like C, C++, or Rust | Native code, inspectable layout and allocation, FFI, and measured overhead |
| R10 | Improve control over RAM and reclamation | Ownership, deterministic release, explicit allocators, and optional explicit sharing |
| R11 | Remain light and highly modular | Measured binary size, startup, linked dependencies, and RAM per selected profile |
| R12 | Provide Bun-like breadth of developer tools | A coherent build, run, test, format, documentation, LSP, and package workflow |
| R13 | Reuse npm, Python, C/C++, Java, Rust, and Go ecosystems | A compatibility matrix and representative packages exercised through suitable adapters |
| R14 | Minimize bridge and translation overhead | Measure call, copy, serialization, runtime, startup, and memory costs separately |
| R15 | Support ARM and x86 systems | ARM64 and x86-64 execution first; distinguish CPU, ABI, OS, SDK, and board support |
| R16 | Scale from small infrastructure to large systems | Early no-heap/freestanding experiment plus hosted workload measurements |
| R17 | Handle CPU-intensive tasks | Bounded native parallel execution, synchronization, SIMD where supported, and profiling |
| R18 | Support synchronous, asynchronous, concurrent, and multitasking workloads | Defined task lifetimes, cancellation, backpressure, synchronization, and executor behavior |
| R19 | Control GPU memory and intensive GPU computation | Explicit buffers, transfers, device selection, submission, completion, and resource budgets |
| R20 | Integrate with Metal, NVIDIA, and other standard GPU stacks | Incremental vendor backends and a documented portable subset |
| R21 | Follow current security practices | Versioned guidance mapping, dependency review, compiler testing, and a response process |
| R22 | Protect data across filesystem, memory, network, and servers | Explicit authorization and integrity controls with a documented trusted computing base |
| R23 | Extend protection toward the root of the platform | Declare hardware and firmware prerequisites, recovery mechanisms, and unsupported guarantees |

## Meaning of context-first

Context is a checked view of a particular source revision, dependency graph, target, and policy. It can include types, ownership, effects, relevant callers, tests, and task constraints.

Ambient chat history must not silently change a program's behavior. A context summary is useful input to an agent, not a substitute for compiling and checking the resulting code.

## Interpreting ambitious requirements

“Any environment” is a portability direction, not a claim that one binary or dependency set runs everywhere. Each supported target needs a declared CPU, ABI, operating environment, and applicable libraries.

“Minimal overhead” is a measured objective. Some boundaries require a foreign runtime, copying, synchronization, or isolation.

“Prevent tampering” means enforceable prevention, authenticated detection, containment, and recovery under a stated threat model. It cannot mean unconditional protection against compromise of every underlying component.

## Evaluation discipline

Record model version, tokenizer, prompts, available tools, context policy, compiler revision, target, optimization level, hardware, and task success criteria. Distinguish hypotheses, benchmark results, and released guarantees. Do not invent token-reduction, speedup, RAM, or security percentages.
