# Proposal 0024: Shared pollable object-build continuations

- Status: Draft; implemented reference API experiment
- Author(s): Talven contributors
- Requirements affected: R08, R12, R24, R25
- Decisions affected: D38, D50, D51, D52 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

The [command primitive](../compiler-commands.md) allows bounded polling and group cancellation, but private object builds still coordinate all commands synchronously. A later watcher needs a sequential native build that can yield between commands and unwind an unfinished candidate without duplicating cache correctness.

## Proposal

Express preparation/compile/link commands as immutable `CompilerRequest` snapshots yielded by one shared build continuation. Retain the synchronous `build(source)` and standalone preparation wrappers; add `start_build(source)` with an owned polling driver. The latter synchronously validates current source and initializes the first request, then exposes non-waiting command polling, current phase/PID, explicit/context-managed cancellation and an ordinary result only after full success.

Both drivers use identical fresh preparation, source/compiler/configuration keys, artifact verification, linking and final promotion. Request deadlines include queue delay and cannot restart a budget at launch. Keep command/input/environment immutable, capture directory once and retain existing resource/timeout assumptions. Allow one active build per session. Unwind candidate cleanup and reset session availability on cancellation, failure or interruption; preserve last-successful objects/probes. Define the full [API lifecycle contract](../build-pipeline.md).

## Alternatives and implications

Duplicating synchronous and event-loop build algorithms risks divergent invalidation or promotion. A worker/thread still requires cancellation/IPC/shared-state contracts. A sequential continuation retains one owner and common checks while using the bounded command primitive. It adds request/generator bookkeeping; frontend, hash/file operations, request creation and cleanup still run synchronously. There is no latency or memory improvement claim.

## Publication and trust

The explicit trusted stable-toolchain contract remains. Requests are trusted internal compiler invocations, not permissions received from source or receipts. Cancelling before successful completion cannot promote partial state. A fully completed native snapshot can become the last-successful private cache even if a watcher subsequently discovers newer source; a watcher must independently gate application execution on current observations. No source watcher, destination write, process restart, runtime dispatch, borrowing extension or state-preserving reload is added in this increment.

## Evaluation

Compare blocking/polling current C/object identities, work decisions and native output across valid edits. Cancel and force failures in preparation, compilation and linking; prove candidate removal, previous executable survival, unchanged cache/probe state and repaired-object reuse. Reject invalid source/drift before launch, preserve immutable requests, include delayed request expiry, handle interruption and reject malformed continuations. Existing shared-build/native/sanitizer tests remain required, alongside the full reference and documentation suites.

## Remaining work

Integrate explicit opt-in watcher mode, source freshness, old-program lifetime and isolated deployment copies; record actual revision/event timing and cancellation evidence. Representative asynchronous build/watch costs, state preservation, broader dependencies/modules and design acceptance remain open.
