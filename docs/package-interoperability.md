# Existing package ecosystems

Status: proposed interoperability strategy. No package adapter is implemented.

## Goal

Reuse useful existing libraries without waiting for an entirely new ecosystem. Preserve the semantics and costs of the imported component, and expose a typed interface suitable for humans and agents.

Registry compatibility, source compatibility, binary compatibility, runtime compatibility, and licensing are separate dimensions. A package name resolving successfully does not establish that it can build or run on the selected target.

## Integration paths

| Ecosystem | Proposed first path | Costs and constraints to expose |
| --- | --- | --- |
| C | Native ABI bindings | Layout, pointers, ownership, allocator contracts, platform ABI |
| C++ | A stable wrapper boundary for selected APIs | Templates, exceptions, object lifetime, compiler/ABI compatibility |
| Rust / Cargo | Wrappers with a defined external ABI for selected libraries | Native Rust ABI assumptions, generics, ownership, panic and allocator contracts |
| npm / JavaScript | An optional compatible JS runtime and generated typed adapters | Runtime and GC footprint, event-loop behavior, native add-ons, dynamic semantics |
| Python packages | An optional compatible Python runtime and typed adapters | Runtime memory, extension modules, Python semantics, object conversion |
| Java / JVM | A suitable JVM bridge or an explicitly supported ahead-of-time integration | Runtime services, GC, reflection, threading, artifact compatibility |
| Go | Exported native entry points or a persistent worker interface | Go runtime and GC, callbacks, scheduling, foreign-call restrictions |

The exact compatibility of a package must be tested against its versions, target, runtime, and API surface. Descriptions above are architectural starting points, not a promise that every package is supported.

## Translation boundaries

A universal Rosetta-style translator with near-zero overhead is not an assumption of this project.

Binary instruction translation addresses a different problem from reproducing another language's object model, reflection, exceptions, garbage collection, scheduler, or package behavior.

Use these approaches deliberately:

1. Direct native calls where an ABI and ownership contract are compatible.
2. A restricted source translation experiment where semantics are specified and testable.
3. An embedded foreign runtime when its behavior is required.
4. A restricted persistent worker or suitable sandbox when isolation is needed.

Source translation should begin with a small, documented subset. Unsupported constructs must fail clearly; silent semantic changes are unacceptable.

## Bridge costs

Measure call overhead, marshaling, copies, synchronization, foreign runtime startup, steady-state RAM, garbage collection, and throughput separately.

Batch fine-grained operations and keep compatible buffers in place where ownership and synchronization allow it. A shared buffer is useful only with a sound lifetime and access contract.

A persistent local worker can amortize startup. A remote microservice adds transport, operational, and failure-management costs; use it for appropriately coarse work rather than assuming it is the cheapest boundary.

Define error, cancellation, timeout, callback, and partial-failure behavior for every adapter.

## Package manager direction

Provide a coherent project manifest that records the ecosystem origin, exact package version, source/artifact integrity, adapter version, foreign runtime requirements, toolchain, and target.

Delegate to existing ecosystem resolution and build mechanisms where necessary, then record a reproducible resolved graph. Reusing a registry does not mean the new language implements that ecosystem's complete package semantics.

Maintain a compatibility record per adapter and target. Make transitive native binaries, install scripts, runtime requirements, and network access visible before execution.

Review the distribution and license requirements of imported components before redistributing them. Public source availability is not a substitute for a package-specific integration decision.

## Security boundary

Native in-process code can bypass safe-language restrictions. A generated typed wrapper is not a sandbox and does not repair unsound foreign code.

Use reviewed native integration for trusted components. Isolate untrusted code in a genuinely restricted process or an appropriate sandbox, accounting for filesystem, network, secrets, device access, and resource limits.

Signed packages and provenance help establish origin and integrity. They do not prove the absence of malicious behavior.

## Staging

Start with one C library and one clearly specified native wrapper. Add one runtime ecosystem only after the native ownership and build interfaces are stable.

Publish a compatibility matrix and failure cases. Expand to the other requested ecosystems based on real workloads, not the size of a claimed registry catalog.

