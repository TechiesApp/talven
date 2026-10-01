# Experimental native object reuse in development

Status: implemented opt-in single-file watcher mode under [Proposal 0025](proposals/0025-native-object-watch.md). It combines the existing [watch/restart contract](development.md) with [pollable private object builds](build-pipeline.md). It is process restart, not state-preserving hot reload. Default `dev` and release `build` retain ordinary whole-program C compilation.

~~~sh
python3 -m talven dev examples/hello.tal --console \
  --incremental-build --stable-toolchain --events build/native-watch.jsonl
~~~

The event path must be new and have an existing parent. Both native-mode flags are required together. `--stable-toolchain` explicitly asserts the private API's trusted stable toolchain/backend/library/linker-input assumptions; hashes do not establish those conditions. Restart after changing untracked toolchain dependencies. This mode requires the declared GCC/Clang-compatible hosted C11/POSIX interface. It adds no freestanding, native Rust, package, GPU or new target profile.

Current source checks remain full. `--incremental-check` is a separate check-reuse/full-native-build experiment and cannot be combined with this mode. Every valid attempted snapshot is freshly parsed/type/borrow checked and preprocessed. Reuse eligibility depends on current expanded C plus compiler/configuration identities and verified last-successful object bytes. Default-profile signature/layout/order changes conservatively rebuild all units; body edits can leave unrelated units eligible. Successful driver probes can be reused under their separate identity checks. Linking stays fresh.

The watcher owns at most one build continuation. While compiler commands run, it continues source observation and cancels superseded work through owned process-group cleanup. Active native pipelines use an event-loop delay of at most 5 ms or the smaller configured poll interval; otherwise the configured polling interval applies. Read at most 64 KiB compiler output per command poll. Frontend work, hashing, splitting, copying and process creation/cleanup remain synchronous and can delay observations. There is no hard latency or CPU/memory quota.

Cancellation or command failure removes the unfinished candidate and retains last-successful objects/probes. A completely successful native snapshot can remain the private cache even if a later source observation supersedes it; cache promotion is distinct from application publication. Invalid source/builds keep a live old program running. A completed source-matched candidate receives a separate bounded regular-file byte check and verified deployment copy into the watcher's revision directory. That copy survives subsequent compiler-cache replacement. No user-selected executable or source path is overwritten.

Reobserve source after native completion, before replacement and after stopping the old program. Reject a stale/cancelled candidate at each boundary. Stop/reap the old program before starting the replacement; every new process starts fresh and initialization runs again. If a save arrives during shutdown, the superseded replacement never starts, and the watcher attempts the new revision. There is no old-program rollback guarantee after shutdown. The final source read and process launch remain separate operations; an immediately subsequent write is discovered later, as in ordinary watch mode. No readiness or atomic filesystem publication is established.

Build/source/preprocessing/object limits and the aggregate `--build-timeout` apply. Compiler command groups have a fixed 100 ms direct-child grace before group KILL/reaping; program shutdown uses `--stop-timeout`. The native timeout is enforced when command/build steps regain control and includes queued command delay, not an interruptible frontend deadline. Command stdout/stderr bounds, last-successful/candidate object limits and 16 MiB program bounds remain as documented by [the object API](object-reuse.md). Deployment copies add one current program and one potential replacement, each bounded to 16 MiB, outside compiler-cache storage. Owned compiler/program groups and temporary storage are cleaned on normal completion/cancellation/session shutdown within the stated process-group assumptions.

## Additional development receipts

The existing `talven.dev.v1` source-revision/hash events remain. Native session/build/start events have `build_mode: units` and `frontend_mode: full` at session start. `stable_toolchain_required` records the mode's obligation; `local_contracts` records the selected declaration mode.

| Event | Additional native-mode meaning |
| --- | --- |
| `building` | First compiler command created; current source revision/hash, phase (`prepare`) and PID |
| `compiler_step` | Next owned compiler command/phase/PID; JSON receipt only, no repetitive human log |
| `compiled` | Private native candidate completed; selected build profile, compiled/reused unit IDs, probe reuse, object byte total and executable hash; not current application publication or task correctness |
| `superseded` | Pending/candidate work discarded after a newer source observation or cancellation; no replacement start |
| `started` | Freshly gated replacement process created from its verified deployment copy; application readiness remains unknown |

Events retain actual observed-to-event monotonic elapsed time. That includes debounce, synchronous work, native commands and relevant shutdown, but excludes unknown save-to-observation time. The [actual watcher measurement runner](native-watch-baseline.md) separately records parent edit-to-receipt observations with native task acceptance. No comparative throughput, save-to-running improvement, memory reduction or agent benefit is inferred from the mode implementation alone. The earlier [whole/reused build](object-rebuild-evidence.md) and [driver-probe](driver-probe-evidence.md) measurements have different boundaries, source identities and polling; do not relabel them as watcher measurements. Those measurements and the separate [actual watcher observations](native-watch-evidence.md) show mixed costs and justify keeping this mode opt-in.

Eight focused tests exercise real native greeting/body/comment/contract/invalid/repair revisions, correct compiled/reused work, slow superseded preprocessing, failed-link retention, timeout/shutdown and required/mutually exclusive flags. Explicit compiler/program doubles separately verify live-old-program retention, deployment-file lifetime and source saves during shutdown. Those doubles do not establish Talven APIs for sleeping/signals/subprocesses or native semantic acceptance. Existing shared-frontend/build/borrow sanitizer tests remain required, and Linux CI requires native checks without skips.

The separate [local function contract profile](local-function-contracts.md) is selected explicitly with `--local-contracts`; existing default profiles retain their conservative global declarations.
