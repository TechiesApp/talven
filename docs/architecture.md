# Proposed architecture

Status: proposed design, not an implemented system.

## One semantic foundation

The compiler should own parsing, types, ownership analysis, effects, module resolution, and target constraints. The CLI, editor LSP, and agent interface should query this shared semantic model.

The compiler remains the authority when an agent's interpretation or a cached summary disagrees with source.

~~~mermaid
flowchart TD
    Human["Human editor"] --> LSP["LSP"]
    Agent["Coding agent"] --> API["Context and edit API"]
    LSP <--> Semantics["Compiler semantic model"]
    API <--> Semantics
    Source["Source, dependencies, target"] --> Semantics
    CLI["Developer CLI"] --> Semantics
    Semantics --> Native["Typed IR and native code generation"]
    Native --> Link["Target linker"]
    Core["Freestanding core"] --> Link
    Modules["Selected allocation, OS, async, GPU, or foreign modules"] --> Link
    Link --> Program["Target executable"]
    Program --> Hosted["Hosted OS and supported drivers"]
    Program --> Board["Freestanding board support"]
~~~

The diagram describes proposed relationships. It does not imply an existing server, protocol, or executable. A build selects a deployment target and the modules it needs; it does not need both hosted and freestanding support.

See the [detailed architecture diagrams](architecture-diagrams.md) for the agent verification loop, protected release boundaries, and CPU/GPU resource lifetimes.

## Compiler direction

Use ahead-of-time native compilation as the default. A mature backend such as LLVM is a candidate for optimization and CPU target coverage; the backend decision needs a prototype and target evaluation.

Keep a typed intermediate representation before lowering to machine-oriented code. Preserve source locations and ownership/effect information for diagnostics.

Prefer deterministic module interfaces and incremental dependency analysis. Public function boundaries should state contracts explicitly, while local type inference can reduce repetition.

The M1a reference compiler uses Python and a C11 backend to exercise the shared semantic model and native execution. The production bootstrap language and backend remain undecided. Do not commit to self-hosting before the semantics and toolchain are useful. See the [prototype scope and tradeoffs](prototype.md).

Fast compilation is now an explicit requirement. [Proposal 0010](proposals/0010-fast-compiler-and-development-reload.md) calls for an early native implementation experiment with preserved independent acceptance, evaluating frontend and backend costs separately. Rust and Cranelift are candidates, not selected dependencies. A packaged native compiler, persistent semantic service and incremental build graph are not implemented yet.

## Small native core

The smallest profile should support ordinary computation with stack and static storage, strict types, defined control flow, and platform-independent core operations. It should not require a heap, tracing garbage collector, OS, event loop, or foreign-language runtime.

Optional library and runtime components:

| Component | Responsibilities | Cost that should remain visible |
| --- | --- | --- |
| Core | Primitive types, control flow, basic collections over supplied storage | Generated code and required checks |
| Allocation | Heap containers, arenas, allocator interfaces | Allocation, deallocation, metadata, fragmentation |
| OS integration | Files, clocks, processes, synchronization | Platform support and system calls |
| Async execution | Task scheduling, timers, I/O readiness | Executor state, task storage, polling or completion work |
| CPU parallelism | Bounded workers and scoped parallel tasks | Threads, queues, synchronization |
| Services | HTTP, serialization, database adapters, cryptography | Selected libraries, buffers, connections |
| Foreign runtimes | JS, Python, JVM, or other runtime adapters | Runtime footprint, GC, marshaling, compatibility requirements |
| GPU backends | Device discovery, buffers, queues, kernels, vendor APIs | Driver/runtime dependencies and device resources |

These are architectural groups, not finalized package names. Tooling should expose transitive dependencies. Selecting a small module must not silently pull in a full application runtime.

Modularity applies to libraries, runtimes, backends, and tools. Avoid arbitrary plugins that redefine the core grammar or safety semantics differently in every project.

## Bun-like experience

Provide one coherent developer entry point for building, running, testing, formatting, documentation, package operations, and LSP integration.

A capable development installation does not require a large deployed executable. Build tools and optional development services can stay on the developer machine.

The [prototype guide](prototype.md) and [formatting guide](formatting.md) describe the implemented CLI commands. Production installation and the broader toolkit remain open design work.

Design the development loop alongside the compiler: watch/restart first, dependency-aware incremental compilation next, then optional state-preserving reload at defined safe boundaries. The experimental [development command](development.md), `python3 -m talven dev`, now watches one file and performs full builds with process restart; later ordinary edits should reuse unaffected work. Keep errors from replacing a working revision, require restart for incompatible state/interface changes, and omit development reload support from release builds. The [reload proposal](proposals/0010-fast-compiler-and-development-reload.md) defines the staged intent and remaining contracts.

## Targets and ABI

A target description must identify the architecture, ABI, operating environment, and required SDK or board support. Initial hosted targets are proposed as Linux ARM64 and Linux x86-64, followed by additional platforms based on evidence.

Support explicit data layout and a well-defined foreign boundary. A C-compatible boundary is the proposed first integration surface. Generic language types, closures, unwinding, ownership, and allocator behavior need explicit conversion rules.

Freestanding support needs its own startup, linker, allocator, panic, interrupt, and device-access arrangements. CPU code generation alone does not provide a board support package.

## Safety and performance

Prefer static checks where they can enforce a property. Keep necessary runtime checks visible and optimize them away only when the compiler proves them redundant.

Expose allocation, blocking, unsafe operations, and platform effects in tooling. Do not advertise an abstraction as free without generated-code and workload evidence.

Controlled low-level operations belong in explicit unsafe modules with safe wrappers where soundness can be established. Their contracts become part of the trusted computing base.
