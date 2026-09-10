# Development watch and restart

Status: experimental single-file development command. It uses the existing Python frontend and C11 backend for **full builds**. Incremental compilation, persistent compiler caches, UI/browser refresh, and state-preserving hot reload remain unimplemented. See [the staged design](proposals/0010-fast-compiler-and-development-reload.md) and [this increment's proposal](proposals/0012-development-watch-and-restart.md).

## Try it

From the repository root with Python 3.11+ and a trusted C11 compiler:

~~~sh
python3 -m talven dev examples/hello.tal --console
~~~

The command prints the greeting, continues watching after the program exits, and rebuilds/reruns it when the source bytes change. Edit the greeting and save. A syntax/type/borrow error is reported; correcting the file triggers another build. Ctrl-C shuts down the session and its current compiler/program groups. `--console` retains the [explicit POSIX output contract](text-console.md).

The initial target evidence is Linux ARM64 and x86-64 through native CI. The implementation requires POSIX process groups and rejects other operating systems. A passing local test on another POSIX host does not establish a full platform support profile.

## Session contract

- Watch one file path; imports and directory/workspace watching are not implemented. Poll exact bytes, including comments and whitespace, every 50 ms by default. Changes entirely between observations may be missed. Metadata-only saves of identical bytes do not rebuild.
- Assign increasing session-local revisions to changed observations, including missing/unreadable, oversized, or nonregular source states. Read at most the existing 256 KiB source limit plus one byte. A valid-sized read receives the SHA-256 of its exact bytes, even if UTF-8 or language validation later fails. Unreadable/oversized/nonregular observations have a null hash; different inaccessible contents cannot be distinguished.
- Wait for 100 ms of unchanged observations before attempting a revision. This coalesces observed save bursts; it cannot identify every editor's save transaction. Source is never modified. Atomic file replacement and recovery after deletion are supported by reopening the selected path.
- Analyze the snapshot through the shared frontend and emit C with the ordinary backend. Build an isolated temporary candidate using the same `-std=c11 -O2 -Wall -Wextra -pedantic-errors` flags as `build`. At most one compiler and one previously started program are active. This adds orchestration, not a new language profile or alternate safety mode.
- Observe source while the C compiler runs. Cancel a build when superseded. Check freshness again after compilation and after stopping the old program. A stale candidate is discarded. The final read and process launch are not an atomic filesystem transaction: a concurrent later write is discovered on a subsequent observation. Frontend analysis and process shutdown are synchronous, so those operations can delay observations.
- Keep a live old program during parsing or native build failure. After a successful fresh candidate, stop/reap the old direct child before launching the replacement. Program state is lost and initialization runs again. If launch fails after shutdown, report failure; there is no rollback guarantee. If the replacement exits or crashes, report its return code and continue watching without an automatic retry loop.
- Compiler and program processes get separate POSIX sessions/process groups. Send TERM, wait up to one second for the direct child, then send KILL to its group and reap the direct child. Group signaling also happens when a leader exits naturally, to clean up remaining members. Descendants do not receive an independent grace period after their leader exits. A program's normal stdout/stderr are inherited, its stdin is closed, and its working directory/environment are the invoking session's. Interactive input and readiness checks are outside this increment.
- Build timeout defaults to 30 seconds, measured from the start of frontend checking and checked when the event loop regains control. It is not an interruptible frontend CPU quota or hard real-time deadline. Capture at most 64 KiB of combined C-compiler stdout/stderr; exceeding it rejects the build. Program output is not captured or bounded by the watcher.
- Ctrl-C exits the watcher with status 130; SIGTERM exits with 143 after cleanup. Build and program failures keep the watcher alive; setup/I/O failures exit with status 1. Killing the watcher with an uncatchable signal, host failure, processes escaping their groups, and arbitrary foreign resources are outside this cleanup contract. Trusted compilation/execution has the user's filesystem/network permissions; process groups are resource hygiene, not a sandbox.

The flags `--poll-interval`, `--debounce`, `--build-timeout`, and `--stop-timeout` accept seconds from 0.01 through 60, inclusive. Nonfinite values are rejected. `--cc` accepts one trusted executable path, including spaces; it is never interpreted as a shell command. Changing the compiler, toolchain, environment, or command options requires restarting the development session. A session does not pin or authenticate an external compiler binary.

## Agent receipts

Create a separate JSON Lines file to retain actual session observations:

~~~sh
mkdir -p build
python3 -m talven dev examples/hello.tal --console --events build/hello-dev.jsonl
~~~

The receipt path must be new, have an existing parent, and differ from the watched source. Exclusive creation refuses to overwrite any existing file. A later session needs a fresh receipt path. Human session messages go to stderr; program stdout/stderr remain ordinary program streams, so consuming receipts from the separate file avoids confusing program text with compiler facts. Receipts grow with session activity; rotation is not implemented.

Every record has `schema: talven.dev.v1`, `event`, `revision`, and `source_hash`. Revisions are local to one receipt file; an A→B→A source sequence gets three revisions even if the first and third hashes match. There is no stable ABI or authenticated receipt claim.

| Event | Meaning and additional fields |
| --- | --- |
| `session_started` | Revision 0, null source hash; source path, compiler hash, selected `cc`, full build mode, and configured timing limits |
| `observed` | New source state; not a claim of valid syntax or successful build |
| `building` | C compiler process created; revision/hash, compiler PID and `build_mode: full` |
| `superseded` | Candidate discarded because a newer observation or cancellation prevented publication |
| `rejected` | Frontend, input, build, or launch failure; structured `diagnostic` with the same codes/ranges as CLI analysis where applicable |
| `started` | Native process created; PID and full build mode. Does not establish application readiness or task correctness |
| `exited` | Program exited naturally; `returncode` follows Python's POSIX convention (negative means a signal) |
| `stopped` | Program cleaned up for replacement or session shutdown; reason and return code |
| `session_stopped` | Session cleanup completed; received signal, or 0 for an I/O failure cleanup path |

Candidate/program events include `observed_to_event_seconds`, computed from a monotonic clock since that revision was observed. This includes debounce and completed synchronous work. It excludes unknown time between an editor save and observation and is **not save-to-readiness latency**. An observed revision coalesced before any attempt has only an `observed` record. A build cancelled during session shutdown need not receive a terminal candidate event. Use `started`, `stopped`, and `exited` to track the active process separately from the newest observed/rejected revision.

This increment makes no comparative throughput, memory, cache-reuse, token-saving, or latency claim. Representative performance evaluation must retain inputs/edits, environment, compiler/toolchain versions and flags, repetition order, failed attempts, and correctness criteria. The [existing offline baseline](tooling-baseline.md) measures different, standalone command boundaries.

## Verification

`tests/test_dev.py` runs actual native greetings and repairs, unchanged-timestamp edits, missing/invalid/nonregular source recovery, save coalescing, stale candidate cancellation, build timeout/output limits, source/receipt protection, and process exit reporting. Explicit test-only compiler/process doubles exercise delayed builds, failed native compilation, TERM-resistant shutdown, edits during shutdown, and failed startup. Those doubles do not establish native Talven APIs for sleeping, signals, or long-running services.

Run `python3 -m unittest discover -s tests -v` for the full suite. CI requires successful runs without skips on its declared Linux hosts; [compiler checks](../.github/workflows/compiler-check.yml) also run borrowing sanitizers, native examples, independent offline agent acceptance, freestanding execution, and the existing tooling baseline. Live provider calls remain outside this increment.

On 11 September 2026, the full suite passed **246 tests with no skips** in a local Linux aarch64 Docker environment (`python:3.11-bookworm`, Python 3.11.16, Debian GCC 12.2.0-14+deb12u1, target `aarch64-linux-gnu`). This includes 14 development-session tests. The separate borrowing check passed six ASan/UBSan executions at `-O0` and `-O2`. The compiler hash for that run was `791c630edb1d6d93e41a53d7ace71ffe903a57d6cc2ce962a59f7a33a4d0a515`. These are correctness results, not representative latency measurements or a new target-support promise. Earlier failing test runs exposed fixture assumptions about non-atomic saves and competing timeout/output-limit budgets; those fixtures were corrected before the successful full run.
