# Benchmarks and evidence at a glance

Talven is early. This page gathers the measurements it has so far, so you can judge whether the direction is worth your time. Every number here comes from a committed, reproducible record linked in its section. Each section also says what the number does **not** show.

## Summary

| Question | Measured answer | Source |
| --- | --- | --- |
| Can a current model work in Talven from one page of documentation? | Claude Opus 5.5 passed **16 of 16** repair and edit tasks on the first attempt, about **$0.02 per task** at list price | [Agent pilot](#agents-can-use-it-today) |
| How much prompt does the language itself cost? | The whole system prompt, including the language reference, is about **3,900 tokens** | [Agent pilot](#agents-can-use-it-today) |
| Does compiler context stay small as programs grow? | Selected-symbol context stayed at **~1.5 KB** while source grew **4×** (2.2 KB to 8.6 KB) | [Bounded context](#compiler-context-stays-bounded) |
| How fast is the native checker? | Checks a **2,400-line** program in **4.1 ms** end to end, start-up included | [Checker speed](#native-checker-speed) |
| How small can programs be? | A no-libc Linux program links to **2,800 bytes** with **1,072 bytes** of code | [Footprint](#small-freestanding-programs) |
| Is the implementation trustworthy? | 270+ tests, a **548-case** differential suite between two independent compilers, sanitizers, and CI on Linux x86-64 and ARM64 | [Correctness](#correctness-investment) |

## Agents can use it today

**Record:** [pilot evidence](pilot-evidence.md) and its [archived runs](../experiments/results/pilot-opus-5-5-20260924/).

Claude Opus 5.5, effort `high`, received only the one-page [language reference](language-reference.md), a task, and the source. Every task was accepted by independent native tests, not by the compiler under test.

| Corpus | Trials | First-attempt passes | Input tokens per call (mean) | List-price cost |
| --- | --- | --- | --- | --- |
| Records, moves, types, refactors | 8 | 8 | 4,943 | $0.146 |
| Shared and exclusive borrowing | 8 | 8 | 5,225 | $0.184 |

About 3,900 tokens of each call were the cached system prompt (31,160 cache-read tokens over 8 calls per corpus): the model learned a new language from that much text. Costs are list-price equivalents; the run used a subscription.

**Limits.** Eight tasks per corpus, one repetition, one model. The tasks sit at a ceiling, so this does not yet show that compiler context helps; that needs harder tasks. See [next steps](pilot-evidence.md#next-steps).

## Compiler context stays bounded

**Record:** [tooling baseline](tooling-baseline-evidence.md) (Linux ARM64, 8 September 2026).

`talven context --symbol` returns a checked, deterministic summary of one function and its direct dependencies instead of the whole file.

| Workload | Source bytes | Selected context bytes |
| --- | --- | --- |
| Chain 32 | 2,170 | 1,554 |
| Chain 128 | 8,563 | 1,560 |

Source grew about four times; the context an agent needs for the edit did not. This is the mechanism behind the product goal of lower cost per task.

**Limits.** Bytes, not tokens, on synthetic call chains. Whether smaller context improves agent success is exactly what the harder corpus must test.

## Native checker speed

**Record:** [`frontend-benchmark-macos-arm64-20260924.json`](../experiments/results/frontend-benchmark-macos-arm64-20260924.json), produced by [`scripts/benchmark-frontends.py`](../scripts/benchmark-frontends.py) on macOS ARM64 (Python 3.14.7, Apple clang 21, rustc 1.96). The workloads are generated programs of scalar functions with arithmetic, conditionals, and calls, up to the prototype's token limit. Values are wall-clock medians of 9 runs after a warm-up.

| Program | Talven native, end to end | Talven Python reference, in-process | `clang -fsyntax-only` (equivalent C) | `rustc --emit=metadata` (equivalent Rust) |
| --- | --- | --- | --- | --- |
| 10 functions, 83 lines | 4.4 ms | 0.9 ms | 15.4 ms | 25.8 ms |
| 100 functions, 803 lines | 4.1 ms | 8.5 ms | 16.0 ms | 35.5 ms |
| 300 functions, 2,403 lines | 4.1 ms | 26.8 ms | 18.9 ms | 54.8 ms |

The native time is almost entirely process start-up: it barely changes between 83 and 2,403 lines. The Python reference is the specification-grade implementation; it scales linearly and is fine for today's program sizes.

**Limits.** Clang and rustc do more work for richer languages, include standard-library or header processing, and start larger processes, so their columns give scale rather than a like-for-like race. The native prototype covers scalars and text only, not records or borrowing. One host, one run.

## Small freestanding programs

**Record:** [freestanding validation](freestanding-validation.md) (Linux ARM64, GCC 12, no libc, no allocator).

| Build | Executable bytes | Code (text) bytes |
| --- | --- | --- |
| `-O2`, success path | 2,800 | 1,072 |
| `-O2`, trap path | 2,464 | 736 |

Checked arithmetic and traps are included; nothing else is linked. This supports the goal of a small freestanding core.

## Correctness investment

- **Two compilers, one behavior.** The Python reference and the Rust prototype are compared on 548 cases (examples, 116 hand-written edge cases, 160 random programs, 260 mutations): diagnostics must match code, message, and range, and emitted C must be byte-identical and run identically.
- **Sanitizers.** Borrowing and text lifetimes run under ASan and UBSan.
- **Test coverage.** The reference suite has 270+ tests and runs in CI on Linux x86-64 and ARM64 with no skips allowed.

## Reproduce

~~~sh
# Native checker comparison (needs Rust 1.96 via rustup; clang/rustc optional)
cargo build --release --manifest-path experiments/native-compiler/Cargo.toml
python3 scripts/benchmark-frontends.py --native experiments/native-compiler/target/release/talven-native \
  --sizes 10,100,300 --out build/frontend-benchmark.json

# Offline tooling baseline
python3 scripts/measure-tooling.py --out build/tooling-baseline

# Agent pilot (requires a signed-in Claude Code CLI; spends subscription usage)
python3 experiments/adapters/claude_code_cli.py --write-config build/cli.json --model claude-opus-5-5 --effort high
python3 -m experiments run --adapter build/cli.json --max-cost-usd 10 --out build/pilot
~~~

Report the host, tool versions, and every sample with new results; see [AGENTS.md](../AGENTS.md) for the evidence rules.
