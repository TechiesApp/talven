# Talven

*Clarity down to the machine.*

Pronounced **TAL-ven**.

A proposal for a native programming language designed first for LLM coding agents, with a clear source language for humans, strong safety, and explicit control over hardware and resources.

**Status: design stage.** This repository records requirements and proposed architecture for Talven. It does not contain a working compiler, runtime, package manager, or benchmarks. The language name was selected on 7 September 2026.

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

- Features described here are requirements or proposals, not implemented guarantees.
- High-level convenience must have visible dependencies and costs.
- A universal translator cannot be assumed to remove every foreign runtime, garbage collector, or semantic difference.
- A language cannot guarantee integrity after every possible kernel, firmware, hardware, or key compromise.
- GPU portability requires a supported subset and explicit access to vendor-specific functionality.
- Provider prompt caching and local compiler/context caching are different mechanisms.

## First implementation objective

Prove the agent workflow alongside a small safe native subset: compile a useful program, obtain relevant context, make a bounded change, and verify it on ARM64 and x86-64. Evaluate small-system feasibility early before expanding the runtime and ecosystem.

## Project status

The language is named **Talven**. Its public repository is [TechiesApp/talven](https://github.com/TechiesApp/talven). Implementation language and final grammar remain open decisions. Design work proceeds through [design proposals](docs/proposals/README.md) and GitHub Discussions.

## License

Talven is licensed under the [Apache License, Version 2.0](LICENSE). Contributions are accepted under the same license and must be signed off under the [Developer Certificate of Origin](https://developercertificate.org/); see [CONTRIBUTING.md](CONTRIBUTING.md).
