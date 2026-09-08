# Offline compiler and tooling baseline

Status: implemented experiment, report `talven.tooling-baseline.v1`, workload suite `m1c-tooling-workloads-v1`. This measures the current Python/C11 bootstrap on fixed inputs. It does not choose a production compiler, compare languages, measure model effectiveness, or complete M1. See [Proposal 0009](proposals/0009-offline-tooling-baseline.md).

## Run and retain a baseline

Run from a trusted Git checkout with Python 3.11+ and a native C11 compiler supporting the existing CLI build flags. No provider, credentials, package installation, or network connection is used by the runner.

~~~sh
python3 scripts/measure-tooling.py --out build/tooling-baseline \
  --repetitions 5 --warmups 1 --cc cc
~~~

Use a fresh output directory each time. Optional `--expect-arch aarch64` or `--expect-arch x86_64` rejects an unexpected host before creating output. `--environment-note` records operator-supplied container image identity, filesystem placement, or other run conditions; it is not an automatically verified hardware fact. `--timeout` defaults to 60 seconds per subprocess, with a maximum of 300. The existing Talven build command also retains its own 30-second C compilation timeout. Repetitions accept 1–100 and warmups 0–10.

The command exits zero only after the entire suite passes. Output creation never overwrites an existing run. Once created, `report.json` starts with `complete:false`, `passed:false`, and `summary:null`. Expected failures retain commands and partial outputs, keep these fields, and exit one. An interruption also retains the most recently saved report; a hard termination may leave the last command pending. No partial suite gets a timing summary. Failed correctness checks are failures, never skipped or fast samples.

## Workloads and acceptance

Inputs and independent native checks live in [tooling_workloads.py](../experiments/tooling_workloads.py). Existing compiler tests and evaluation acceptance rules are unchanged.

| Workload | Source | Independent native acceptance |
| --- | --- | --- |
| `vectors` | Exact existing vector example | Four full-i32 dot products including negative, zero, and large values |
| `borrowing` | Exact existing borrowing example | Five starting values; shared read preserves the owner, add/step_twice return and mutate correctly |
| `chain-32` | Deterministically generated 32 helpers plus main | Last helper returns input + 32 for three inputs |
| `chain-128` | Deterministically generated 128 helpers plus main | Last helper returns input + 128 for three inputs |

All native oracles also require Talven main to return zero. Oracles are separate C translation units with full integer comparisons, compiled with `-fno-lto`. Only the subject compilation renames the hosted C main to let the oracle supply its own entry point. The prototype `tv_f_*` names are test internals, not a public foreign ABI.

Each workload receives a separate candidate that adds `baseline_added() -> i32`, returning zero. Edit validation must report exactly that addition, retain the expected source/compiler identities, and report no other contract/call changes. These are valid-base declaration additions; invalid repairs, diagnostic performance, and multi-file changes are outside this first suite.

## Measured operations

| Operation | Boundary | Output checks |
| --- | --- | --- |
| `check` | Full `talven check --json` process | Successful diagnostic envelope |
| `format` | Full `talven fmt` process, stdout mode | Exact canonical source bytes |
| `context` | Full `talven context --symbol main --include-body --max-bytes 16384` process | Context v2, selected main, source/compiler identities |
| `snapshot` | Full `talven edit snapshot` process, no source body | Successful snapshot and exact identities |
| `validate` | Full `talven edit validate` process with pinned identities and candidate | Successful preview and exactly one added helper |
| `emit-c` | Full `talven emit-c` process, stdout mode | Identical to preflight C accepted by the native oracle |
| `c-build` | Direct C compile/link of saved generated C | New executable exists and executes with exit zero |
| `build` | Full `talven build` process, including C compile/link | New executable exists and executes with exit zero |

