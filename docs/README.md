# Talven documentation

Pick the path that matches why you are here. Documents marked *evidence* record what was actually run and measured; the others describe behavior or design.

## New here

| Read | To learn |
| --- | --- |
| [Project README](../README.md) | What Talven is, what works today, and how to try it |
| [Language reference](language-reference.md) | Every rule of the implemented language on one page |
| [Benchmarks and evidence](benchmarks.md) | Measured agent, speed, size, and correctness results |
| [Contributing](../CONTRIBUTING.md) | Setting up, running checks, and opening a pull request |

## Using the compiler and tools

| Read | To learn |
| --- | --- |
| [Prototype guide](prototype.md) | Commands, diagnostics, compiler context, the LSP, and design tradeoffs |
| [Static text and console output](text-console.md) | `str`, `print`, and the Hello World contract |
| [Borrowing guide](borrowing.md) | Shared and exclusive borrows, mutation, and evaluation order in depth |
| [Formatting](formatting.md) | The canonical formatter shared by the CLI and the LSP |
| [Development watch and restart](development.md) | `talven dev`: rebuild and restart on save |
| [Edit previews](edit-validation.md) | Checking a candidate edit against an exact source revision |
| [Freestanding Linux execution](freestanding.md) | Building without libc or an allocator |
| [Native compiler prototype](../experiments/native-compiler/README.md) | The Rust implementation of the scalar subset |

## Agent evaluation

| Read | To learn |
| --- | --- |
| [Evaluation harness](../experiments/README.md) | Corpora, conditions, acceptance, accounting, and how to run |
| [Provider adapters](../experiments/adapters/README.md) | The Anthropic Messages adapter and the Claude Code CLI transport |
| [First live pilot](pilot-evidence.md) | *Evidence:* Claude Opus 5.5 on both corpora |
| [Evaluation validation](evaluation-validation.md) | *Evidence:* harness behavior with offline fixtures |
| [Borrowing evaluation validation](borrowing-evaluation-validation.md) | *Evidence:* the borrowing corpus offline |
| [Anthropic adapter validation](anthropic-adapter-validation.md) | *Evidence:* adapter protocol and accounting offline |

## Design and direction

| Read | To learn |
| --- | --- |
| [Requirements](requirements.md) | The product requirements and the current evidence for each |
| [Roadmap](roadmap.md) | Milestones M0–M6 and their evidence gates |
| [Decision register](decisions.md) | Accepted, proposed, and open decisions |
| [Design proposals](proposals/README.md) | How design changes are written and accepted, and the index of proposals |
| [Architecture](architecture.md) and [diagrams](architecture-diagrams.md) | Compiler, native core, optional modules, and targets |
| [Agent workflow](agent-workflow.md) | Context, diagnostics, caching, edits, and model evaluation |
| [Language, memory, and concurrency](language-memory-concurrency.md) | Proposed ownership, allocation, tasks, and errors |
| [GPU and platforms](gpu-platforms.md) | Host/device boundaries, backends, and portability |
| [Package interoperability](package-interoperability.md) | Reusing existing ecosystems and their costs |
| [Security](security.md) and [references](references.md) | Threat model, enforcement boundaries, and sources |

## Validation records

Each increment keeps its own *evidence* record, with hosts, tool versions, and test counts at the time:

| Increment | Record |
| --- | --- |
| M1a reference compiler | [Prototype validation](prototype-validation.md) |
| M1b formatting and native CI | [Formatting validation](formatting-validation.md) |
| M1c borrowing | [Borrowing validation](borrowing-validation.md) |
| Freestanding execution | [Freestanding validation](freestanding-validation.md) |
| Edit previews | [Edit preview evidence](edit-validation-evidence.md) |
| Tooling baseline | [Method](tooling-baseline.md) and [evidence](tooling-baseline-evidence.md) |
| Native compiler prototype | [Native compiler evidence](native-compiler-evidence.md) |

## Project

[Governance](../GOVERNANCE.md) · [Security policy](../SECURITY.md) · [Code of conduct](../CODE_OF_CONDUCT.md) · [Publishing notes](../PUBLISHING.md) · [Guidance for coding agents](../AGENTS.md)
