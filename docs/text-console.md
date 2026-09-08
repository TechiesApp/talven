# Static text and optional console output

Status: implemented experimental increment, compiler `0.4.0-dev`, language profile `m1-static-text-v1`, formatter `m1-static-text-layout-v1`, context `talven.context.v2`. It preserves the [M1c borrowing rules](borrowing.md). [Proposal 0011](proposals/0011-static-text-and-console-output.md) remains Draft; neither full M1 nor a production compiler is complete.

## Run Hello World

Use Python 3.11+ and a trusted C11 compiler with POSIX development headers and services. From the repository root:

~~~sh
python3 -m talven check examples/hello.tal --json
python3 -m talven fmt examples/hello.tal --check
python3 -m talven context examples/hello.tal --symbol main
python3 -m talven build examples/hello.tal --console -o build/hello
./build/hello
~~~

The [example](../examples/hello.tal) is:

~~~text
fn main() -> i32 {
    return print("Hello, world!\n");
}
~~~

Successful execution writes exactly `Hello, world!` followed by one LF byte and exits zero. The generated program runs natively without Python; this hosted console example uses the host C library and OS. `--console` also works with `emit-c`. Builds without it reject a program containing a print call with E0404 and preserve any previous output executable.

## Text values

`str` is an immutable view of static UTF-8 bytes, represented by an address and byte length. Literal storage lasts for the program's lifetime. A local binding does not own stack-backed text: copying, passing, and returning the view remain valid after the originating function returns.

~~~text
fn message() -> str {
    return "Hello, world!\n";
}

fn echo(text: str) -> i32 {
    return print(text);
}

fn main() -> i32 {
    let greeting = message();
    return echo(greeting);
}
~~~

Literals support ordinary Unicode source characters plus `\"`, `\\`, `\n`, `\r`, `\t`, and `\0`. Literal spelling is preserved by formatting; bytes are encoded as UTF-8 without normalization or locale conversion. Unknown escapes (including `\x` and `\u`), raw ASCII control characters, raw CR/LF, and missing closing quotes produce E0006. Use an actual Unicode source character when needed. A zero byte counts toward the length and is written normally. Text has no implicit trailing terminator.

The source, token, and nesting limits in the [prototype guide](prototype.md) still apply. `str` supports immutable locals and function parameters/results only. No equality, ordering, arithmetic, concatenation, indexing, interpolation, heap-backed strings, or text fields in records are added. `let mut` and explicit borrows remain restricted to named records; `&str` is not supported. `str` and `print` are reserved global declaration names. Existing local-namespace rules still apply; calls resolve globally.

## Output contract and dependency boundary

`fn print(text: str) -> i32` is a checked builtin with the following contract:

| Condition | Behavior |
| --- | --- |
| All bytes accepted | Return `0`; no newline or formatting is added |
| Empty text | Return `0` without touching stdout |
| Short write | Continue from the first unwritten byte |
| Interrupted before progress | Retry |
| Other returned error, including would-block | Return `1`; earlier bytes may already be visible |
| Unexpected zero progress on nonempty text | Return `1` |
| Host signal or indefinitely blocked output | Retain host behavior; there is no new signal handler or timeout |

The POSIX implementation uses the host library's `write`, in chunks up to 16 KiB, with no stdio buffering, format-string interpretation, or allocator calls in emitted output support. It is synchronous. It does not promise an atomic line, rollback, or durable storage, and does not return the host error code. In particular, a broken pipe can terminate the process with SIGPIPE rather than return `1`. See the [Linux write documentation](https://man7.org/linux/man-pages/man2/write.2.html). Propagate or check the status when output is required for task success, as the greeting does.

Every syntactic print call requires the explicit console option during emission, including calls in unused functions or short-circuited expressions. This matches the current backend's whole-program emission. Actual execution still respects left-to-right order and `&&`/`||` short-circuiting. Programs without print calls emit neither the console helper nor POSIX headers even if the option is supplied.

Static text can be emitted with `--freestanding` without console or allocator dependencies in the tested fixture. Printing in that profile, or combining `--console` and `--freestanding`, is rejected. The existing [no-libc Linux probe](freestanding.md) stays separate. The hosted greeting's process startup, host library, and OS are not claimed to perform zero total allocations. Generated C is inspectable but is not a stable safe foreign interface; hand-written callers could violate text validity or lifetime assumptions.

## Editor and agent behavior

Analysis is shared by CLI, context, read-only edit previews, and LSP. Checking or formatting a print call does not execute it or invoke a C compiler. LSP hover describes the builtin contract; definition returns no source location for a builtin. Normal text bindings and user functions retain source navigation. Formatting treats a literal as one token: comment markers and delimiters inside it remain text.

