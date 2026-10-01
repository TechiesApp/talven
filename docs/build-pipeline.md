# Pollable private object builds

Status: implemented reference API experiment under [Proposal 0024](proposals/0024-pollable-object-builds.md). `UnitBuildSession.start_build(source)` provides a pollable driver for the same [private object build](object-reuse.md) that `build(source)` drives synchronously. Default CLI build/dev remain unchanged; the separate [opt-in watcher mode](native-watch.md) handles source freshness and application publication.

~~~python
import time
from talven.unit_build import UnitBuildSession

source = "fn main() -> i32 { return 0; }"
with UnitBuildSession(stable_toolchain=True) as session:
    with session.start_build(source) as pipeline:
        while not pipeline.poll():
            # A watcher can observe source here and close superseded work.
            time.sleep(0.001)
        result = pipeline.result
        print(result.receipt["compiled"], result.receipt["reused"])
        # The API builds a session-owned candidate; it does not run it.
~~~

Starting a pipeline synchronously checks current source, hashes/selects trusted compiler inputs and advances to its first compiler request. Invalid source or pinned compiler drift rejects before process creation. A request contains immutable command/input/environment snapshots, a captured directory, phase and remaining command budget. Its deadline starts when the request is created: delaying consumption cannot grant a fresh timeout at launch. Known phases are `prepare`, `compile` and `link`.

`poll()` performs a non-waiting command step and returns `False` while pending or `True` after the entire successful build. `result` then contains the ordinary `UnitBuild`; `pid`/`stage` identify the currently owned compiler command or are null after completion/close. A successful pipeline can report completion again. A cancelled/failed closed pipeline cannot be polled. Only one build may be active per session; close/cancel that pipeline before closing the session or beginning another build.

The blocking and polling drivers consume one shared generator of compiler requests. Preparation, exact unit keys, copied/recompiled objects, fresh linking, final identity/integrity checks and successful cache/probe promotion are therefore common code. Existing command output, artifact and aggregate build bounds apply. Polling gives control back while compiler commands run; frontend work, hashing, splitting, file copying/validation, process creation and cleanup remain synchronous. It is not an interruptible frontend or hard real-time API.

Closing a pending pipeline stops its current owned [command group](compiler-commands.md), closes its continuation and unwinds candidate cleanup. Any command failure or polling interruption does the same. A partial candidate never promotes object/probe state; previous successful paths remain usable and a repair can reuse their objects. Completion still means successful private native building, not current filesystem publication, task correctness or application readiness. A future watcher must reobserve source and obey its old-program shutdown/freshness rules before execution. If source becomes superseded just after successful native completion, the session can retain that successful native snapshot's cache; it must not be confused with the currently published program.

Seven focused tests verify native blocking/polling byte and work parity across cold/body/comment revisions, exact static text output, cancellation and command failure in all phases, successful-cache repair, invalid-source/compiler-drift rejection, immutable requests, queued deadline expiry, pipeline interruption and malformed continuation failure. TERM-resistant command doubles verify actual cleanup but do not add Talven signal/subprocess APIs. Existing shared-build tests exercise full i32 checks, borrowing/stores/traps and reused objects with ASan/UBSan. No watcher mode, state preservation or speed improvement is claimed here.
