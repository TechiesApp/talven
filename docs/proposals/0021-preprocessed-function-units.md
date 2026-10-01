# Proposal 0021: Fresh preprocessing for function units

- Status: Draft; implemented reference preparation experiment
- Author(s): Talven contributors
- Requirements affected: R08, R12, R24, R25
- Decisions affected: D22, D38, D48, D49 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

[Hosted C units](../c-units.md) identify generated source, but header changes can change compiled objects without changing that source. Preprocessing each function separately also adds a compiler process and expands common headers for every function. Establish current expanded input before designing reuse.

## Proposal

Add opt-in `prepare-c-units SOURCE [--console] [--cc TOOL] [--timeout SECONDS]`. Fully analyze the current source through the shared frontend, then preprocess one bounded generated stream with common headers/contracts and reserved unit boundaries. Strictly split the result and prepend the same expanded header to each function/entry body. This is preprocessing input, not a valid combined C translation unit. Ordinary C emission and build/dev remain unchanged.

Preserve system-header markers and normalize only `<stdin>` marker numbers after preprocessing. The primary [GCC preprocessor output documentation](https://gcc.gnu.org/onlinedocs/cpp/Preprocessor-Output.html) describes filename, line and context flags; preserve system-header treatment when separately compiling frozen output. Actual macro expansions remain part of exact unit identities. Every unit still includes all current global contracts; dependency refinement is deferred.

Return `talven.preprocessed-units.v1`, profile `hosted-preprocessed-units-v1`, with exact source/compiler/language/console identities, fixed C flags, driver executable hash/version/target, hashed effective environment, input/raw-output hashes, normalization rule and ordered frozen units. Check driver/compiler-checkout bytes again before returning. Do not retain inherited environment values as fields. Compiler output can still contain host-specific data; receipts are local trusted-tool artifacts, not automatically public or authenticated evidence.

Use inherited environment copied once with `LC_ALL=C`, trusted GCC/Clang-compatible driver operations, POSIX process groups, bounded stdout/stderr and aggregate compiler-subprocess timeout. Document limits and timeout exclusions in [the command contract](../preprocessed-units.md). Reject bad boundaries/overflow/failure with no partial result. Do not compile objects, link, execute Talven programs, write source/unit files, add a shared cache or silently select this path for ordinary builds.

## Alternatives and costs

Per-function preprocessing repeats process/header work. Hashing only original includes misses resolved/transitive headers and macros. Removing all line markers loses host-header warning context. One fresh expanded stream gives inspectable current bytes, but duplicating expanded headers in receipts can greatly increase output, serialization and compile cost. Separate objects also inhibit cross-function optimization without LTO. No speed or memory improvement is claimed.

## Trust and invalidation

Only checked current source is lowered. Invalid source starts no compiler. Header/macro/global-contract changes affect exact expanded units; body-only changes can leave unrelated units stable. Hashes identify bytes, not authority. Driver identity omits backend binaries, libraries, configuration and other toolchain dependencies. Toolchain stability, object integrity, private storage, cache retention and fresh publication need an explicit later contract; these receipts alone do not authorize safe reuse.

## Evaluation

Test strict ordered boundaries, missing/repeated/empty/trailing rejection, resource limits, drift, current source, non-retained environment values, command cleanup and absence of program execution. Separately compile/link frozen units with strict C11/no-LTO settings, check exact static UTF-8/NUL output across functions and borrowing fixtures under both sanitizer optimization levels. Run the full reference suite, ordinary emitter differential corpus and documentation checks. Linux CI requires native evidence without skips; report local target limitations.

## Open work

Stable complete toolchain assumptions, objects and their corruption checks, reuse bounds, revision-aware linking/publication/cancellation, development integration, representative comparison measurements and design acceptance remain open.