Context keeps `talven.context.v2` and its existing borrowed-parameter facts. The new language profile adds:

- `str` parameters with `passing: "copy"`.
- A `builtins` array for builtin calls in selected source functions and their direct source callees. Builtins are separate from source declarations and source-function `dependencies`.
- `required_runtime`, which reports console requirements across all emitted functions even for a selected symbol or a requested freestanding target.
- A static-text rule and builtin output/error/effect information.

`validation: "frontend-only"` still means no build, link, runtime, or capability validation. In particular, freestanding context can describe checked code that later fails target emission because it requires console support. `context --symbol` continues to select source declarations, not builtins. Consumers must recognize the language profile and runtime fields before editing this feature. Compiler/version/profile/source identities invalidate previous context keys. A hash or the console option does not grant OS permissions. Edit receipts expose added/removed direct `print` calls, not full transitive effect analysis.

## Verification

The [frontend/tooling tests](../tests/test_text.py) and [native tests](../tests/test_text_native.py) cover the contracts above with fixed expected bytes and independent native observations. Controlled write-boundary fixtures test short writes, interruptions before and after progress, partial failures, and zero progress. Real native executions check descriptor failure, SIGPIPE, long literals, no formatting interpretation, ordering, and short-circuiting. The lifetime/embedded-zero fixture also runs with ASan/UBSan; object inspection checks the tested allocator/console dependency boundary.

The [CI workflow](../.github/workflows/compiler-check.yml) requires all tests without skips on Linux x86-64 with Python 3.11/3.12 and ARM64 with Python 3.12. It also builds the checked-in greeting and independently compares exact stdout, empty stderr, and zero exit status. Required borrowing sanitizer and no-libc checks remain in place. Target declarations and test definitions alone are not execution evidence; successful runs are recorded with the implementation PR.

No compiler-throughput improvement, model token/cost result, whole-process allocation total, or broader platform support is measured by this increment. The agent acceptance corpora remain independent and unchanged. A short-lived greeting prepares for watch/restart; it does not implement or validate live reload, incremental compilation, or state-preserving hot reload.

### Local execution record, 8 September 2026

The implementation working tree passed **232 tests with no skips** in a Linux ARM64 Docker environment: CPython 3.11.16, GCC 12.2.0 (`aarch64-linux-gnu`), GNU Binutils 2.40. This includes 28 new text/tooling/native tests and the existing suite. Two legacy diagnostic cases were updated because quoted text now lexes successfully; illegal-character coverage was retained. The independent agent corpora and native acceptance rules were unchanged.

The text lifetime/embedded-zero test passed ASan/UBSan with stack-use-after-return detection and inlining disabled. The separate borrowing sanitizer check passed all six executions. The existing freestanding probe passed all 18 success/trap executions with dependency inspection. Example formatting and whitespace checks passed; documentation validation checked 267 relative links and rendered four diagrams at that point.

Compiler module fingerprint for these executions: `78074c94edcd20405a117ef51a943cfbe2c773112a195ffeb663a8c619c7c389`. These were working-tree checks, not a clean release benchmark; local raw logs and the freestanding report remain under ignored `build/hello-*` paths. GitHub checks provide separate clean-checkout target evidence after publication.

### GitHub execution record, 8 September 2026

[PR #11](https://github.com/TechiesApp/talven/pull/11) implementation commit `0df054429aa5f84c3f75eae922f2627b39f47a4a` passed the [compiler workflow](https://github.com/TechiesApp/talven/actions/runs/34212251417) with the same compiler fingerprint. Each job verified its actual architecture, passed **232 tests without skips**, and independently executed the greeting with exact stdout, empty stderr, and exit zero:

| Actual Linux host | CPython | C compiler and target | Execution |
| --- | --- | --- | --- |
| x86-64 | 3.11.16 | GCC 13.3.0, `x86_64-linux-gnu` | [Passed](https://github.com/TechiesApp/talven/actions/runs/34212251417/job/102015724662) |
| x86-64 | 3.12.14 | GCC 13.3.0, `x86_64-linux-gnu` | [Passed](https://github.com/TechiesApp/talven/actions/runs/34212251417/job/102015724987) |
| ARM64 | 3.12.14 | GCC 13.3.0, `aarch64-linux-gnu` | [Passed](https://github.com/TechiesApp/talven/actions/runs/34212251417/job/102015724958) |

All three jobs also passed both offline agent corpora, the Anthropic fixtures, borrowing sanitizers, the no-libc probe, and the tooling baseline correctness gates. The [documentation and DCO workflow](https://github.com/TechiesApp/talven/actions/runs/34212251395) passed. These results establish the tested behavior on those hosts; they do not establish speed improvements or live-model effectiveness. Later documentation-only evidence additions do not change the compiler fingerprint above.
