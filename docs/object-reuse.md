# Private native object reuse

Status: synchronous reference API experiment under [Proposal 0022](proposals/0022-private-object-reuse.md), build profile `hosted-object-reuse-v1`. It uses [fresh prepared units](preprocessed-units.md), compiles eligible changed functions separately, and always links a current candidate. Ordinary CLI build/dev behavior is unchanged. There is no disk cache shared across sessions, watcher integration or hot reload.

~~~python
from pathlib import Path
from talven.unit_build import UnitBuildSession

with UnitBuildSession(stable_toolchain=True, console=True) as session:
    source = Path("examples/hello.tal").read_text(encoding="utf-8")
    first = session.build(source)
    second = session.build(source + "\n// current revision\n")
    print(second.receipt["compiled"], second.receipt["reused"])
    # second.executable is a session-owned candidate; build never runs it.
~~~

`stable_toolchain=True` explicitly asserts a trusted toolchain whose backend binaries, libraries, configuration, linker inputs and ABI behavior stay stable during the session. Driver hashes/version/target and expanded inputs do not establish that condition themselves. Use a new session after changing those dependencies. This is an experimental caller obligation, not independent enforcement, authentication or a sandbox. The API is synchronous and intended for one caller, not concurrent builds.

Each build fully analyzes current source and runs one fresh preprocessing pass. The source hash alone is not a reuse key: the key includes exact frozen unit hash and ID, compiler checkout, language/build profiles, console selection, resolved driver path, driver executable hash/version/target, effective-environment hash and compile flags. The ordinary source hash can change while identical prepared objects remain eligible. Global signatures/layouts/order repeat in all units and conservatively invalidate them. Environment or driver identity changes force rebuilding. No external receipt or supplied object is accepted as a cache seed.

Objects compile from frozen stdin with `-std=c11 -O2 -Wall -Wextra -pedantic-errors -Werror -fno-lto -x cpp-output -c`. Link every candidate with the same effective environment, trusted driver and compatible flags. No program executes. Separate objects have different optimization opportunities from a whole-program build; runtime performance and binary-size equality are not established.

Only the last successful build is retained in a private temporary directory. For an eligible object, read a bounded regular file without following symlinks, compare its retained SHA-256, and copy those verified bytes into a new candidate. Missing, nonregular, symlinked, empty, oversized or corrupt objects are misses and compile again. After linking, check every candidate object's bytes, the program bounds and driver/compiler-checkout identities. Promote the entire cache together only after success. An invalid revision, compile/link failure, timeout, overflow, object mutation or identity drift discards the candidate and preserves the previous successful build. Compiler-checkout drift gives `E0501` requiring session restart.

The returned `UnitBuild` contains a session-owned executable path and a `talven.unit-build.v1` receipt with current source/compiler/language/console and driver/configuration identities, fixed flags, compiled/reused IDs, each exact frozen C hash/key/object hash, total object bytes, executable hash and raw preprocessing hash. These are byte and work receipts, not task correctness, application readiness or authenticated acceptance. Mutating the returned receipt does not seed or update the internal cache.

An earlier successful executable path expires when a later build succeeds; failures keep it valid. All paths expire on `close()` or context-manager exit. There is no copying to a user-selected destination, running-program lifecycle, live source observation, revision supersession check or atomic filesystem publication. An eventual watcher must separately handle cancellation and source freshness before starting a candidate. Caller-selected source strings identify snapshots, not a continuing filesystem revision.

Bounds inherit preparation/source limits and permit at most 256 functions plus entry, 16 MiB per object/program and 64 MiB total objects per successful/candidate generation. At most one successful and one candidate generation coexist. Artifact bounds are checked after tools return; they are not hard tool disk/memory quotas. The aggregate timeout (0.01–60 seconds, default 30) covers preparation/build elapsed time when control returns, limits each subprocess using its remaining budget, and cannot interrupt synchronous frontend/hash/file work. Compiler stdout/stderr are each bounded to 64 KiB per command; process groups use the established cleanup. Owned directories are removed after failure, replacement or close; host failure or uncatchable termination can leave temporary files.

Ten focused tests verify changed-body reuse, current comment revisions, conservative global/environment invalidation, corruption recovery, invalid-edit repair, compile/link/artifact failure retention, post-link object mutation and compiler drift. Native outputs agree with independently fresh ordinary builds for exact static UTF-8/NUL text, borrowing/stores and checked traps. All three borrowing fixtures execute with genuinely reused objects under ASan/UBSan at both `-O0` and `-O2` in test-only flag variants. Local macOS checks do not expand the declared Linux target profiles. No consistent build/rebuild improvement, memory reduction or agent benefit has been measured; comparison measurements and development integration remain open.
