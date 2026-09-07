# Language, memory, and concurrency

Status: proposed semantics. Exact syntax, type rules, and implementation remain open.

## Syntax principles

Aim for familiar block structure, named fields, readable function signatures, local inference, and a single canonical formatter. Borrow familiarity from TypeScript without assuming JavaScript's runtime or dynamic semantics.

Prefer explicit public types, sum types for alternatives, exhaustive matching, generics, modules, and a limited set of composition mechanisms. Decide structural versus nominal typing deliberately rather than inheriting all of TypeScript's behavior.

Avoid implicit nullability, implicit narrowing numeric conversions, unrestricted dynamic values, and multiple overlapping ways to express the same operation. Define integer overflow, bounds failures, error propagation, and panic behavior before optimizing them.

An illustrative syntax sketch follows. It is not accepted grammar and does not compile in this repository.

~~~text
fn sum(values: view<i32>) -> i64 {
    let mut total: i64 = 0
    for value in values {
        total += i64(value)
    }
    return total
}
~~~

The sketch demonstrates an explicit read-only view, a public signature, and a widening conversion. The representation of views, borrowing syntax, and overflow handling still require a specification.

## Ownership and borrowing

Use single ownership of native resources as the starting point. Moving a value transfers ownership; explicit copying is available for appropriate types.

Allow shared read access and controlled exclusive mutation. Start with scoped borrowing rules that are practical to explain in diagnostics. Escaping borrows and borrows across asynchronous suspension require precise rules; they cannot be made safe just by omitting lifetime syntax.

Ordinary safe code should prevent use-after-free, double-free, invalid aliasing, uninitialized reads, and out-of-bounds access under the compiler and runtime's soundness assumptions.

Low-level work still needs explicit data layout, pointer operations, SIMD or intrinsics, and foreign interfaces. Put these in controlled unsafe boundaries and document the obligations of any safe wrapper.

## Allocation and reclamation

No mandatory tracing garbage collector in the native core.

| Mechanism | Proposed use | Explicit cost or limitation |
| --- | --- | --- |
| Stack and static storage | Small predictable data and freestanding code | Scope, lifetime, and capacity constraints |
| Owned heap allocation | Dynamic containers and resources | Allocator cost, fragmentation, failure handling |
| Arenas or regions | Groups of related temporary objects | Region lifetime and retained capacity |
| Explicit reference counting | Deliberately shared ownership | Counting overhead and possible cycles |
| Foreign runtime GC | Imported JS, Python, JVM, or other managed objects | The foreign runtime's reclamation and scheduling behavior |

Reference counting is not a universal solution to cycles. Use ownership redesign, weak references, explicit cycle handling, or an optional domain-specific collector when justified.

Native resource cleanup should be predictable, but destructors still execute work. Cleanup can block or need deferred device completion; tooling must not disguise that cost.

Define allocation failure behavior for each profile. A no-heap build must reject code that requires an allocator. Limits, quotas, and custom allocator selection should be visible to callers.

## Error and effect model

Prefer typed results for recoverable failures and explicit optional values for absence. Define cancellation, panic, resource exhaustion, and foreign exceptions separately.

Public interfaces should communicate allocation, blocking, I/O, unsafe operations, and relevant platform dependencies where the effect model can express them usefully.

Effect information should help the agent choose correct APIs. It must also remain compact enough for humans to understand.

## Synchronous and asynchronous work

A synchronous function executes in its caller's flow. An asynchronous function can suspend under a selected executor. Async is not automatically CPU parallelism.

Keep the executor optional. A small embedded program should not link a server runtime merely because the language defines async syntax.

Define whether task creation allocates, when execution starts, who owns the task, what awaiting does, and how cancellation is observed. Avoid undocumented detached work.

## Structured concurrency

Child tasks should have explicit owners or scopes. Exiting a scope must account for its tasks and resources; cancellation must not turn into dangling references or partially hidden work.

Bound queues and in-flight work. Support backpressure, deadlines, and explicit handling of cancellation and partial completion.

Specify how synchronous blocking calls interact with an async executor. CPU-heavy or blocking work should use an appropriate bounded worker facility rather than silently occupying an I/O event loop.

## CPU parallelism and synchronization

Provide scoped parallel tasks, channels or queues, mutexes, atomics, and parallel collection operations through suitable modules.

Safe cross-thread sharing needs ownership and synchronization rules. GPU completion and foreign callbacks need equivalent lifetime contracts at their boundaries.

Specify a memory model, atomic ordering semantics, and the conditions under which types can cross or be shared between threads. Syntax alone cannot establish data-race safety.

Hard real-time scheduling, lock-free algorithms, and hardware-specific tuning need explicit target and workload evidence. They are not default guarantees.

## First verification targets

Demonstrate safe rejection of invalid ownership and task lifetimes, bounded resource use, cleanup after errors, and correct interaction between cancellation and outstanding operations.

Measure allocation counts, peak RAM, fragmentation where relevant, task overhead, throughput, and tail latency. Compare safe abstractions with appropriate lower-level baselines without removing required checks merely to improve a benchmark.

