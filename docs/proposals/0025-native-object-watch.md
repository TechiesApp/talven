# Proposal 0025: Opt-in native object reuse in watch/restart

- Status: Draft; implemented reference development experiment
- Author(s): Talven contributors
- Requirements affected: R08, R12, R24, R25
- Decisions affected: D38, D40, D50, D52, D53 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

Private object builds have current-source correctness, integrity and cancellation evidence, but ordinary watch/restart still compiles whole C. Integrating reuse needs source freshness and deployed-program lifetime to remain separate from a compiler cache's successful snapshots.

## Proposal

Add paired `dev --incremental-build --stable-toolchain` flags. Keep default dev/build unchanged and exclude `--incremental-check` from this mode: native-object mode still fully checks current source. Own one [pollable build continuation](../build-pipeline.md), observe source between command steps, cancel superseded work and preserve failed-build/last-successful object/probe retention. Use the same hosted console/entry and source limits, with the private API's explicit trusted stable-toolchain obligation.

After native completion, confirm source identity, reobserve freshness and create a separate verified bounded deployment copy. The old program's file/lifetime cannot depend on compiler-cache replacement. Reuse the existing before/after shutdown freshness checks and stop/reap-before-start process restart rules. A fully successful native snapshot can remain cached even if subsequently superseded for execution; unfinished candidates never promote. Define exact limits, polling cadence, cleanup, flag semantics and additive work receipts in [the mode contract](../native-watch.md).

Expose `build_mode: units`, compiler phase/PID steps and completed candidate compiled/reused IDs/probe/byte identities through current source-revision receipts. Suppress per-command human log noise while retaining JSON steps. Successful compilation is not task correctness, application readiness or current publication. No runtime loader, dispatch, state migration, escaping borrow lifetime, source writing, user-selected destination or release cache dependency is introduced.

## Alternatives and costs

Calling the synchronous builder delays observations and cancellation. Reusing the cache executable path directly couples live program files to replacement/eviction. Sharing object/check modes prematurely obscures whether source was fully checked; keep explicit mutually exclusive experiments. Private units still repeat global contracts, preprocess/link afresh and can make cold/global builds much slower. Prior local timings are mixed and are not watcher measurements; keep opt-in without claiming improvement.

## Trust and publication

Preserve the stable trusted toolchain assumption, byte-integrity checks and owned temporary/process-group scope. Source observations and final launch are not one atomic filesystem transaction. Source-only watching omits broader dependencies/modules/readiness. A native accepted snapshot is not authority to execute when the current watch revision differs. Last-moment compiler/source byte checks are not authenticated code or protected release enforcement.

## Evaluation

Require existing watch behavior and shared compiler/native/sanitizer suites to pass. Verify real native output and work decisions over initial/body/comment/contract/invalid/repair edits; cancel slow superseded preprocessing and fail linking without losing successful artifacts; cover timeout and session shutdown. Use explicitly labeled lifecycle doubles to prove old-process survival, deployed-file lifetime through cache replacement and saves during shutdown preventing stale replacement starts. Enforce paired flags, separate check/native modes and source/event-path protection. Linux CI requires native evidence without skips.

## Remaining work

The [actual watcher runner](../native-watch-baseline.md) now records initial/atomic-edit-to-receipt behavior with retained inputs and independent native task checks. Representative readiness, long-running shutdown and concurrent-edit latency still need separate measurements before broader improvement claims. Production backend/default selection, incremental parsing/shared native tooling, finer dependencies, imports, readiness and state-preserving reload require separate evidence/design. Acceptance remains separate from this experiment.
