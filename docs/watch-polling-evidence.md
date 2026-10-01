# Paired watcher polling experiments

Status: two retained local candidates, both rejected as ordinary default polling changes. A separate timeout-sensitive completion safeguard fixes a correctness edge case without adopting either default candidate. These receipts do not establish a general speedup or explain the entire cause of observed regressions.

## Recorded protocol

Use the [actual watcher runner](native-watch-baseline.md) from source base `e89a981`. Each experiment runs three before/after pairs in AB, BA, AB order, one repetition and no warmups per condition. Every condition executes all four workload families, both full/native modes and six revisions. Each experiment retains 288 verified samples, six reports and 48 cleaned session streams; native task results, current diagnostics, source/C/oracle identities and compiled/reused/probe decisions matched across each pair. This is not a pool with the [first watcher run](native-watch-evidence.md).

Apple M4, macOS ARM64/Darwin 27, CPython 3.14.7, Apple Clang 21.0.0, target `arm64-apple-darwin27.0.0`; fixed selected executable identities, environment hash, C flags and 50/100-ms polling/debounce matched within each pair. Parent receipt reading sleeps 1 ms; native task/exit verification follows terminal timing. OS caches, CPU scheduling and ordinary background activity remain uncontrolled. No competing agent tests/builds ran during either timing experiment.

The measured compiler/runner input set differs only in `talven/dev.py`; exact before/after module snapshots, archived input hashes, orchestration/curation scripts, all raw samples and normalized session events are retained. Before uses an archived code root and after uses the current root on the same filesystem. Watcher C-driver working directories follow those roots; their directory identities differ. This is not a perfectly isolated same-directory experiment. Preserve source/tool/working-directory distinctions and the unchanged native mode as a control; do not interpret every difference as caused by polling.

## Candidate 1: Shorten all active full-build ticks

Cap pending ordinary builds to 5 ms, matching native pipelines, while continuing source reads on every loop tick. This changes source-read frequency as well as compiler-completion polling. Compiler source hashes: before `50b684636b0dc2397fe47d06f4146c632877e67236e606467df1d32d026321a0`; candidate `7a58eb62c28513466fa2d4b74fd2d1fb6cd65a40f8e388d6e913e3b9af7a5dda`. UTC 2026-10-01 16:44:57–16:50:02, 2 October locally.

[Retained candidate receipt](../experiments/results/watch-poll-rejected-macos-arm64-20261002.json), SHA-256 `f2479d760fd3d4d458745f7be266f77f4ade549584144d07b9d48b79eb3d21d0`. Selected ordinary-full parent-to-started durations, milliseconds; each cell lists pairs 1/2/3 rather than pooled medians:

| Workload/revision | Before | Candidate |
| --- | --- | --- |
| stores-128 trivia | 557.750 / 506.608 / 427.893 | 932.796 / 579.284 / 562.129 |
| stores-128 body | 481.860 / 485.731 / 481.205 | 810.873 / 504.772 / 489.965 |
| stores-128 contract | 484.590 / 538.516 / 480.181 | 722.910 / 752.690 / 560.205 |
| borrowing body | 350.892 / 332.611 / 269.614 | 234.081 / 243.213 / 252.752 |

Several small-workload edits improved, but store trivia/body/contract were slower in all three pairs. The unchanged native mode also varied, including lower store-body durations in all three after conditions. Reject the default change. Increased source reads are additional work, but these data do not prove they caused the entire regression; investigate a completion-only schedule separately.

## Candidate 2: Separate completion ticks from periodic source reads

Keep full compiler polling at 5 ms while ordinary periodic source reads retain the configured interval. Native pipelines retain their prior behavior; explicit source freshness checks around publication remain. Compiler source hashes: same before hash; candidate `cca35433da6a70fd2075842deabdea79a2b83a107cff3bbb200a0ce49807c878`. UTC 2026-10-01 16:59:34–17:04:11, 2 October locally.

[Retained candidate receipt](../experiments/results/completion-poll-rejected-macos-arm64-20261002.json), SHA-256 `5a3aa50c12e645bbe37614596161439ce52cbb34f2761476c37063380e705af4`. Selected ordinary-full parent-to-started durations, milliseconds:

| Workload/revision | Before | Candidate |
| --- | --- | --- |
| chain-32 body | 326.194 / 276.780 / 306.128 | 271.081 / 269.185 / 305.944 |
| chain-128 body | 284.897 / 332.383 / 280.231 | 300.209 / 322.339 / 437.756 |
| stores-128 body | 454.912 / 424.195 / 471.209 | 497.157 / 461.486 / 523.570 |
| stores-128 repair | 460.098 / 429.559 / 420.973 | 548.776 / 484.603 / 539.900 |
| borrowing body | 280.167 / 283.134 / 278.089 | 229.143 / 233.368 / 229.895 |

Results remain mixed; store body/repair were slower in every pair. Unchanged native store-body and chain-128 body controls were also slower in every after condition, while native borrowing controls improved. Ambient/root differences therefore remain material, and neither a universal latency reduction nor CPU saving follows. Reject this candidate as the ordinary default too. No memory, energy, long-running shutdown/readiness or agent-cost benefit was measured.

## Retained correctness safeguard

The experiments exposed a separate edge case: with source polling longer than a short build timeout, the ordinary watcher can sleep past that timeout even when its compiler finishes promptly. For example, a one-second source interval and half-second build budget previously rejected a quick successful compiler before noticing its exit.

Keep ordinary default polling. Only when the configured source interval is at least half the build timeout, poll pending full compiler completion with at-most-5-ms sleeps and retain configured periodic source observation. Explicit freshness checks before/after old-program shutdown remain. Native pipelines keep their existing cadence. Idle polling/debounce do not change. A new test-only compiler/program double verifies prompt completion succeeds with the one-second/half-second settings; it establishes watcher timeout behavior, not C compiler performance or new language APIs.

The safeguard is not either retained candidate's source snapshot and has no comparative timing claim. Timeout checking occurs when control returns; synchronous frontend/file/process work and scheduling can still delay it, and no exact deadline guarantee is established. Keep performance default changes dependent on representative task and resource evidence rather than timer granularity alone.
