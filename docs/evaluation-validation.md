# Evaluation harness validation

Measured on 8 September 2026. This record concerns harness correctness, not live agent effectiveness. No paid model calls were made, and no comparative model tokens, dollar costs, or savings were measured.

## Linux ARM64 execution

The full unchanged compiler suite and new harness tests ran in a Linux ARM64 container on an ARM64 Docker host:

| Input or check | Observed result |
| --- | --- |
| Container image | `python:3.11-bookworm`, image index digest `sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca` |
| Actual platform | Linux, `aarch64` |
| Python | 3.11.16 |
| C compiler | Debian GCC 12.2.0-14+deb12u1; target `aarch64-linux-gnu` |
| Talven compiler hash | `e5c4c8973de267594e32d403a646c0c783178c6dfaf32af64f25b0551728bb69` |
| Full unittest discovery | **119 tests passed, zero skips** |
| Borrowing sanitizer script | **6 ASan/UBSan executions passed**, at `-O0` and `-O2` |
| Native CLI examples | Both vectors and borrowing built and exited zero |
| Existing `.tal` formatting checks | All seven example/fixture files passed |

The original 80 compiler tests and compiler sources were preserved. The additional 39 tests cover accounting, adapter protocol/process handling, the run/report/reverification CLI, and independent task acceptance. Negative cases include hardcoded or bypassed results, ineffective main checks, path-scope violations, timeouts, cancellation, malformed/overflowing metrics, changed artifacts, and an archive attempting to select a compiler executable.

## Offline end-to-end run

The [scripted adapter](../tests/fixtures/eval_adapter.py) exercised the [documented workflow](../experiments/README.md) in that Linux container. All four tasks ran independently under both source-only and compiler-context conditions:

| Observation | Actual fixture result |
| --- | --- |
| Trials | 8 |
| Accepted final candidates | 8 |
| Adapter attempts | 16 |
| Repair attempts | 8 |
| Fresh independent reverification | All 8 final candidates passed |
| Model input/output/cache tokens | Unmeasured (`null`) |
| Model/tool/verification/total dollar cost | Unmeasured (`null`) |

Each fixture deliberately submitted an unsuccessful initial candidate followed by a hand-written solution. These numbers establish runner behavior only; they are not evidence that a model completes the tasks or benefits from compiler context. The local artifacts recorded the starting Git revision with a dirty working tree and archived exact harness/source inputs; CI repeats the workflow from its checkout.

## Other checks and limits

All **39 harness tests passed** on macOS ARM64 using Python 3.14.4 and Apple Clang 21.0.0. The untouched full macOS baseline had 28 failures/subtest failures across 80 tests: strict unused-function warnings in generated C and a platform-specific `nm` symbol expectation. This change does not relabel that baseline as a successful macOS compiler conformance run.

The documentation link/diagram check is required before the PR. Native Linux x86-64 and ARM64 CI also run the harness fixture and reverification alongside the existing conformance/sanitizer checks. A configured job is not execution evidence; inspect actual PR checks before making additional target claims.

Acceptance tests are finite and public. The runner limits source edits; a trusted adapter and externally protected execution environment remain required. Live provider integrations, borrowing-specific model tasks, and cross-language comparisons remain unmeasured follow-up work.