Before sampling, the runner obtains one checked reference for each of the first six outputs, then compiles/runs the independent native oracle. Every repeated text/JSON/C output must exactly match its reference. Every warmup and measured executable runs outside its build timing. This tests finite workload behavior; it does not prove arbitrary program equivalence. The measured full build is checked by its executable main, while the independent oracle checks the separately emitted reference C.

The measured C flags are `-std=c11 -O2 -Wall -Wextra -pedantic-errors`, matching the current CLI. There is no optimization-level comparison or whole-program native throughput measurement.

## Timing and size interpretation

Timing uses `perf_counter_ns` around process launch and output collection. It includes child startup, imports, work, and stdout/stderr transport. It excludes receipt persistence, output validation, artifact hashing, native acceptance, and execution of built programs. Nanoseconds are storage units; they are not a precision claim. The clock's reported resolution and implementation are recorded.

Order is fixed and sequential: workload, phase (warmup then measured), repetition, operation. The default retains one warmup and five measured invocations per operation. Preflight and verification commands are separately tagged. Summaries contain only measured, verified samples: count, minimum, median, maximum, and per-sample byte sizes. Raw warmup and measured durations remain available. No outliers are removed, timing threshold gates imposed, confidence intervals inferred, or small-sample tail latency claimed.

Each invocation starts a fresh process. `LC_ALL=C`, `PYTHONHASHSEED=0`, and `PYTHONDONTWRITEBYTECODE=1` are set; Talven commands also use Python `-B`. Existing bytecode and OS caches remain uncontrolled. Preflight has already touched the sources before warmups. This is not a cold-cache benchmark or in-process frontend microbenchmark. Scheduling, background load, filesystem placement, thermal state, virtualization, and C toolchain defaults can affect results. Record the conditions and compare repeated runs before drawing conclusions.

The direct C build and complete Talven build are distinct observations. Subtracting their medians does not isolate Python or frontend overhead. Context selects one function and direct dependencies; its byte count is not whole-program context size. Source/output counts are exact bytes, not tokenizer counts. Executable size is its on-disk file length, including hosted toolchain/startup defaults; it is not RAM, stack use, deployed dependency size, or a freestanding measurement.

## Evidence and trust

The output directory retains:

- `report.json`: raw command timings/status, checks, summaries, exact argv/order/settings, host OS/architecture/CPU model when available, Python and C executable identities, C target/version, source/compiler identities, timestamps, and Git revision/dirty state.
- `inputs/`: the benchmark's executing sources, all compiler modules, and both original example sources with byte lengths and SHA-256 hashes.
- `workloads/`: source/candidate/oracle files, generated C, independent checker, and every warmup/measured executable, with report hashes for measured artifacts.
- `commands/`: every command's exact stdout/stderr bytes, with hashes and lengths in the report.

Inputs and compiler/tool identities are checked for observed changes before a successful report. Hashes identify bytes; they do not authenticate archives or guarantee an atomic filesystem snapshot. The checkout, Python runtime, C toolchain, and host remain trusted. Standard libraries, system headers, linked libraries, inherited environment beyond the explicit overrides, and compiler subtools are not bundled or fully pinned. Bytecode/cache contents are not archived. Restore those environmental inputs separately for comparable repeats; artifact preservation does not promise bit-identical timing or binaries. The runner has subprocess timeouts but no hostile-process sandbox or comprehensive memory/disk quotas.

CI runs a short three-repetition baseline on its declared Linux jobs and retains the complete directory as a downloadable artifact. Downloaded executable files may need their execute permission restored; [GitHub's artifact action documents permission loss](https://github.com/actions/upload-artifact#permission-loss). CI is correctness/archiving evidence under shared runner conditions, not a controlled machine comparison.

Model usage, tokenizer identity, dollar cost, memory/allocations, LSP latency, native throughput, and cold-cache performance remain explicitly unmeasured. No time-to-dollar conversion or token/cost advantage is reported. Use the separate [agent harness](../experiments/README.md) for controlled model tasks and the [freestanding probe](freestanding.md) for its narrower deployment measurements.
