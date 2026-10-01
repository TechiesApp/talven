# Proposal 0023: Pollable bounded compiler commands

- Status: Draft; implemented reference command primitive
- Author(s): Talven contributors
- Requirements affected: R12, R21, R24, R25
- Decisions affected: D38, D40, D50, D51 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

The private object build API synchronously preprocesses, compiles and links. Directly calling it in the watcher would block source observation during those commands and delay superseded-build cancellation. Define a bounded command step before integrating a multi-command build pipeline.

## Proposal

Factor the existing bounded trusted subprocess runner into `BoundedCommand`, with owned stdin/pipes/selector/process group, non-waiting `poll()` and explicit/context-managed `close()`. Read at most 64 KiB per poll, return `None` while pending and exact stdout bytes only after EOF plus successful exit. Preserve the established non-reaping exit check and child-group cleanup, including lingering descendants. Keep `run_bounded` as a synchronous compatibility wrapper used by current prepared-unit/object builds.

Capture the caller-provided environment and directory for command creation. Enforce input/stdout/stderr, wait and timeout bounds, and close owned resources on launch/poll failure or interruption. Document the exact limits and synchronous lifecycle costs in [the primitive contract](../compiler-commands.md). Do not change ordinary build/dev, execute Talven programs, add a watcher option or claim a nonblocking frontend/native build pipeline yet.

## Alternatives and costs

Running the whole synchronous build in the watcher delays observations. Moving all work to a thread adds concurrent state/cancellation ownership before the cache protocol is ready. A long-lived external worker adds IPC, publication and recovery contracts. A pollable command allows later sequential pipeline stages to remain owned by one event loop. Poll/read granularity and process cleanup still add costs; no performance guarantee follows from the interface.

## Trust and lifecycle

Commands are trusted caller-provided argument lists, not shell strings or authority derived from retrieved source. This is resource ownership and cancellation, not isolation or complete compiler identity. Retain the unreaped direct child until signaling its group to avoid reusing a group identity. Both EOF and exit matter; descendants holding descriptors keep the command pending. A caller must continue polling or close an abandoned command. Host failure, uncatchable termination and group escape remain outside this contract.

## Evaluation

Exercise pending commands while the caller observes changed file bytes, exact environment/directory/stdin output, multi-buffer drains with a per-poll read budget, empty successful output, usage/launch/command failures and timeouts. Cancel TERM-resistant child groups; let a leader exit while a descendant owns pipes and prove its PID remains reserved until cleanup. Run existing real-C preparation/object/sanitizer cases and the full reference/documentation checks. No test fixture constitutes a Talven language API for subprocesses, signals or sleeping.

## Remaining work

Build-stage continuation/ownership, cache promotion through cancellation, fresh watcher source publication, old-program lifetime, aggregate pipeline budgets and actual save-to-running latency must be implemented and verified before native watcher reuse is offered. Design acceptance remains separate from this primitive.
