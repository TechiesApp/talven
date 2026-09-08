# Anthropic adapter validation

Measured on 8 September 2026. This records offline verification of the optional [Messages adapter](../experiments/adapters/README.md). No live provider call or real credential inspection was performed. Model effectiveness, live API compatibility, token consumption, and dollar cost remain unmeasured.

## Linux ARM64

The final implementation ran with the checkout mounted read-only and the ignored build directory writable:

| Input or check | Observed result |
| --- | --- |
| Container | `python:3.11-bookworm`, image digest `sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca` |
| Actual host | Linux `aarch64` |
| Python | 3.11.16 |
| C compiler | Debian GCC 12.2.0-14+deb12u1; target `aarch64-linux-gnu` |
| Talven compiler hash | `e5c4c8973de267594e32d403a646c0c783178c6dfaf32af64f25b0551728bb69` |
| Full unittest discovery | **163 passed, zero skips** |
| Borrowing sanitizers | **6 ASan/UBSan executions passed**, at `-O0` and `-O2` |
| Native examples | Vectors and borrowing built and exited zero |
| Formatting | All **11** `.tal` example/corpus/fixture files passed |

The existing 144 tests, compiler, runner, and both corpora were unchanged. The 19 added tests comprise 15 mocked adapter tests and four runner integration tests. Native acceptance uses `-std=c11 -O2`; borrowing acceptance retains its independent ordinary-value and helper-return-sensitivity builds.

## Offline fixture observations

Every fixture below ran in source-only and compiler-context conditions with fresh conversations, then underwent independent reverification:

| Fixture and task selection | Trials | Correct final candidates | Adapter calls | Repairs | Reverified |
| --- | --- | --- | --- | --- | --- |
| Original fixture, all four original tasks | 8 | 8 | 16 | 8 | 8 passed |
| Borrowing fixture, all four borrowing tasks | 8 | 8 | 16 | 8 | 8 passed |
| Anthropic fixture, `strict-type` only | 2 | 2 | 4 | 2 | 2 passed |
| Anthropic fixture, `borrow-permission` only | 2 | 2 | 4 | 2 | 2 passed |

The Messages fixture identity is `fixture-messages-v1`; its tokenizer declaration is `fixture: no tokenizer`. Each sequence returns a failing starter and a hand-written repair. All input/output/cache token totals and all dollar amounts remain **null**, including synthetic usage suppression at the adapter envelope. These completion counts measure scripted execution, not an agent's success rate. The two corpora retain separate identities and denominators.

The integration tests block Python socket connections in child processes, provide a fake key sentinel, and verify no sentinel appears in archived files. They check request translation hashes, fixture/adapter artifact bytes, both contexts, repaired histories, and fresh native reverification. Additional cases confirm invalid completed JSON remains repairable, truncated/refused output cannot become a candidate, and exhausted fixtures do not repeat a response.

Mocked transport tests check exact history/settings/schema translation, separate cache components, partial/malformed usage, thinking details without double counting, provider failures with retained receipts, model-written accounting rejection, fixed endpoint/version, request/response bounds, one-call behavior, connection cleanup, safe errors, and credential-free config/fixture paths.

Review found that empty fixture/config path arguments could be confused with absent options. Both now fail before credential/network access, with regression coverage. An initial Linux test used a repository-local temporary directory and failed against the read-only mount; it now uses the system temporary directory. The final full-suite result above includes those fixes. Independent review found no remaining actionable issues after the fixes.

Local run archives record base revision `129352ef28a454a9ab40f184a84c34035b52ff06` with a dirty working tree and preserve the exact inputs. They are development verification evidence, not a clean-release benchmark. The 15 mocked adapter tests also passed on macOS ARM64/Python 3.14.4; no full macOS native conformance claim is made.

## Remaining evidence

The PR workflow runs the full suite, both original fixtures, both selected Messages tasks, sanitizers, examples, and formatting on Linux x86-64/Python 3.11, x86-64/Python 3.12, and ARM64/Python 3.12. Documentation links and Mermaid rendering are checked separately. Workflow configuration alone is not execution evidence; actual runs are available in the introducing PR's checks.

A pinned real model, its tokenizer declaration, approved spending limits, live API validation, billing receipts, repeated trials, and comparative conclusions remain future work. This adapter does not complete M1 or change the trusted host/toolchain boundary.
