# Proposal 0011: Static text and optional console output

- Status: Draft
- Author(s): Talven contributors, following the owner's Hello World request
- Requirements affected: R01, R07, R08, R10, R11, R12, R15, R24, R25
- Decisions affected: D07, D09, D28, D39
- Discussion: [PR #11](https://github.com/TechiesApp/talven/pull/11), building on [design PR #10](https://github.com/TechiesApp/talven/pull/10)

## Problem

The native subset can compute and return an exit status, but it cannot print a greeting. Humans and agents need a small observable program before the watch/restart work in [Proposal 0010](0010-fast-compiler-and-development-reload.md). Adding a general string library, allocator, imports, or foreign interface would expand the scope substantially.

## Proposal

Add immutable static `str` values and a reserved builtin `fn print(text: str) -> i32`. Require explicit `--console` for hosted C emission or builds containing a call to this builtin. Static text itself remains usable in freestanding emission; console output does not.

`str` copies an address and byte length pointing to immutable static UTF-8 data. Literals are the only source of text storage. Values may be bound, copied, passed, or returned without introducing a borrow of stack data or a heap allocation. No record text fields, mutation, indexing, concatenation, equality, interpolation, dynamic strings, or stored borrowed references are added. Record fields remain `i32` and `bool`. Global declarations cannot replace `str` or `print`.

Quoted literals allow Unicode source text and the escapes `\"`, `\\`, `\n`, `\r`, `\t`, and `\0`. Unescaped ASCII controls, physical CR/LF, unknown escapes, and unterminated literals fail with E0006. There is no Unicode normalization or locale conversion. The formatter preserves the original literal spelling. A zero byte is data, not a terminator.

`print` writes exactly the supplied bytes to stdout, without appending a newline or interpreting formatting directives. The optional POSIX helper uses `write` through the host C library. It retries interrupted calls, continues after short writes, and returns `0` after all bytes have been accepted. It returns `1` for another returned write error or zero progress. Empty text succeeds without touching stdout. Nonblocking would-block is a failure, not a retry loop. Failure can leave partial output. A blocking write can wait, and repeated interruptions can keep retrying. Host signals are unchanged: a broken pipe may terminate the process with SIGPIPE. Success does not promise durable storage. These distinctions follow the [Linux write contract](https://man7.org/linux/man-pages/man2/write.2.html).

The build option selects a dependency, not a security permission. Frontend checks remain target-independent and do not execute I/O. Emission rejects missing console opt-in and any console/freestanding combination with E0404. All function bodies are emitted, so even a call in an unused function requires opt-in. No console helper or POSIX headers are emitted when there are no print calls.

Preserve context v2's existing source-function, record, and borrowed-parameter contracts. Add separate `builtins` facts and whole-program `required_runtime` dependencies; mark `str` parameter passing as `copy`. Advance the compiler and language/formatter profiles. Consumers must understand the new profile and fields before editing text/output code. A source hash alone is insufficient. Builtin hover has a checked signature but no invented source definition. Edit previews report the changed direct call without claiming runtime verification or a complete effect system.

## Examples

This syntax is implemented by the accompanying experiment:

~~~text
fn main() -> i32 {
    return print("Hello, world!\n");
}
~~~

~~~sh
python3 -m talven build examples/hello.tal --console -o build/hello
./build/hello
~~~

## Alternatives considered

- A literal-only print statement would get a greeting running but create a special statement and prevent passing/returning reusable text. Static `str` uses existing expression and function rules.
- C string/stdio lowering would make embedded zero-byte behavior and allocation costs harder to explain. Explicit lengths and an unbuffered write loop avoid those dependencies in generated output support.
- Raw Linux syscalls could avoid libc for printing, but require new target-specific console support. Preserve the existing separate no-libc probe; general freestanding console providers remain open.
- General imports, dynamic strings, and an I/O result type belong to later module, allocator, and typed-failure designs. This builtin and numeric result are experimental, not a final standard-library interface.

## Costs and implications

- Agent context: add static storage/copy rules, a builtin contract, and explicit runtime requirements. No token or task-cost benefit is claimed.
- Runtime and memory: literals occupy read-only static data; values carry a pointer and `size_t` length. The helper uses a stack offset and bounded write chunks, without allocation or stdio buffering in generated code. Hosted startup, libc, and the OS remain separate dependencies; their total allocations are not measured here.
- Security: writing stdout is an observable effect, and source-order/short-circuit semantics must hold. Lower literal bytes as numeric C array elements so source spelling cannot become C code or format directives. No sandbox or resource-permission enforcement is added.
- Targets: console support requires POSIX headers and services. Verified target claims are limited to recorded Linux ARM64 and x86-64 runs. No Windows, board, browser, or GPU console implementation is supplied.
- Interoperability: generated C types and symbols are an internal test interface, not a stable foreign ABI or permission to construct arbitrary `str` views from C.

## Evaluation

Keep the independent agent acceptance corpora and borrowing tests intact. Test exact bytes, Unicode, embedded zero bytes, empty/large literals, returning/copying static text, invalid syntax/types, forbidden text borrowing/mutation, argument order, and short-circuit suppression. Observe short writes, interruptions, zero progress, and partial failure at a controlled OS boundary; also run real descriptor failure and broken-pipe cases. Inspect emitted object dependencies, execute lifetime cases with ASan/UBSan, and keep the existing no-libc probe passing. Exercise CLI, formatter, context, edit preview, and LSP through the shared frontend.

Record actual verification in the [text/console guide](../text-console.md). CI must run all tests without skips on its declared architectures and independently compare the checked-in greeting's stdout bytes, stderr, and exit status. This feature supplies no compiler speed, model-effectiveness, or paid-provider measurements.

## Unresolved questions

Module-based I/O selection, typed output failures, mutable/dynamic text, Unicode operations, additional platform backends, and a stable native ABI need separate designs. Watch/restart is the next development-loop increment; incremental compilation and state-preserving hot reload remain later work. This short-lived example cannot demonstrate preserved application state.
