# Proposal 0022: Private last-successful native objects

- Status: Draft; implemented synchronous reference API experiment
- Author(s): Talven contributors
- Requirements affected: R08, R12, R24, R25
- Decisions affected: D22, D38, D49, D50 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

[Fresh preprocessing](../preprocessed-units.md) establishes current expanded function inputs. The next step must demonstrate actual object reuse without promoting failed revisions, accepting corrupt artifacts or silently changing ordinary build/watch behavior. Reuse needs an explicit trust boundary beyond driver hashes.

## Proposal

Add a synchronous `UnitBuildSession` Python API, requiring the caller to assert a trusted stable toolchain for its lifetime. Fully check/preprocess every source snapshot. Key each function/entry object by exact expanded C, unit ID and current compiler/language/profile/console/driver/environment/flag identities. Retain only the last successful build in private owned temporary storage. For eligible entries, read bounded regular files without following symlinks, verify their retained bytes and copy them into an isolated candidate; damaged entries compile again.

Compile changed units without LTO, link every current candidate, then verify all candidate objects, executable bounds and final compiler/driver identities. Promote the cache together after success. Invalid source or any preparation/compile/link/integrity/limit/drift failure removes only the candidate. Previous successful paths remain available through failure and expire after a later success or session close. Return current `talven.unit-build.v1` work/byte receipts; never execute the result or write a user-selected destination.

The exact flags, resource limits, timeout exclusions and path lifetime contract are in [the API documentation](../object-reuse.md). Ordinary build/dev remain unchanged. Do not accept external objects or receipts, add persistent shared storage, introduce dynamic dispatch or broaden borrow lifetimes.

Under the same stable-toolchain assumption, retain successful version/target probes only while driver path/bytes, effective environment and actual working directory match. Still preprocess every current valid snapshot and recheck final identities. Capture one working directory/environment for all commands, and include directory identity in object keys. Failed builds retain prior probes, with `driver_probe_reused` reported as work metadata outside configuration keys. Standalone preparation still probes freshly on every call.

## Trust and publication

Caller acknowledgement of a stable trusted toolchain covers backend tools/libraries/configuration and linker inputs not fully identified by the driver receipt. It is a stated experimental assumption, not independently enforced security. A new session is necessary after changing those dependencies. Hashes identify bytes without authenticating tools or proving task correctness. Private owned files assume trusted single-caller access; this is not a hostile cross-process cache protocol.

Publication here means promoting the session's candidate/cache, not starting an application or publishing a filesystem revision. A future watcher must preserve existing source observation, cancellation, process-group cleanup and last-moment freshness checks. Source snapshots are fully checked before reuse; a previously successful object does not substitute for current language analysis or dependency evidence.

## Alternatives and costs

A C-text-only cache misses header/configuration changes. A shared on-disk cache adds integrity, races, eviction and trust before session behavior is verified. Replacing ordinary `dev` now risks blocking source observation during multi-process preparation/compilation. Begin with a synchronous private API. Every revision still parses/checks/preprocesses/links; copying and hashing can dominate small builds. Separate compiler processes and expanded headers can make cold and changed builds slower. No improvement is assumed.

## Evaluation

Check body/comment reuse and broad contract/environment invalidation. Damage retained objects with missing bytes, corruption, symlinks and FIFOs. Reject invalid source before external execution, force compile/link failures, exceed artifact bounds, mutate objects after linking and force compiler identity drift. Require no partial cache promotion and successful repair using prior objects. Compare each current native output with an independent ordinary build, including exact static text, borrow ordering/stores and traps. Execute reused borrowing objects with ASan/UBSan at `-O0` and `-O2`. Run the full reference and documentation suites; Linux CI requires native evidence without skips.

## Open work

Measure representative full/reused builds with retained current inputs, configuration, ordering and independent correctness gates. Define asynchronous watcher cancellation/publication before integration. Complete toolchain dependency capture, finer global contracts, incremental parsing/native Rust reuse, shared cache/eviction, modules, state-preserving reload and design acceptance remain separate.
