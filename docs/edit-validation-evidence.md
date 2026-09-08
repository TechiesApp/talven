# Edit preview validation evidence

Measured on 8 September 2026. This records offline checks of the [edit snapshot/preview interface](edit-validation.md). No live evaluation-provider request was made. Agent effectiveness, token consumption, dollar cost, preview latency and memory usage remain unmeasured.

## Linux ARM64 environment

The feature worktree was mounted read-only in a Linux ARM64 container, with its ignored build directory writable:

| Input or check | Observed value |
| --- | --- |
| Container | `python:3.11-bookworm`, image digest `sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca` |
| Actual host | Linux `aarch64`; container CPU model unavailable |
| Python | CPython 3.11.16 |
| C compiler | Debian GCC 12.2.0-14+deb12u1; target `aarch64-linux-gnu` |
| Talven compiler hash | `aea751513c037a6eba45ae74a0d050550773352e22ad573daa478ed4e09a916b` |
| Full unittest discovery | **195 passed, zero skips** |
| New preview tests | **19 portable tests** and **one independent native test** |
| Independent candidate executions | **Four expected outcomes**: correct repair exits zero, wrong repair exits one, each at `-O0` and `-O2` |
| Existing borrowing sanitizers | **Six ASan/UBSan executions passed**, across `-O0` and `-O2` |
| Existing freestanding probe | **18 executions passed**, with exact success/trap exits and dependency inspection |
| Native CLI examples | Vectors and borrowing both built and exited zero |
| Formatting | All **12** tracked Talven example/corpus/fixture files and the generated repair example passed |

The existing 175 tests, language frontend/backend, formatter, LSP, evaluation runner/corpora and freestanding probe remain unchanged. New tooling changes the compiler module inventory and therefore its aggregate hash; no prior context/archive identity was reused or relaxed.

The local run archives identify revision `b583350eeb9d68e4f68d68916c5646fb11b9bf68` with a dirty working tree and retain pinned source/compiler/harness inputs, exact commands and receipts. These are development verification artifacts, not a clean-release benchmark. Native and evaluation scripts record their actual compiler/host settings separately.

## Preview behavior and independent acceptance

Portable tests exercised invalid-source snapshots, exact CRLF/UTF-8 hashes, explicit source inclusion, repeatable encoding, revision guards, frontend diagnostics, invalid-base repair, declaration and direct-call comparisons, input/output limits, same-file no-ops and read-only behavior. Injected source/candidate/compiler changes were rejected without overwriting concurrent writers' bytes. CLI tests additionally exercised both nested commands, required arguments, JSON/newline output, exit status and legacy command dispatch. The focused tests also passed on macOS ARM64/Python 3.14.4; the complete native results above came from Linux.

The [separate native test](../tests/test_edit_validation_native.py) starts with a shared parameter that cannot grant the exclusive reborrow its helper requires. The correct candidate changes that parameter to exclusive. A second candidate makes the same permission repair but adds one to the returned value. Both candidates pass the shared frontend and receive successful preview receipts; each has `changes: null` because the base is invalid.

A separate C driver checks full i32 return values and mutation of the original counter against independently specified positive, negative, zero and boundary cases. Generated code and driver are separate translation units, compiled with `-std=c11`, `-O0` or `-O2`, `-fno-lto`, `-Wall -Wextra -Werror -pedantic-errors`. The correct candidate passes; the behaviorally wrong candidate fails with status one. The driver does not infer correctness from the preview receipt or a truncated return value. Its internal generated C interface is a test boundary, not a stable public ABI.

The guide's CLI example also ran: snapshot of `examples/invalid/type.tal` succeeded, candidate validation reported the base's E0201 and a valid candidate, and the original source remained unchanged. The generated candidate passed canonical formatting. This establishes the documented command path, without substituting for the independent native oracle.

## Existing offline fixture observations

All fixture selections ran in source-only and compiler-context conditions and then underwent independent reverification:

| Selection | Correct final candidates | Adapter calls | Repairs | Reverified |
| --- | --- | --- | --- | --- |
| Original corpus, all four tasks | 8/8 | 16 | 8 | 8 passed |
| Borrowing corpus, all four tasks | 8/8 | 16 | 8 | 8 passed |
| Anthropic fixture, `strict-type` | 2/2 | 4 | 2 | 2 passed |
| Anthropic fixture, `borrow-permission` | 2/2 | 4 | 2 | 2 passed |

The Messages fixture used `fixture-messages-v1` and tokenizer declaration `fixture: no tokenizer`. All token/cache/cost totals remained **null**. These completion counts measure scripted repairs and acceptance, not a model's success rate. The corpora keep their independent identities, denominators and acceptance code.

Task review identified missing automated coverage in the initial implementation. Seven focused tests added the promised CLI, borrowing/record contract and source-freshness cases. All 19 focused tests passed; scoped review approved the correction with no production-code change. The full Linux results above include those tests.

## CI and remaining limits

The existing protected native jobs discover the new tests alongside the full suite on Linux x86-64/Python 3.11, x86-64/Python 3.12, and ARM64/Python 3.12. They also exercise offline fixtures, sanitizers, freestanding execution, native examples and formatting. Documentation links, Mermaid rendering and DCO sign-off are checked separately. Configuration alone is not execution evidence; completed runs are available in the introducing PR's checks.

The preview does not establish atomic file application, a consistent multi-file snapshot, filesystem locking, behavioral equivalence, complete effects, ABI compatibility, process isolation, native target support by itself, or the M1 controlled-agent gate. An applying host must enforce writer coordination and task acceptance independently.
