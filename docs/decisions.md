# Decision register

Status definitions:

- **Requirement:** expressed product intent from the initial discussion.
- **Accepted:** an explicitly chosen project decision; not evidence of implementation.
- **Proposed:** an implementation direction to evaluate.
- **Open:** a decision that has not been made.
- **Limit:** a constraint that must be reflected in claims and design.

## Recorded positions

| ID | Status | Position | Reason or next evidence |
| --- | --- | --- | --- |
| D01 | Requirement | LLM and agentic coding remains the primary product focus | Evaluate total cost of correctly completed work |
| D02 | Requirement | Native control, high performance, small footprint, modern usability | Measure implementation cost rather than infer it from syntax |
| D03 | Requirement | Current open and proprietary model compatibility | Evaluate a pinned language guide with multiple models |
| D04 | Proposed | One compiler semantic model for LSP and agent tools | Avoid inconsistent types, effects, and diagnostics |
| D05 | Proposed | Familiar, regular source syntax with strict static contracts | Prototype and compare both model and human behavior |
| D06 | Proposed | Ownership with controlled scoped borrowing; no mandatory tracing GC | Specify soundness and error behavior before broadening the model |
| D07 | Proposed | Small freestanding core and explicit optional runtime modules | Prove deployed dependency and footprint boundaries |
| D08 | Proposed | Ahead-of-time compilation with a mature native backend | Evaluate toolchains, target coverage, diagnostics, and build costs |
| D09 | Proposed | Linux ARM64 and x86-64 as first hosted targets | Small initial test matrix; expand after execution evidence |
| D10 | Requirement | Tiny-system and broad-platform feasibility | Test an early no-heap/freestanding program |
| D11 | Proposed | C-compatible native integration before managed runtime ecosystems | Establish ownership and ABI contracts first |
| D12 | Limit | Foreign runtimes and semantics cannot be universally erased | Document per-package translation or bridging constraints |
| D13 | Proposed | Explicit GPU memory and one backend before portable kernels | Validate lifetimes and synchronization first |
| D14 | Requirement | Security across code, data, dependencies, and deployment | Use layer-specific enforcement and a threat model |
| D15 | Proposed | Protected agent policy outside the writable workspace | Prevent self-authorized capability and release changes |
| D16 | Limit | No unconditional tamper-proof claim across compromised trusted components | State prerequisites, detection, containment, and recovery |
| D17 | Limit | Provider prompt caching is distinct from compiler and build caching | Record different keys, costs, invalidation, and trust assumptions |
| D18 | Requirement | A public repository under TechiesApp | TechiesApp/talven was created by the project owner; public visibility verified on 7 September 2026 |
| D19 | Accepted | The language is named Talven, pronounced TAL-ven | Selected by the project owner on 7 September 2026; repository: TechiesApp/talven |
| D20 | Accepted | Apache License 2.0 for all repository content; contributions under DCO sign-off | Chosen on 7 September 2026 for its explicit patent grant and wide organizational acceptance; see [LICENSE](../LICENSE) |
| D21 | Accepted | Design changes proceed through numbered proposals in `docs/proposals/` with decisions recorded here | Established on 7 September 2026; see [GOVERNANCE.md](../GOVERNANCE.md) |
| D22 | Proposed | Use a dependency-free Python reference frontend and C11 backend for M1a | [Proposal 0001](proposals/0001-m1a-reference-compiler.md); implemented as an experiment; final compiler language/backend remain open |
| D23 | Proposed | Start with affine stack records containing scalar fields | Proposal 0001; M1a checks demonstrate moves without claiming borrowed references, heap ownership, or destructors |
| D24 | Proposed | Share frontend analysis between CLI, bounded context, and basic LSP | Proposal 0001; remaining editor features and performance require further work |
| D25 | Proposed | One token-preserving canonical formatter shared by CLI and LSP | [Proposal 0002](proposals/0002-canonical-formatting-and-native-checks.md); implemented experimental layout, with no token-savings claim |
| D26 | Proposed | Run native conformance on declared Linux x86-64 and ARM64 CI hosts | Proposal 0002; record real compiler/host/test evidence, reject skips, and keep target claims limited to successful runs |
| D27 | Proposed | Explicit call-scoped shared/exclusive borrowing of named scalar-field records, with no reference escape | [Proposal 0003](proposals/0003-call-scoped-borrowing.md); implemented experiment with mutation, conflict rejection, and explicit reborrowing |
| D28 | Proposed | Preserve source-order effects in native lowering and expose borrow contracts through context v2 | Proposal 0003; ordered native fixtures and shared CLI/LSP/context tests; no complete effect system or performance claim |

## Open decisions

| Decision | Questions to resolve |
| --- | --- |
| Compiler implementation | Should the Python/C11 prototype evolve or be replaced for production compiler throughput, portability, and tooling latency? |
| Type model | Which nominal/structural rules, generics, and composition features are necessary? |
| Borrowing model | What references may escape scopes or cross suspension and task boundaries? |
| Failure semantics | How are overflow, panic, cancellation, OOM, and foreign exceptions represented? |
| Effect system | Which effects are checked, inferred locally, or explicit at public boundaries? |
| ABI and module interface | How are layout, ownership transfer, callbacks, and version compatibility encoded? |
| Package manifest | How are adapters, foreign runtimes, hashes, targets, and capabilities locked? |
| First workloads | Which tasks represent meaningful agent savings and native-system needs? |
| First GPU backend | Which available hardware and workload should guide the first integration? |
| Runtime release process | Who owns protected policy, signing, private reporting, and security response? |

## Change process

A proposal should identify affected requirements, semantics, agent context cost, runtime cost, security implications, and validation evidence.

Record alternatives and the reason for the chosen direction. A repository merge is not evidence that an unimplemented feature is supported; update implementation status separately.
