# Borrowing evaluation corpus validation

Measured on 8 September 2026. This records offline harness correctness for `m1c-borrowing-tasks-v1` and compatibility with `m1c-agent-tasks-v1`. No paid model calls were made. Tokens, dollar costs, model effectiveness, and compiler-context benefits remain unmeasured.

## Linux ARM64 execution

The final implementation ran on an actual ARM64 Docker host with the checkout mounted read-only and the ignored artifact directory writable:

| Input or check | Observed result |
| --- | --- |
| Container image | `python:3.11-bookworm`, image index digest `sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca` |
| Actual platform | Linux, `aarch64` |
| Python | 3.11.16 |
| C compiler | Debian GCC 12.2.0-14+deb12u1; target `aarch64-linux-gnu` |
| Talven compiler hash | `e5c4c8973de267594e32d403a646c0c783178c6dfaf32af64f25b0551728bb69` |
| Full unittest discovery | **144 tests passed, zero skips** |
| Borrowing sanitizer script | **6 ASan/UBSan executions passed**, at `-O0` and `-O2` |
| Native CLI examples | Both vectors and borrowing built and exited zero |
| `.tal` formatting | All **11** example/corpus/fixture files passed |

The compiler sources and original 80 compiler tests were unchanged. The 64 harness tests include the prior 39 tests plus 25 added tests for corpus routing, borrowing acceptance, and the borrowing fixture workflow. Native evaluation builds use `-std=c11 -O2`.

The borrowing acceptance tests check starter diagnostics E0302/E0303/E0304 and the valid-but-wrong ordering starter. They accept hand-written repairs and reject changed helper/main contracts, hardcoded answers, mutation bypasses, reconstructed records, extra helpers or branches, late snapshots, and unused helper results. Review exposed that passive call tracing alone accepted decorative calls; return-sensitivity checks and regressions now reject that case across all four tasks, including reconstructing one update result from another.

Each accepted borrowing candidate uses two native builds: ten ordinary input pairs and twenty probes with independently varied helper return values. The probes preserve actual record writes and check returned results, original-pointee identity, call counts/order, arguments, and snapshot use. Return adjustments use checked arithmetic, and trace/offset indices are bounded for invalid extra calls. These are finite public checks, not a proof against overfitting.

## Both offline corpora

The [documented fixture commands](../experiments/README.md) ran both corpora in source-only and compiler-context conditions, with fresh conversations and original sources for every trial:

| Observation | Original corpus | Borrowing corpus |
| --- | --- | --- |
| Corpus version | `m1c-agent-tasks-v1` | `m1c-borrowing-tasks-v1` |
| Trials | 8 | 8 |
| Accepted final candidates | 8 | 8 |
| Adapter calls | 16 | 16 |
| Repair attempts | 8 | 8 |
| Fresh independent reverification | 8 passed | 8 passed |
| Model input/output/cache tokens | Unmeasured (`null`) | Unmeasured (`null`) |
| Model/tool/verification/total dollar cost | Unmeasured (`null`) | Unmeasured (`null`) |

The fixtures intentionally submit the unchanged failing starter and then a hand-written repair. Their completion counts describe scripted runner behavior only. The borrowing integration test also verifies initial diagnostics versus context v2, independent context conditions, corpus provenance, and unknown usage accounting.

Local artifacts record base revision `a5e2e5146e3eaaaf2fc5f8a1e1e9812361fc5479` with a dirty working tree and archive the exact inputs. A validation driver's initial borrowing output name collided with its already-built example executable; the harness refused to overwrite it. The standalone borrowing run and reverification then completed in a fresh directory. No existing result was overwritten.

The original corpus remains the default, with unchanged task IDs, order, source paths, instructions, and acceptance. Historical reports remain readable; exact reverification still requires the matching trusted compiler/harness/source hashes. A new checkout does not silently reinterpret an old archive.

## Other checks and limits

A final targeted macOS ARM64 run encountered repeated five-second C compilation timeouts in an existing bypass regression, including its unchanged ordinary native build. The timeout was not increased or counted as success; the complete final Linux suite above passed that test. The [historical harness validation](evaluation-validation.md) separately records the earlier macOS compiler-baseline limitations. No full macOS conformance claim is made here.

The PR workflow runs both offline corpora and their reverification on Linux x86-64/Python 3.11, x86-64/Python 3.12, and ARM64/Python 3.12, alongside all tests, sanitizers, examples, and formatting. Documentation link and Mermaid checks are also required. Workflow configuration is not execution evidence; consult the actual PR checks for those runs.

Both corpora still require trusted adapters, compiler/harness sources, and native toolchains. This milestone does not provide a hostile-process sandbox, a live provider integration, comparative model results, or completion of M1.
