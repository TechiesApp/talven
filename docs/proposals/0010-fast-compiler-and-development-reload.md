# Proposal 0010: Fast compiler and development reload

- Status: Draft; records owner-requested performance and reload requirements. Implementation choices below remain proposals.
- Author(s): Talven contributors
- Requirements affected: R01, R03, R04, R08, R11, R12, R15, new R24 and R25
- Decisions affected: D08, D22, D24, D33, D34, new D35 through D38
- Discussion: Pull request introducing this proposal; owner design discussion on 8 September 2026

## Problem

Developers and agents need quick feedback after editing code. Fast generated programs alone do not meet that need: compiler startup, repeated checking, code generation, linking and restarting all contribute to the development loop. Ordinary small changes should reuse unaffected work rather than require full compilation every time.

The existing compiler is Talven's own implementation, written in Python with a C11 backend. Python is a bootstrap choice, not a permanent product requirement. It is needed by the compiler, not by the generated executable. A packaged native compiler, incremental compilation and state-preserving hot reload are **unimplemented**. [Proposal 0012](0012-development-watch-and-restart.md) now supplies an experimental [single-file watcher and restart command](../development.md) using full builds. Existing context hashes and edit previews establish neither incremental dependency tracking nor a safe reload protocol.

## Proposal

### Native compiler direction

Treat fast startup, checking, builds and rebuilds after edits as explicit product requirements. Prototype a native compiler early, before broad runtime and ecosystem expansion. Rust is the leading candidate to evaluate, not a selected production dependency. Retain the Python reference and independent behavioral acceptance: a replacement must demonstrate equivalent language semantics, diagnostics, borrowing, context and native results on its declared scope.

Evaluate frontend implementation and backend separately. Moving the frontend out of Python would not remove the current C compilation/linking stage. A native compiler executable also need not bundle its backend, linker, headers or system libraries; its distribution must disclose these dependencies. Self-hosting in Talven is a separate later choice, not a prerequisite for speed.

Evaluate fast code generation, including Cranelift as a candidate, against the C11 baseline. Prefer short development builds with the same language semantics and required runtime checks. More expensive release optimization can be a separate profile. Do not choose a backend or promise speedups from implementation-language reputation or the small, variable [current baseline](../tooling-baseline-evidence.md).

### Stage A: Watch and restart

Provide an explicit development session which watches a selected source/workspace and runs its program after successful builds. Its first version may use the existing compiler and full build. This provides automatic refresh, but must not be described as incremental compilation or state-preserving hot reload.

- Coalesce save bursts and assign revisions to builds. A superseded result must never replace a newer running revision, even when builds finish out of order.
- Build a separate candidate executable. Keep the working process running while compiling; syntax, type, borrow or build failure shows diagnostics and leaves that process alone if it is still alive.
- After the newest candidate passes its required checks, perform a controlled stop/start. Release old resources before restarting; do not launch duplicate consumers of the same resources. Short-lived programs such as Hello World simply run again.
- Restart loses in-memory state and reruns initialization. A process that already exited cannot be kept running. If startup fails after the previous process has stopped, report failure; restart is not an atomic rollback guarantee.
- Shut down the session without orphaning builds or programs. Display whether a revision was rejected, restarted or is still running. Future machine-readable receipts should expose these states to agents too.

This is the initial meaning of live reload for native Talven programs. Browser refresh or UI redraw requires integration with a selected framework, which does not exist in Talven today.

### Stage B: Persistent incremental compilation

Keep a compiler service alive during development. Reuse parsing/analysis results and compiled artifacts through an explicit dependency graph. Recheck and regenerate changed units plus everything affected by changed contracts, types, borrowing permissions, constants or inlined bodies. Relink when necessary; restart does not inherently require recompiling unchanged code.

Cache identity must cover relevant source/dependency inputs, compiler/schema versions, target, options and toolchain assumptions. A stable function signature cannot validate an artifact that embedded a changed callee body. Reject and rebuild corrupt or incompatible cache entries, recording why. Reuse must not relax ownership rules or independently required acceptance checks.

