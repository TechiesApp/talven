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
| D22 | Accepted | Use a dependency-free Python reference frontend and C11 backend for M1a | [Proposal 0001](proposals/0001-m1a-reference-compiler.md); implemented as an experiment; final compiler language/backend remain open |
| D23 | Accepted | Start with affine stack records containing scalar fields | Proposal 0001; M1a checks demonstrate moves without claiming borrowed references, heap ownership, or destructors |
| D24 | Accepted | Share frontend analysis between CLI, bounded context, and basic LSP | Proposal 0001; remaining editor features and performance require further work |
| D25 | Accepted | One token-preserving canonical formatter shared by CLI and LSP | [Proposal 0002](proposals/0002-canonical-formatting-and-native-checks.md); implemented experimental layout, with no token-savings claim |
| D26 | Accepted | Run native conformance on declared Linux x86-64 and ARM64 CI hosts | Proposal 0002; record real compiler/host/test evidence, reject skips, and keep target claims limited to successful runs |
| D27 | Accepted | Explicit call-scoped shared/exclusive borrowing of named scalar-field records, with no reference escape | [Proposal 0003](proposals/0003-call-scoped-borrowing.md); implemented experiment with mutation, conflict rejection, and explicit reborrowing |
| D28 | Accepted | Preserve source-order effects in native lowering and expose borrow contracts through context v2 | Proposal 0003; ordered native fixtures and shared CLI/LSP/context tests; no complete effect system or performance claim |
| D29 | Accepted | Versioned provider-neutral agent evaluations with runner-controlled acceptance and provenance-aware accounting | [Proposal 0004](proposals/0004-reproducible-agent-evaluation.md); source-only/compiler-context trials, bounded repairs, archived inputs, and unknown metrics preserved; live model comparisons remain unmeasured |
| D30 | Accepted | Preserve the original evaluation corpus and select borrowing repairs separately | [Proposal 0005](proposals/0005-borrowing-evaluation-corpus.md); independent native values, mutation, call order, and return-sensitivity checks; live agent results remain unmeasured |
| D31 | Accepted | Keep Anthropic Messages integration in an optional command adapter with explicit live/fixture modes | [Proposal 0006](proposals/0006-anthropic-evaluation-adapter.md); owner-selected provider, unchanged acceptance, receipt-aware accounting, and offline verification; live compatibility and model results remain unmeasured |
| D32 | Accepted | Link and execute a bounded freestanding C probe with explicit Linux startup and traps, without libc or a heap allocator | [Proposal 0007](proposals/0007-freestanding-linux-execution.md); inspect dependencies and target, test values/traps, and record actual file/section sizes; broader runtimes and board support remain open |
| D33 | Accepted | Preview complete candidate edits against exact source/compiler revisions through the shared frontend | [Proposal 0008](proposals/0008-revision-checked-edit-validation.md); read-only snapshots, invalid-base repairs and bounded declaration comparisons; atomic application and independent task acceptance remain separate |
| D34 | Accepted | Measure offline CLI/build costs on fixed workloads with native acceptance and retained raw samples | [Proposal 0009](proposals/0009-offline-tooling-baseline.md); separate process timings and byte sizes with environment/provenance; production backend choice and controlled agent results remain open |
| D35 | Requirement | Make compiler speed and developer/agent feedback latency explicit product goals | Owner request on 8 September 2026; R24; measure startup, checking, full/incremental builds and memory without assuming a speedup from implementation language |
| D36 | Requirement | Provide quick development refresh with incremental reuse, live reload and eligible state-preserving hot reload | Owner request on 8 September 2026; R25; incompatible changes may require restart, and development support must remain optional for deployed programs |
| D37 | Accepted | Evaluate a native compiler early while retaining the Python reference and independent acceptance | [Proposal 0010](proposals/0010-fast-compiler-and-development-reload.md); Rust now has a bounded scalar/static-text experiment; Cranelift remains unimplemented, and production compiler/backend selection is open |
| D38 | Accepted | Stage development tooling as watch/restart, persistent incremental compilation, then restricted hot reload | Proposal 0010; revision-aware publication, defined state/lifetime boundaries and development-only loader; watch/restart and opt-in persistent function checking are implemented experiments; opt-in private native object builds are implemented under Proposed D53; restricted hot reload remains open |
| D39 | Accepted | Start visible output with immutable static UTF-8 views and an explicitly selected POSIX print builtin | [Proposal 0011](proposals/0011-static-text-and-console-output.md); exact bytes, output failures, static lifetimes, optional dependencies and shared tooling; dynamic text, general I/O, and reload remain separate |
| D40 | Accepted | Start development refresh with single-file snapshot builds and revision-aware process restart | [Proposal 0012](proposals/0012-development-watch-and-restart.md); shared full-build semantics, failed-edit recovery, process cleanup, and actual event timing; no incremental compilation, readiness, or state-preservation claim |
| D41 | Accepted | Evaluate a native Rust scalar/static-text compiler through C11 while retaining reference and independent acceptance | [Proposal 0013](proposals/0013-native-scalar-compiler.md); separate profile, records/moves and call-scoped borrowing/mutation ported, reference diagnostics and byte-identical C checked by a shared differential corpus, direct native checking/emission and retained correctness-gated comparison samples; no shared tooling parity, incremental reuse or production speed claim |
| D42 | Accepted | Before a paid pilot, keep the source-only control free of compiler diagnostics, price calls from a pinned table, stream with explicit effort, cap spend, interleave trials, and report paired results | [Proposal 0014](proposals/0014-live-pilot-readiness.md); default corpus `m1-agent-tasks-v2`; list-price cost is labeled estimate provenance, not a billing receipt; no live result claimed |
| D43 | Proposed | Initialized mutable `i32`/`bool` locals and fixed-type scalar reassignment, preserving immutable parameters, record moves, and call-scoped borrowing | [Proposal 0015](proposals/0015-mutable-scalar-locals.md); implemented `0.5.0-dev` experiment; design acceptance and new live evaluation remain separate |
| D44 | Proposed | Reuse successful function checks using exact current source and dependency contracts, with fresh parsing/references and full native rebuilding | [Proposal 0016](proposals/0016-persistent-function-checking.md); opt-in reference experiment; invalidation is tested, [local timings](incremental-checking-evidence.md) do not establish a consistent speedup |
| D45 | Proposed | Offer bounded current-document identifier completion through shared syntax, with current checked facts or explicitly unchecked recovered declarations | [Proposal 0017](proposals/0017-current-document-completion.md); reference LSP experiment; plain UTF-16 edits, lexical scope, no source application/execution or measured agent benefit |
| D46 | Proposed | Derive full current-document semantic highlighting from shared lexing and resolved references, clearing semantic facts on invalid edits | [Proposal 0018](proposals/0018-semantic-highlighting.md); reference LSP experiment; UTF-16 relative tokens, declaration/write markers, bounded full results, no range/delta or performance claim |
| D47 | Proposed | Show bounded current direct-call signatures and argument passing contracts through shared syntax and current checked facts | [Proposal 0019](proposals/0019-current-call-signatures.md); reference LSP experiment, nested argument selection and explicitly unchecked recovered declarations; no call validation, source application or performance claim |
| D48 | Proposed | Emit checked hosted function C units with stable local temporaries and repeated current global contracts before designing object reuse | [Proposal 0020](proposals/0020-hosted-function-c-units.md); reference lowering experiment, bounded unit receipts and independent separate-object native/sanitizer checks; no object cache, new build mode or speed claim |
| D49 | Proposed | Freeze fresh trusted preprocessing into bounded function units while preserving host-header context | [Proposal 0021](proposals/0021-preprocessed-function-units.md); checked current source, strict splitting and driver/input byte identities; object reuse, complete toolchain trust and native build publication remain separate |
| D50 | Proposed | Reuse bounded private last-successful objects under an explicit trusted stable-toolchain contract, with fresh checking/preprocessing/linking | [Proposal 0022](proposals/0022-private-object-reuse.md); synchronous API experiment, object integrity and atomic session-cache promotion; default builds remain unchanged; Proposed D53 adds opt-in watch integration, and measured comparative costs remain mixed |
| D51 | Proposed | Own bounded pollable compiler commands so later native build stages can preserve observation and cancellation | [Proposal 0023](proposals/0023-pollable-compiler-commands.md); non-waiting read steps, unreaped group identity and compatibility wrapper; watcher object reuse/publication remain separate |
| D52 | Proposed | Share one current-source object-build continuation between blocking and polling drivers, unwinding cancelled candidates before promotion | [Proposal 0024](proposals/0024-pollable-object-builds.md); bounded immutable requests, queued deadlines and last-successful retention; source watcher/application publication remain separate |
| D53 | Proposed | Integrate explicit opt-in private native object reuse into source-aware watch/restart with verified separate deployment copies | [Proposal 0025](proposals/0025-native-object-watch.md); full current checks, cancellation/freshness, last-successful native retention and restart; no default speed claim or state preservation |
| D54 | Proposed | Select own/direct-callee type declarations for opt-in hosted units, retaining global record layouts and fresh current checks | [Proposal 0026](proposals/0026-local-function-contracts.md); [local function contracts](local-function-contracts.md), separate profile/cache identities and actual native acceptance; default profiles remain unchanged |
| D55 | Proposed | Reuse callers under explicit current call type contracts while refreshing displayed signatures from fresh declarations | [Proposal 0027](proposals/0027-current-call-type-contracts.md); [selected persistent check mode](call-type-contracts.md), exact own source, current record/call types and reference descriptions; default dependency identities remain unchanged |
| D56 | Proposed | Reconstruct current function bodies from exact last-successful immutable grammar while freshly lexing all source and parsing declarations | [Proposal 0028](proposals/0028-function-body-syntax-reuse.md); [body syntax experiment](body-syntax.md), current spans, fresh mutable AST/types, semantic validation and shared limits; default parsing unchanged |
| D57 | Proposed | Run bounded explicit native/output or first-diagnostic cases through the shared frontend, capturing full signed main results with a private C driver | [Proposal 0029](proposals/0029-native-test-manifests.md); [test manifests](testing.md), exact expectations and bounded current receipts; no new syntax, packages, foreign ABI or hostile-code sandbox |
| D58 | Proposed | Reconstruct bounded sequential UTF-16 editor deltas atomically, requiring full resynchronization after rejected newer batches | [Proposal 0030](proposals/0030-incremental-editor-synchronization.md); [editor synchronization](editor-synchronization.md), fresh shared checking, version ordering and blocked stale queries; no incremental parser or performance claim |
| D59 | Proposed | Port the existing checked compact agent index to the standalone native compiler with byte-identical differential output | [Proposal 0031](proposals/0031-native-compact-agent-context.md); sorted current signatures/record fields, explicit compact mode and first-error rejection; full context v2, caching, native LSP and measured agent/latency benefits remain open |
| D60 | Proposed | Port the reference's bounded token/comment-preserving layout to read-only native formatting and check mode | [Proposal 0032](proposals/0032-native-canonical-formatting.md); shared syntax-only validation, output/re-lex guards and exact module provenance; native replacement/revision guards, editor integration and measured benefits remain open |
| D61 | Proposed | Evaluate pinned text-only Codex CLI through ChatGPT login with explicit invocation bounds and unknown dollar costs preserved | [Proposal 0033](proposals/0033-codex-subscription-evaluation.md); optional adapter and unchanged independent acceptance; invocation limits differ from token/quota/billing limits |

## Open decisions

| Decision | Questions to resolve |
| --- | --- |
| Compiler implementation | Which native implementation/backend and packaging meet R24? The owner kept this open on 24 September 2026: Rust is the leading candidate (D41); choose the backend after in-process measurements on larger generated inputs separate parsing cost from start-up. |
| Development reload | Which dependency/cache, internal ABI, state-invariant, safe-boundary and restart contracts meet R25 without adding mandatory release overhead? |
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
