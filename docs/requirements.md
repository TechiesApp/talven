# Requirements

Status: recorded product requirements with proposed acceptance evidence and the current evidence for each. The [language reference](language-reference.md) defines the implemented subset; the table remains the broader intended scope, not a list of completed features.

The priority order is agent effectiveness, semantic clarity and safety, native control and efficiency, then breadth of convenience and ecosystem support. All requirements remain part of the vision; implementation is staged.

## Traceability

| ID | Requirement from the design discussion | Proposed evidence | Current evidence |
| --- | --- | --- | --- |
| R01 | LLM and agentic coding is the primary focus | Controlled coding tasks measuring correctness, context size, repairs, and total tokens | Partial: evaluation harness with paired conditions; [first live pilot](pilot-evidence.md) 16/16 and [module pilot](codex-module-pilot-evidence.md) 8/8 at ceilings; added module context used more input tokens, no cost benefit established |
| R02 | Reduce token use | Compare total task tokens across tokenizers and models, including specification and repair overhead | Partial: pilot token counts per condition recorded ([pilot](pilot-evidence.md)); no cross-language baseline |
| R03 | Excellent LSP | Incremental diagnostics, completion, definition, references, rename, ownership and effect information | Partial: diagnostics, hover, definition, references, rename, symbols, formatting, bounded [completion](editor-completion.md), [call signatures](editor-signatures.md) and full [semantic highlighting](semantic-highlighting.md) over [sequential incremental synchronization](editor-synchronization.md); custom [resource context](resources.md) exposes checked origins, intrinsic contracts and owning-parameter effects; broader ownership/effect information and incremental parsing remain open |
| R04 | Make context easy to cache and reuse | Deterministic context records, versioned keys, precise invalidation, and measured cache behavior | Partial: deterministic context v2 with versioned cache keys and [resource context](resources.md) with exact source/compiler/runtime identities; cache behavior not measured |
| R05 | Be context-driven | Compiler-generated task context; program semantics remain defined by source and dependencies | Partial: reference compiler context, [native focused context](proposals/0034-native-focused-context.md) and reference/native [edit previews](edit-validation.md) |
| R06 | Work with current open and proprietary models | Ordinary text/tool interfaces and a concise specification; evaluate without requiring model retraining | Partial: text/JSON interfaces, a one-page [language reference](language-reference.md) and bounded [live pilots](pilot-evidence.md); broader model/provider coverage remains open |
| R07 | Offer approachable TypeScript-like syntax | A small regular grammar and usability studies with both humans and models | Partial: small implemented grammar, including [mutable scalar locals](proposals/0015-mutable-scalar-locals.md) motivated by pilot repair failures; [current-profile Codex pilot](codex-pilot-evidence.md) passed six finite large-program trials; no human usability study or causal syntax-benefit result |
| R08 | Enforce strict types and safety | Explicit public contracts, checked conversions, exhaustive cases, and unsafe boundaries | Partial: strict types, no implicit conversions, checked arithmetic and explicitly selected [exhaustive typed outcomes](outcomes.md) and [resource provenance/release obligations](resources.md); no unsafe boundary yet |
| R09 | Provide low-level flexibility and native performance like C, C++, or Rust | Native code, inspectable layout and allocation, FFI, and measured overhead | Partial: native code through C11, explicit [scalar C exports](c-api.md) and [fixed supplied-block cost evidence](resource-costs.md); no foreign imports or overhead comparison |
| R10 | Improve control over RAM and reclamation | Ownership, deterministic release, explicit allocators, and optional explicit sharing | Partial: affine records, [call-scoped borrowing](borrowing.md) and explicit [bounded supplied-storage blocks](resources.md) with linear release/delegation; a separate [C byte-buffer experiment](proposals/0045-supplied-byte-buffer-runtime.md) adds container invariants before source integration; general allocators, heap containers and shared ownership remain open |
| R11 | Remain light and highly modular | Measured binary size, startup, linked dependencies, and RAM per selected profile | Partial: [freestanding probe sizes](freestanding-validation.md) and [supplied-block artifacts/layouts/bounded stack evidence](resource-costs.md); total RAM remains unmeasured |
| R12 | Provide Bun-like breadth of developer tools | A coherent build, run, test, format, documentation, LSP, and package workflow | Partial: check, fmt, context, build, dev, LSP, edit, bounded [native test manifests](testing.md) and explicit [local-module tools](modules.md); project test/watch/edit integration, documentation generation and packages remain open |
| R13 | Reuse npm, Python, C/C++, Java, Rust, and Go ecosystems | A compatibility matrix and representative packages exercised through suitable adapters | Partial: [C host export boundary](c-api.md) and libc-parsed scalar workload; no Talven foreign imports or package adapters |
| R14 | Minimize bridge and translation overhead | Measure call, copy, serialization, runtime, startup, and memory costs separately | None |
| R15 | Support ARM and x86 systems | ARM64 and x86-64 execution first; distinguish CPU, ABI, OS, SDK, and board support | Partial: Linux x86-64 and ARM64 CI execution |
| R16 | Scale from small infrastructure to large systems | Early no-heap/freestanding experiment plus hosted workload measurements | Partial: [no-libc Linux probe](freestanding.md) |
| R17 | Handle CPU-intensive tasks | Bounded native parallel execution, synchronization, SIMD where supported, and profiling | None |
| R18 | Support synchronous, asynchronous, concurrent, and multitasking workloads | Defined task lifetimes, cancellation, backpressure, synchronization, and executor behavior | None |
| R19 | Control GPU memory and intensive GPU computation | Explicit buffers, transfers, device selection, submission, completion, and resource budgets | None |
| R20 | Integrate with Metal, NVIDIA, and other standard GPU stacks | Incremental vendor backends and a documented portable subset | None |
| R21 | Follow current security practices | Versioned guidance mapping, dependency review, compiler testing, and a response process | Partial: DCO, pinned CI actions, sanitizer checks; response process not exercised |
| R22 | Protect data across filesystem, memory, network, and servers | Explicit authorization and integrity controls with a documented trusted computing base | None: design only |
| R23 | Extend protection toward the root of the platform | Declare hardware and firmware prerequisites, recovery mechanisms, and unsupported guarantees | None: design only |
| R24 | Provide a very fast compiler and responsive developer/agent feedback | Measure startup, checking, full builds, incremental rebuilds and compiler memory on representative workloads; evaluate a native implementation against the reference | Partial: [offline tooling baseline](tooling-baseline.md), native prototype with [in-process phase measurements](native-phase-baseline.md), opt-in [persistent checks](development.md#persistent-function-checks) with [local timings](incremental-checking-evidence.md); no established incremental improvement |
| R25 | Refresh running code quickly during development, with live reload and eligible state-preserving hot reload | Measure save-to-diagnostic and save-to-running-revision latency; verify dependency-aware reuse, state preservation, restart boundaries, and absence of reload support from release artifacts | Partial: [watch/restart and dependency-aware function checks](development.md); [opt-in private native object mode](native-watch.md) with full current checks and an [actual watcher measurement runner](native-watch-baseline.md) with [mixed local timings](native-watch-evidence.md); [local function contract experiment](local-function-contracts.md); default builds remain full, no hot reload |

## Meaning of context-first

Context is a checked view of a particular source revision, dependency graph, target, and policy. It can include types, ownership, effects, relevant callers, tests, and task constraints.

Ambient chat history must not silently change a program's behavior. A context summary is useful input to an agent, not a substitute for compiling and checking the resulting code.

## Interpreting ambitious requirements

“Any environment” is a portability direction, not a claim that one binary or dependency set runs everywhere. Each supported target needs a declared CPU, ABI, operating environment, and applicable libraries.

“Minimal overhead” is a measured objective. Some boundaries require a foreign runtime, copying, synchronization, or isolation.

“Prevent tampering” means enforceable prevention, authenticated detection, containment, and recovery under a stated threat model. It cannot mean unconditional protection against compromise of every underlying component.

## Evaluation discipline

R24 and R25 were requested on 8 September 2026. [Proposal 0010](proposals/0010-fast-compiler-and-development-reload.md) records the proposed native-compiler and staged reload direction. The current Python/C11 bootstrap, standalone CLI timings and read-only edit previews do not establish incremental compilation or hot reload. Avoid full recompilation for ordinary edits where dependencies permit; incompatible changes may require broader rebuilding and restart. These requirements set no measured latency guarantee or mandatory production runtime.

Record model version, tokenizer, prompts, available tools, context policy, compiler revision, target, optimization level, hardware, and task success criteria. Distinguish hypotheses, benchmark results, and released guarantees. Do not invent token-reduction, speedup, RAM, or security percentages.