CLI, LSP and agent tooling should share semantic queries and revision identities. Context v2's direct-call list is not a complete build invalidation graph. Persistent queries, stable symbol identity, modules, compilation units and incremental linking need explicit design and verification as this stage is implemented.

Ordinary edits should avoid full compilation; global configuration or dependency changes may require broader rebuilding. Compare cold startup, warm no-change requests and edits separately. Persistent service state must not hide stale source or diagnostics.

### Stage C: Restricted state-preserving hot reload

Add an optional development loader for explicitly reloadable units with defined code and state contracts. Start with eligible function-body changes and stable interfaces/state layouts. A native loader can replace compiled code; this design does not require a JVM, Node or Python interpreter inside the application.

| Change | Initial proposed handling |
| --- | --- |
| Opt-in body edit with unchanged interface/state contract | Recompile affected units and publish new code at a safe boundary; retain state |
| Record size, alignment, field layout, function signature or borrowing/ownership contract | Recompile affected units and restart; no implicit state migration |
| Initialization or state-invariant change | Explicit restart to re-establish initialization and state assumptions |
| Target, backend, toolchain or reload-contract change | Restart with appropriate cache invalidation; potentially a full rebuild |
| Compilation/validation failure | Reject candidate; keep currently running code and state |
| No safe reload boundary available | Defer with a bounded wait, then report restart required |

The applying host must prevent new calls entering affected code and establish that old frames, callbacks and borrowed references no longer depend on it before replacement or unloading. All affected units must switch to one consistent generation. Staging must not run application initialization or mutate live state. Failure before publication must preserve the old generation; this does not promise to undo application I/O or other effects after publication.

Unchanged layout and signatures are necessary eligibility checks, not proof that old state remains meaningful. Reloadable code needs explicit state invariants; developers can request restart even for an otherwise eligible edit. No automatic heap-state migration, stack-frame rewriting or preservation of arbitrary foreign handles is promised. The single-threaded, call-scoped borrow checker alone cannot establish loader safety. Threads, suspended tasks and foreign callbacks need additional lifetime and safe-boundary rules before participating.

Changed code takes effect when it runs again. Reload does not retroactively rerun earlier calls, main or initializers. A future UI/event framework may offer a refresh hook with its own tested contract.

### Keep development support optional

Release builds should omit the development loader, watcher, reload dispatch and metadata. Both development and release must preserve Talven's type/ownership and observable arithmetic rules. Development speed must not come from silently disabling required safety checks.

Production programs remain native, with their selected platform/runtime dependencies explicit. Reload support must not become a mandatory freestanding-core dependency. Verify its absence from release artifacts rather than claiming zero overhead from this design alone.

## Examples

These command names are **illustrative future interfaces**, not commands supported by today's CLI:

~~~text
talven dev examples/hello.tal
talven build --release examples/hello.tal
~~~

A future example could print `Hello, world!`, then print changed text after a save. Stage A rebuilds and reruns it; Stage B reuses unaffected work. A short-lived Hello World process cannot demonstrate state-preserving hot reload. Stage C needs a separate long-running fixture with observable state and a controlled safe boundary.

## Alternatives considered

- Keep Python permanently: it remains useful as a reference, but production implementation should be selected against measured startup, throughput, memory and feedback costs.
- Rewrite everything immediately: replacing frontend, backend and runtime together makes regressions harder to isolate. Start with a bounded native implementation and preserved independent tests.
- Watch plus full rebuild forever: useful initially, but does not meet the incremental development objective for ordinary edits.
- Promise hot reload for every edit: incompatible state/layout/lifetime changes require migration rules or restart.
- Require a permanent managed runtime for reload: conflicts with the lightweight optional-runtime direction. Evaluate a development-only loader first; a JIT is an optional implementation technique, not a language requirement.
- Change only the implementation language: algorithms, dependency tracking, code generation and linking can still dominate feedback time.

## Costs and implications

