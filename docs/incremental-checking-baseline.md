# Persistent function-checking baseline

Status: implemented offline measurement experiment, report `talven.incremental-comparison.v1`. It compares the shared full reference frontend with the opt-in persistent checker from [Proposal 0016](proposals/0016-persistent-function-checking.md). It measures in-process analysis over fixed edits; it does not measure native Rust reuse, C build speed, save-to-running latency or model effectiveness. See [actual local observations](incremental-checking-evidence.md).

## Run and retain

~~~sh
LC_ALL=C PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 python3 scripts/measure-incremental.py \
  --out build/incremental-comparison --repetitions 5 --warmups 1 \
  --environment-note 'Describe host, load and filesystem here'
~~~

Use a new output directory. Python 3.11+, Git and a trusted C11 `cc` are required. `--expect-arch aarch64` or `x86_64` verifies the actual host architecture. The ordinary C compiler option names one executable; no shell command is interpreted. Repetitions, warmups and native verification timeout use the same bounded limits as the [offline tooling baseline](tooling-baseline.md).

Reports retain exact compiler and measurement sources, every edited source, raw per-revision timings and reuse lists, diagnostic failures, generated C, independent acceptance drivers and command output. Provenance includes compiler identity/profile, Python version/executable, CPU/OS, Git revision and status, C version/target/executable, flags, timing clock, relevant environment values and garbage collector settings. Inputs and executable identities are checked again before a successful summary. Hashes identify the retained bytes, without authenticating them.

## Workloads and acceptance

| Workload | Revisions and independent native acceptance |
| --- | --- |
| `chain-32`, `chain-128` | 32/128 helpers plus main; initial source, a leading Unicode comment, a helper body edit with main updated, a parameter-name contract change, an invalid return, then repair. Three positive/negative/large full-i32 helper results plus main exit zero |
| `stores-128` | 128 helpers, each with 12 scalar stores; the same edit sequence and independent chain checks. Source/tree limits remain enforced |
| `borrowing` | Read/write helpers and main; comment, mutation body edit, added boolean field, invalid shared-to-exclusive argument, then repair. Reads preserve owners, writes return and store current values, the added field remains intact, and main exits zero |

For every revision, preflight obtains the current full analysis and expected first diagnostic, C and deterministic context. Every valid preflight compiles with `-std=c11 -O2 -Wall -Wextra -pedantic-errors -fno-lto`; a separate C driver tests full-i32 results and mutation rather than relying on truncated process exit values. Expected invalid revisions must produce `E0201`.

Measured full and persistent results must match the entire current analysis, reference positions/descriptions, diagnostic, context and byte-identical accepted C. A missing successful analysis or changed output fails the report. Warmups and verification are excluded from summaries. Missing or unverified measured samples prevent a successful summary; failures retain partial receipts and `passed: false`.

## Timing boundary and interpretation

Both conditions run in the same Python process. A repetition constructs a fresh persistent session and replays the complete sequence. Each revision alternates condition order across repetitions. The initial incremental sample includes session construction and compiler hashing. Later incremental samples include identity checks, full parsing and declaration validation, cache matching, current reference reconstruction and misses. Full samples include ordinary `analyze`. Source reads, report writes, equality/context/C verification, C compilation and execution occur outside timed analysis.

The report records minima, medians, maxima and raw timings separately for every workload, revision and mode, including expected errors. Garbage collection stays at the invoking process's settings. Cache hits can coexist with slower checking when parsing or reuse bookkeeping dominates. Initial cache creation is additional work. Do not infer a universal speedup, proportionality to hit count, native compiler performance or end-to-end development latency from these samples.

Memory/RSS, cold filesystem caches, process startup, incremental parsing, incremental C builds, linking/restart and provider token/dollar cost remain unmeasured. These workloads establish a reproducible narrow comparison, without completing R24/R25 or selecting a production frontend/backend.

## Continuous verification

`tests/test_incremental_measurement.py` validates edit validity, dependency invalidation and repair reuse, rejects partial/unverified summaries, and checks that missing analysis cannot become a successful report. Compiler CI runs the measurement on its declared Linux hosts and retains the complete directories as artifacts. Local observations belong in a separate evidence record with their full provenance and limitations.

The explicit [current call type contract option](call-type-contracts.md) allows parameter-name changes to preserve caller checks while rebuilding displayed signatures from current declarations. Default signature identities remain unchanged; full current parsing and native rebuilding still apply.

[Three paired local comparisons](call-contracts-evidence.md) retain current native-accepted workloads, exact complete analysis/context/C and 2,016 samples including warmups. Recheck counts improve for parameter renames; timings remain mixed and defaults remain unchanged.
