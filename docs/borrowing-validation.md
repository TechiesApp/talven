# M1c validation record

Date: 7 September 2026. This covers the experimental [call-scoped borrowing profile](borrowing.md), native lowering, and shared agent/editor contracts. It is not a production security audit, formal soundness proof, or model-efficiency benchmark.

## Local evidence

`python3 -m unittest discover -s tests -v`: **80 tests passed, no skips** on Linux x86-64, CPython 3.12.13, GCC 13.3.0 (`x86_64-linux-gnu`). This includes the prior 61 tests and 19 added test methods; parameterized cases exercise additional inputs.

Compiler source fingerprint: `e5c4c8973de267594e32d403a646c0c783178c6dfaf32af64f25b0551728bb69`. This hashes compiler modules, not all repository files, and is not an authenticity signature.

- Shared aliases/read access, exclusive field updates, explicit reborrowing, ownership moves after calls, nested call loan release, and retained outer loans.
- Rejection of conflicting reads/writes/moves, immutable mutations, shared-to-exclusive upgrades, reference escape/storage, bare reference forwarding, unsupported places, type mismatches, and assignment after moving its destination.
- Native argument/operand/record-initializer order, repeated mutating calls, short-circuit effects, right-hand-side mutation before a field store, recursive reborrowing, shared aliases, and moves after completed calls.
- Three borrowing programs execute at both `-O0` and `-O2` with undefined-behavior sanitization, strict C11 warnings, and no sanitizer diagnostics.
- Formatter comment insertion at every token boundary of a mutable/borrowed program preserves the token stream, C lowering, and idempotence. Invalid adjacent borrow tokens remain separate.
- Context v2 includes permission/scope/nonescape contracts and borrowed record schemas. LSP hover/definition uses the same frontend, and conflicting borrow edits produce E0302 then recover when corrected.

The complete address/undefined-behavior sanitizer check is a separate command. Locally, compilation succeeded but LeakSanitizer could not inspect `/proc/.../task` and reported that it cannot operate under tracing. This is a local runtime limitation, not a successful ASan check; no leak detection was disabled to report a pass. CI requires the full check on native hosts with leak and stack-use-after-return detection enabled.

Both CLI examples built and exited zero. All seven example/fixture `.tal` files passed canonical formatting checks, and the invalid borrow example returned E0302.

The local documentation check verified **135 relative links across 31 Markdown files**. Its four diagram renders could not run because the required Puppeteer browser is absent. The unchanged full rendering gate runs in GitHub CI; local links alone are not rendering evidence.

## Reproduce

~~~sh
python3 -m unittest discover -s tests -v
python3 -m talven fmt examples/borrowing.tal --check --json
python3 -m talven check examples/borrowing.tal --json
python3 -m talven context examples/borrowing.tal --symbol step_twice
python3 -m talven build examples/borrowing.tal -o build/borrowing
./build/borrowing
ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:halt_on_error=1 python3 scripts/check-borrow-sanitizers.py
node scripts/check-docs.mjs
~~~

The invalid borrowing example must return E0302. CI additionally checks formatting of all examples and both test fixtures, builds and executes the vector and borrowing CLI examples, and refuses missing native tools or skipped tests. Sanitizer checks require a supported C compiler/runtime and host OS facilities.

## Hosted target evidence

The [first M1c native run](https://github.com/TechiesApp/talven/actions/runs/34115045076) succeeded on 7 September 2026 for commit `c1ebc28a65ec91ad9657db3c90f97f66e4201f54`. All jobs reported the compiler fingerprint recorded above.

| Host and C target | Python | Test suite | ASan/UBSan executions | Job evidence |
| --- | --- | --- | --- | --- |
| Linux x86-64, `x86_64-linux-gnu` | 3.11.16 | 80 passed, no skips | 6 passed | [Job 101719770956](https://github.com/TechiesApp/talven/actions/runs/34115045076/job/101719770956) |
| Linux x86-64, `x86_64-linux-gnu` | 3.12.14 | 80 passed, no skips | 6 passed | [Job 101719770688](https://github.com/TechiesApp/talven/actions/runs/34115045076/job/101719770688) |
| Linux ARM64, `aarch64-linux-gnu` | 3.12.14 | 80 passed, no skips | 6 passed | [Job 101719771013](https://github.com/TechiesApp/talven/actions/runs/34115045076/job/101719771013) |

All three jobs used GCC 13.3.0, Ubuntu package `13.3.0-6ubuntu2~24.04.1`. The six sanitizer executions are three programs at two optimization levels, with address/undefined-behavior checks and explicit leak/stack-use-after-return detection. Each job also verified its actual architecture, checked all seven example/fixture layouts, and built and executed both CLI examples. The local LeakSanitizer limitation did not occur on these CI hosts.

The [documentation job](https://github.com/TechiesApp/talven/actions/runs/34115045136/job/101719771446) passed all 135 relative links and four Mermaid renders for that commit. The [DCO job](https://github.com/TechiesApp/talven/actions/runs/34115045136/job/101719771347) also passed. These CI results supply the rendering and full sanitizer evidence unavailable locally.

Earlier [M1b target results](formatting-validation.md) cover the previous profile; they remain separate historical evidence.

## Limits

The corpus demonstrates specified behavior on recorded hosts, not safety of arbitrary programs, all C compilers, or all ARM/x86 variants. There is no heap reclamation, general escaping-reference checker, concurrency model, safe FFI, GPU buffer lifetime support, or measured agent token/performance benefit. External toolchain and OS/runtime/hardware trust boundaries remain as documented in the guide.