- Agent context: explicit diagnostics and running/build revisions reduce ambiguity, but no token or task-cost improvement is inferred. Model benchmarks remain separate.
- Runtime and memory: a persistent compiler consumes development-machine memory; caches consume disk. Reload indirection, metadata and retained code consume development resources. Measure and bound these costs and old-generation retention.
- Security: the session compiles and executes selected application code under host permissions. Watchers, hashes and loaders are not a sandbox or release authority. Source comments do not authorize deployment, provider use or unrelated commands.
- Targets: prove execution and reload on declared Linux ARM64/x86-64 hosts first. Platform loaders, executable memory rules, filesystems and linkers need per-target evidence. Freestanding/board hot reload is outside the initial scope.
- Ecosystem: internal reload contracts are distinct from the future public foreign ABI. Foreign runtimes, GPU work, suspended tasks and arbitrary handles do not automatically participate.

## Evaluation

Measure from an observed save/revision event to diagnostics and to verified execution of the new revision. Record build-start/check/code-generation/link/restart/publication boundaries so file detection or debounce delay is not omitted. Distinguish detection latency from latency measured from a controlled save operation. Record cold/warm cache state, retained memory and cache size. Verify that fast refresh actually executes the newest accepted code.

Use fixed edits covering a function body, public signature, record layout, borrow permission, initialization, invalid source and a correction. Include save bursts, out-of-order completion, failed builds, failed startup, busy safe boundaries, stale/corrupt caches, process exit and session shutdown. Require fresh-build equivalence for incremental artifacts and deterministic errors on the same revision. Preserve independent arithmetic, ownership/borrowing, native and agent acceptance tests.

For hot reload, verify preservation for eligible changes, restart requirements for incompatible changes, unchanged old state on pre-publication rejection, and no use of unloaded code or stale borrowed references. Combine behavioral tests with relevant native sanitizers; these do not prove arbitrary state compatibility. Check release artifacts separately for absence of reload support.

Record actual hardware, OS, compiler/backend/toolchain versions, inputs/edits, flags, cache state, background load, sample order and repetitions. Retain all samples and failed attempts. Set performance budgets from representative baselines: no numeric latency, memory, speedup or portability claim is made here. The existing offline CLI baseline does not measure these proposed persistent/reload paths.

## Roadmap placement

Keep the first visible console program and watch/restart loop as small early M1 increments. [Proposal 0011](0011-static-text-and-console-output.md) now supplies the first [static-text console implementation](../text-console.md), including encoding, I/O failure behavior and freestanding boundaries. Use it as a concrete refresh workload; the [development command](../development.md) now supplies full-build watch/restart.

Prototype the native compiler and dependency-aware development architecture before broad M2–M6 expansion. Add persistent incremental operation after demonstrating its invalidation rules. Restricted hot reload follows explicit module/state contracts and safe boundaries; concurrency extensions depend on the M2 lifetime model. Initial development refresh should not wait for M5 or require a general public FFI.

Controlled agent evaluation remains an independent M1 gate. No live provider call or paid model run is authorized by this proposal.

## Unresolved questions

Production compiler language/backend and packaging; module/compilation-unit identity; cache format/integrity; development versus release optimization; CLI/agent receipt schema; process shutdown/startup contracts; internal reload ABI; state opt-in/invariants; safe-boundary enforcement/timeouts; old-code reclamation; debugger integration; later async/foreign/GPU participation; and representative latency budgets remain open.

## Primary design references

- [Rust](https://rust-lang.org/) describes a native implementation-language candidate, not evidence of Talven compiler speed.
- [Cranelift](https://cranelift.dev/) describes a backend designed with compilation speed in mind. Talven integration and comparative results remain unmeasured.
- [Rust compiler incremental design](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html) explains dependency-aware reuse and invalidation tradeoffs; Talven has not implemented that system.
- [Flutter hot reload](https://docs.flutter.dev/tools/hot-reload) distinguishes state-preserving reload, restart and affected-library compilation. It is a developer-experience reference, not a Talven runtime or compatibility promise.
