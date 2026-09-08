# Talven

*Clarity down to the machine.*

Pronounced **TAL-ven**.

A proposal for a native programming language designed first for LLM coding agents, with a clear source language for humans, strong safety, and explicit control over hardware and resources.

**Status: experimental compiler with M1c call-scoped borrowing.** The repository contains a small working reference compiler alongside the broader language proposal. It checks types, moves, shared/exclusive borrows, and scalar-field mutation; emits native programs through C11; returns structured agent context; and shares a canonical formatter between CLI and LSP. It is not a production language release or completion of the full M1 milestone. The language name was selected on 7 September 2026.

## Try the prototype

From the repository root, use Python 3.11+ and a C11 compiler named `cc` for native builds. Analysis uses only the Python standard library.

~~~sh
python3 -m talven check examples/vectors.tal --json
python3 -m talven fmt examples/vectors.tal --check --json
python3 -m talven context examples/vectors.tal --symbol dot --include-body
python3 -m talven build examples/vectors.tal -o build/vectors
./build/vectors
python3 -m unittest discover -s tests -v
~~~

The vector example exits zero when its calculation is correct. See the [prototype guide](docs/prototype.md) for grammar, ownership rules, diagnostics, context/cache identity, LSP integration, and freestanding emission. See the [validation record](docs/prototype-validation.md) for actual target evidence.

Native CI passed all **80 tests on Linux x86-64 and ARM64**, with no skips. All three jobs also passed six ASan/UBSan borrowing executions and built and ran both CLI examples. See the [M1c validation record](docs/borrowing-validation.md) for exact host, compiler, and job evidence.

The implemented subset has `i32`, `bool`, functions, conditionals, and move-only records containing scalars. [M1c borrowing](docs/borrowing.md) adds `let mut` record owners, shared `&Record` and exclusive `&mut Record` call arguments, and field assignment. References cannot be stored or returned. Escaping references, heap/resource cleanup, full LSP features, concurrency, GPU backends, package adapters, and comparative model benchmarks remain future work.

Try `python3 -m talven build examples/borrowing.tal -o build/borrowing`, then `./build/borrowing`. The example updates a record through an exclusive borrow and then reads it through a shared borrow.

## Product goal

Make it cheaper and more reliable for current open and proprietary LLMs to understand, change, check, and maintain systems software. Preserve native performance, a small deployment footprint, and direct control over CPU memory, GPU resources, concurrency, and platform capabilities.

The primary measure is **total cost per correctly completed coding task**, including context, generated tokens, repair attempts, tool calls, and verification. Shorter source text is useful only when it improves that result.

## Requirements at a glance

| Requirement | Intended direction |
| --- | --- |
| LLM and agentic coding first | A small regular grammar, compiler-generated context, structured diagnostics, precise edits, and reproducible verification |
| Human usability | Familiar syntax inspired by TypeScript, strict static types, predictable behavior, excellent LSP |
| Native systems programming | Ahead-of-time compilation, explicit layouts and allocation, safe ownership, controlled unsafe operations |
| Small default footprint | A freestanding core; allocation, OS services, async execution, networking, foreign runtimes, and GPU backends are optional |
| Rich developer experience | A coherent Bun-like toolkit for builds, tests, formatting, documentation, packages, and editor support |
| Existing ecosystems | Incremental adapters for native libraries and established language runtimes, with explicit compatibility and cost boundaries |
| CPU and GPU work | Structured concurrency, bounded CPU parallelism, synchronous and asynchronous APIs, explicit device memory and transfers |
| Broad deployment | ARM64 and x86-64 first; more operating systems, boards, and freestanding targets through declared support profiles |
| Security | Memory safety, least privilege, protected agent policy, trustworthy builds, and platform-specific integrity protections |

## Read the design

