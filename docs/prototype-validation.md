# M1a validation record

Date: 7 September 2026. This is local prototype evidence, not a production security audit or comparative performance benchmark.

## Environment

| Item | Observed value |
| --- | --- |
| Host | Linux x86_64 |
| C target | `x86_64-linux-gnu` |
| Python | CPython 3.12.13 |
| C compiler | GCC 13.3.0, Ubuntu 13.3.0-6ubuntu2~24.04 |
| Compiler source fingerprint | `4224116f1b14ac01617db6e422fb50624400606b4009912d6b881f96fb7ff404` |

The fingerprint is emitted by `talven.context.compiler_hash()` and covers the Python compiler modules. It is an input identifier, not a signature or trust guarantee.

## Results

`python3 -m unittest discover -s tests -v`: **39 tests passed, no skips**.

- Positive and negative parsing/type cases, duplicate/unknown names, literal range, all-path return requirements, and scope boundaries.
- Moves through bindings, parameters, returns, continuing branches, and short-circuit expressions. Copying scalar fields remains valid.
- Deterministic context facts, source/compiler/target/query cache invalidation, exact byte-budget behavior, stale revision rejection, and opt-in untrusted source text.
- LSP framing and lifecycle, UTF-16 offsets, diagnostics, hover, definition lookup, symbols, stale document versions, malformed messages, and input limits.
- Native vector example, nested calls and records, C identifier mangling, and a seeded corpus of 80 scalar calculations under undefined-behavior sanitization.
- Eight overflow/division/remainder cases at both `-O0` and `-O2`: every case traps, without a sanitizer-reported C arithmetic error. These tests use `-fsanitize=undefined -fno-sanitize-recover=all`.
- Short-circuit operands skip a trapping function as specified.
- Freestanding vector object compiles with `-std=c11 -O2 -ffreestanding -fno-builtin`; `nm -u` reports only `talven_trap` for this example. No board startup or freestanding execution was tested.
- Failed native builds preserve an existing output, compiler selection is passed as an executable argument rather than a shell command, and output cannot overwrite source through the same path or a hard link.
- A seeded corpus of 300 malformed source strings produces controlled results. This is a small robustness probe, not sustained fuzzing coverage.

The CLI also compiled and ran `examples/vectors.tal` successfully as a hosted executable. The native program requires no Python interpreter at runtime.

### Documentation check

`node scripts/check-docs.mjs` verified 78 relative links across 25 Markdown files. Local rendering of the four architecture diagrams could not complete because Puppeteer's required `chrome-headless-shell` was absent. Installing that browser was blocked when network approval was cancelled. This is an environment limitation, not a successful diagram check.

The diagrams are unchanged from the design baseline. The existing [documentation workflow](https://github.com/TechiesApp/talven/actions/workflows/docs-check.yml) runs the full link and rendering check on the implementation pull request; consult that check for its result.

## Reproduce

~~~sh
python3 --version
cc --version
cc -dumpmachine
python3 -m unittest discover -s tests -v
python3 -m talven build examples/vectors.tal -o build/vectors
./build/vectors
~~~

Native tests are skipped if `cc` is unavailable. The native arithmetic suite additionally requires the selected compiler's undefined-behavior sanitizer support. This record applies to the environment above; do not interpret a skipped test as target support.

## Still unverified

ARM64 execution, other operating systems/ABIs, actual boards, production compiler throughput, LSP latency, runtime memory/throughput comparisons, controlled LLM task outcomes, and token/cost savings. The full M1 gate remains open. See [the agent evaluation protocol](../experiments/README.md) and [roadmap](roadmap.md).
