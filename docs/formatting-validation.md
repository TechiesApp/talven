# M1b validation record

Date: 7 September 2026. This record covers the canonical formatter, its CLI/LSP integration, and the existing native subset. It is prototype evidence, not a production security audit or a model-efficiency benchmark.

## Local evidence

`python3 -m unittest discover -s tests -v`: **61 tests passed, no skips** on Linux x86-64 with CPython 3.12.13 and GCC 13.3.0 (`x86_64-linux-gnu`).

Compiler source fingerprint: `997c39d3a42fff81eade6376869c44d879cd28a9e574b9303957d727fbc83102`. This identifies the Python modules and is not an authenticity signature.

- Exact layout fixtures and idempotence, including empty/comment-only files, CRLF, Unicode comments, trailing comments, and comments inside expressions.
- Inserting a comment at every token boundary in a representative record/conditional program preserves C lowering and produces idempotent formatting.
- Sixty seeded whitespace variants produce the same layout and unchanged native C output. Parentheses, literal spelling, declaration order, and checked function contracts remain intact.
- Type/ownership-invalid examples still format and retain their diagnostic categories. Syntax, nesting, token, source-byte, and expanded-output failures return controlled diagnostics.
- Default/check-only formatting leaves files unchanged. Explicit writes preserve mode bits, reject stale hashes and direct symlink/hard-link targets, preserve observed concurrent edits, clean up after failed replacement, and avoid rewriting unchanged files.
- LSP returns the same canonical layout with UTF-16 edits, including non-BMP characters, without mutating the server's document or fetching unopened URIs. Syntax failures return no edit; type errors do not prevent formatting.
- Existing type/move, context, native arithmetic/trap, short-circuit, and freestanding tests pass alongside the new tests. Formatting/source hashes invalidate context identity as expected.

The CLI built and ran `examples/vectors.tal` successfully. All three `.tal` examples passed `fmt --check --json`. The new workflow YAML parsed with three declared target/runtime combinations.

The local documentation check verified **105 relative links across 28 Markdown files**. Rendering remains unavailable locally because the required Puppeteer browser is absent; its earlier download approval was cancelled. The four diagram blocks are unchanged, and the existing pull-request documentation job runs the full rendering check. Local link verification alone is not a diagram-rendering pass.

The [GitHub documentation job](https://github.com/TechiesApp/talven/actions/runs/34110749076/job/101706166572) subsequently passed the full relative-link and four-diagram rendering check for commit `b054445fd203684eec3a018a23231ce56e980c3c`. The DCO sign-off job also passed.

## Reproduce

~~~sh
python3 -m unittest discover -s tests -v
python3 -m talven fmt examples/vectors.tal --check --json
python3 -m talven fmt examples/invalid/moved.tal --check --json
python3 -m talven fmt examples/invalid/type.tal --check --json
python3 -m talven build examples/vectors.tal -o build/vectors
./build/vectors
node scripts/check-docs.mjs
~~~

Native tests need `cc`, its undefined-behavior sanitizer support, and `nm` for the freestanding symbol assertion. The new CI jobs fail if native tools are missing or any test is skipped. A local skipped test is not target evidence.

## Hosted target evidence

The first [native CI run](https://github.com/TechiesApp/talven/actions/runs/34110749528) succeeded on 7 September 2026 for commit `b054445fd203684eec3a018a23231ce56e980c3c`. Job logs reported the same compiler-source fingerprint as the local run above.

| Host and C target | Python | Tests | Execution evidence |
| --- | --- | --- | --- |
| Linux x86-64, `x86_64-linux-gnu` | 3.11.16 | 61 passed, no skips | [Job 101706168812](https://github.com/TechiesApp/talven/actions/runs/34110749528/job/101706168812) |
| Linux x86-64, `x86_64-linux-gnu` | 3.12.14 | 61 passed, no skips | [Job 101706168609](https://github.com/TechiesApp/talven/actions/runs/34110749528/job/101706168609) |
| Linux ARM64, `aarch64-linux-gnu` | 3.12.14 | 61 passed, no skips | [Job 101706168897](https://github.com/TechiesApp/talven/actions/runs/34110749528/job/101706168897) |

All three jobs used GCC 13.3.0, Ubuntu package `13.3.0-6ubuntu2~24.04.1`. The architecture assertion, test suite, all example formatting checks, and native CLI build/execution steps succeeded. This is actual hosted execution evidence for the M1a subset with M1b tooling.

Each job checks the actual machine architecture, runs the suite, validates example formatting, and compiles and runs the vector example through the CLI. This covers the current subset on those hosts, not all ARM/x86 hardware, OS/ABI variants, freestanding boards, concurrency, GPU memory, or foreign runtimes.

## Limits

No controlled LLM comparison, token/cost savings, cache-hit benchmark, editor-latency target, complete borrow checker, concurrency safety proof, or universal filesystem-integrity guarantee is claimed. The in-place writer has a documented compare/replace race and requires coordinated writers. See [formatting.md](formatting.md) for exact boundaries.