| Document | Purpose |
| --- | --- |
| [Prototype guide](docs/prototype.md) | Current implemented grammar, commands, contracts, limits, and design tradeoffs |
| [Prototype validation](docs/prototype-validation.md) | Historical M1a tests and initial x86-64 evidence |
| [Formatting guide](docs/formatting.md) | Canonical CLI/LSP formatting, explicit writes, and cache/target implications |
| [M1b validation](docs/formatting-validation.md) | Historical formatter checks and native CI evidence |
| [Borrowing guide](docs/borrowing.md) | Call-scoped loans, mutation, evaluation order, and context v2 migration |
| [M1c validation](docs/borrowing-validation.md) | Borrow rejection, native ordering/lifetimes, LSP/context, and sanitizer evidence |
| [Agent experiments](experiments/README.md) | Reproducible evaluation harness, independent acceptance, adapter protocol, and measurement accounting |
| [Evaluation validation](docs/evaluation-validation.md) | Actual harness test and offline fixture evidence, with unmeasured model metrics explicit |
| [Requirements](docs/requirements.md) | Traceable record of the product requirements and evidence needed to satisfy them |
| [Architecture](docs/architecture.md) | Compiler, native core, optional modules, target support, and toolchain |
| [Architecture diagrams](docs/architecture-diagrams.md) | Agent verification, protected release boundaries, and CPU/GPU resource lifetimes |
| [Agent workflow](docs/agent-workflow.md) | Context, LSP, diagnostics, caching, edits, and model evaluation |
| [Language, memory, and concurrency](docs/language-memory-concurrency.md) | Proposed syntax principles, ownership, allocation, tasks, and error handling |
| [GPU and platforms](docs/gpu-platforms.md) | Host/device boundaries, vendor backends, tiny systems, and portability |
| [Package interoperability](docs/package-interoperability.md) | Reusing existing packages and understanding the cost of integration |
| [Security](docs/security.md) | Threat model, enforcement boundaries, data integrity, and maintenance |
| [Roadmap](docs/roadmap.md) | Staged experiments and evidence gates |
| [Decision register](docs/decisions.md) | Requirements, proposals, unresolved decisions, and limits |
| [References](docs/references.md) | Primary guidance supporting the security discussion |
| [Design proposals](docs/proposals/README.md) | How a design change is written, discussed, and accepted |
| [Contributing](CONTRIBUTING.md) | How to propose and evaluate design changes |
| [Governance](GOVERNANCE.md) | Roles and how decisions are made |
| [Security policy](SECURITY.md) | How to report a security concern privately |
| [Code of conduct](CODE_OF_CONDUCT.md) | Expected behavior in project spaces |

## Scope and limits

- The prototype guide identifies implemented behavior; broader architecture features remain requirements or proposals.
- High-level convenience must have visible dependencies and costs.
- A universal translator cannot be assumed to remove every foreign runtime, garbage collector, or semantic difference.
- A language cannot guarantee integrity after every possible kernel, firmware, hardware, or key compromise.
- GPU portability requires a supported subset and explicit access to vendor-specific functionality.
- Provider prompt caching and local compiler/context caching are different mechanisms.

## First implementation objective

M1a starts the agent workflow and native subset; M1b adds canonical formatting and native CI; M1c adds a defined call-scoped borrowing subset. The [evaluation harness](experiments/README.md) now runs the initial corpus with independent native acceptance, source-only/compiler-context conditions, bounded repairs, and provenance-aware token/cost reporting. Offline fixtures validate the harness; no live model comparison or token savings is claimed. Consult the validation records for successful target runs. Completing M1 still requires controlled agent task evaluations and review of the implemented rules. Expand the runtime and ecosystem after these foundations have evidence.

## Project status

The language is named **Talven**. Its public repository is [TechiesApp/talven](https://github.com/TechiesApp/talven). M1a uses Python and C11 as an experimental bootstrap; the production compiler implementation and final grammar remain open decisions. Design work proceeds through [design proposals](docs/proposals/README.md) and GitHub Discussions.

## License

Talven is licensed under the [Apache License, Version 2.0](LICENSE). Contributions are accepted under the same license and must be signed off under the [Developer Certificate of Origin](https://developercertificate.org/); see [CONTRIBUTING.md](CONTRIBUTING.md).
