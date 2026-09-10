# Proposal 0012: Development watch and restart

- Status: Draft; bounded experimental implementation
- Author(s): Talven contributors
- Requirements affected: R01, R08, R10, R24, R25; see [requirements](../requirements.md)
- Decisions affected: D38, new D40; see [decisions](../decisions.md)
- Discussion: Implementation pull request

## Problem

The greeting is runnable, but each edit requires a manual build and execution. Humans and agents need a session that refreshes successful revisions, reports failed edits, and avoids running obsolete candidates or overlapping program instances. A runnable refresh loop also gives later compiler work a concrete feedback boundary to measure.

## Proposal

Implement Stage A of [Proposal 0010](0010-fast-compiler-and-development-reload.md): `python3 -m talven dev SOURCE`, with explicit console support and an optional new JSONL receipt file. The [development guide](../development.md) specifies the implemented contract.

Poll one file's bounded bytes, assign session revisions, debounce observed save bursts, and compile snapshots with the shared frontend/backend and ordinary full-build C flags. Preserve a live old process on compilation failure. Cancel superseded compilation and recheck freshness before replacement, including after the old process stops. Stop/reap before launching the candidate; report startup failure without claiming rollback. Track natural exit separately from session exit. Temporary candidate artifacts are removed as jobs finish or the session shuts down.

Use separate POSIX process groups for compiler and native program, bounded TERM/KILL cleanup, bounded compiler output, and a build deadline checked by the event loop. This is trusted local execution; neither arbitrary descendant escape nor uncatchable watcher termination is solved by process groups. Polling and a final read cannot provide a transactional lock against another writer.

The session reports exact observed source hashes and actual elapsed observation-to-event times. `started` means process creation, not readiness or correctness. Keep source identity, running revision, and current diagnostics distinct. Changing toolchain or compiler files requires a fresh session. There is no compiler cache, incremental reuse, state preservation, or additional support inside emitted applications.

## Examples

Implemented command, from the repository root:

~~~sh
python3 -m talven dev examples/hello.tal --console
~~~

Save a changed greeting to rebuild/rerun. An invalid edit reports diagnostics while any old live process remains active. Hello World normally exits immediately; this example demonstrates repeated execution, not state preservation.

## Alternatives considered

- External generic watcher: useful today, but does not itself define Talven source revision receipts or candidate publication rules.
- Wait for a native incremental compiler: delays testing the development session contract and conflates correctness with speed.
- Start each build from the mutable source path: can associate diagnostics/output with the wrong observed revision. Read snapshots instead.
- Run old and new programs concurrently: risks duplicate consumers and competing resources. Stop before replacement.
- OS-specific notifications first: potentially lower idle work, but requires more platform machinery. Bounded single-file polling gives an explicit initial contract; benchmark before changing it.

## Costs and implications

- Agent context: a new command and small receipt schema; ordinary frontend diagnostics and hashes retain their meaning.
- Runtime and memory: no watcher or loader in generated binaries. The developer session consumes Python/process/polling resources, bounded source/compiler-output memory, temporary artifacts, and an optional growing receipt file.
- Security: trusted compiler/program execution inherits user capabilities. Separate process groups and exclusive receipt creation do not replace an OS sandbox or external writer coordination.
- Targets: POSIX implementation, with Linux ARM64/x86-64 as initial CI evidence gates. Windows and freestanding reload remain separate.
- Ecosystem: no foreign ABI, module, package, UI framework, or readiness protocol is introduced.

## Evaluation

Behavioral tests must demonstrate exact native output before/after edits, invalid-edit recovery, unchanged-metadata detection, coalescing, stale build suppression, edits during old-process shutdown, cleanup of compiler/program children, timeouts, noisy compiler rejection, process exit/startup failures, and non-destructive receipt creation. Clearly label doubles used to exercise lifecycle behavior unavailable in Talven's current subset. Preserve independent compiler/agent acceptance and execute the full native CI matrix without skips.

Retain actual session receipts when evaluating performance; record source edits, toolchain, hardware/environment, options and correctness. No latency budget, speedup, token/cost saving, production readiness, or full M1 completion follows from this implementation.

## Unresolved questions

Native compiler choice, dependency-aware persistent compilation, workspace watch identity, event-driven filesystem backends, developer diagnostics UI, application readiness, state migration, hot-reload safe points, and benchmarks representing long-running applications remain later work.
