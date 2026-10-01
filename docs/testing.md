# Native test manifests

The reference command `python3 -m talven test MANIFEST` runs explicit cases for the implemented single-file language. It shares the ordinary frontend and C lowering; it adds no language test syntax, package system, foreign ABI or release runtime. See [Proposal 0029](proposals/0029-native-test-manifests.md).

Run the repository's examples, including exact console output and expected type, move and borrow diagnostics:

```sh
python3 -m talven test examples/tests.json
python3 -m talven test examples/tests.json --json
```

## Manifest

```json
{
  "schema": "talven.test-manifest.v1",
  "cases": [
    {"id": "vectors", "source": "vectors.tal", "result": 0},
    {"id": "hello", "source": "hello.tal", "console": true, "stdout": "Hello, world!\n"},
    {"id": "type-error", "source": "invalid/type.tal", "diagnostic": "E0201"}
  ]
}
```

Sources are relative to the manifest's directory. The root object has only `schema` and `cases`; cases have only the fields shown above plus optional `stderr`. Case IDs are unique ASCII letters/digits/underscore/hyphen, 1–64 characters. `source` is a nonempty relative `.tal` path, at most 1024 UTF-8 bytes, without NUL or parent traversal. Its resolved path must stay inside the manifest directory. Files must be regular UTF-8 files; the manifest and each source are limited to 256 KiB. Duplicate JSON keys, unknown fields, nonstandard JSON constants and invalid UTF-8 strings are rejected. The manifest contains 1–128 cases.

`console` is a boolean, default false. A runtime case needs the ordinary zero-argument `fn main() -> i32`. `result` is a signed i32 JSON integer, default zero; booleans/floats are rejected. `stdout` and `stderr` are UTF-8 strings, default empty, each at most 64 KiB. Bytes match exactly, including NULs, line endings and Unicode encoding; no newline is added.

A diagnostic case supplies `diagnostic: "Edddd"` and omits `result`, `stdout` and `stderr`. It compares the first shared frontend/lowering diagnostic; `console` can still select console emission. Input/setup failures, missing tools, native build failures, traps and timeouts cannot satisfy that expectation. A valid program with an expected diagnostic fails before native compilation.

## Native execution and reports

Runtime cases compile/link in private temporary directories with a trusted GCC/Clang-compatible C11 compiler (`--cc`, default `cc`). The subject's generated C entry adapter is renamed for the test build. A separately compiled C driver calls the lowered main function and captures its full signed result. This prevents a return value such as 256 from passing an expected-zero test because the operating system truncates the exit status. The driver appends a private bounded result suffix to stdout; the runner removes the final suffix and compares the preceding program output. Printing a lookalike suffix does not replace the driver's actual result. This internal symbol is not a supported foreign interface.

`--timeout SECONDS` accepts 0.01–60, default 30, as an aggregate per-case command budget, including elapsed setup time before each command. Commands use owned process groups with cleanup on timeout, output overflow, failure or interruption. This does not interrupt synchronous Python work or enforce memory/disk quotas. Program stdout is limited to 64 KiB plus protocol overhead; stderr is limited to 64 KiB. Object and executable artifacts must be regular, nonempty files of at most 16 MiB. Artifact/compiler identities are checked around execution; source bytes are captured once for each case. Hashes identify captured inputs, not a later on-disk revision or independently authenticated toolchain.

Human output gives PASS/FAIL IDs and counts. `--json` emits a bounded `talven.test-report.v1` report under profile `hosted-i32-tests-v1`, including language/compiler/manifest/source identities, host, compiler version/target, flags, environment hash, phase, expected/actual results, output byte counts/hashes/previews and failure diagnostics. Previews retain at most 1024 bytes per stream; full byte comparisons happen before previewing. A failed command reports its bounded captured streams and return status. Diagnostics have bounded messages. Reports are limited to 2 MiB; an oversized report fails rather than presenting partial acceptance.

Exit zero requires a complete report with every case passing. Runtime mismatches fail even when compilation and the driver exit succeed. E0801 describes invalid manifest/expectation setup; E0802 describes an invalid full-result protocol. Existing E0005/E0402/E0501/E0901 cover size/command/freshness/input failures.

These are trusted local hosted tests, not hostile-code isolation. Path validation guards mistakes; it cannot secure a concurrently hostile filesystem. The inherited toolchain and native code can access the host. Reports hash environment values without publishing them, but expected/actual output is test data and should not contain secrets. Tests establish their declared expectations, not general task correctness, performance or model-cost savings.

## Verification

The [test runner cases](../tests/test_test_runner.py) exercise full signed results (including 256 and i32 extremes), UTF-8/NUL/lookalike-protocol output, exact stderr comparison, existing borrow/store examples, current compiler diagnostics, invalid manifests, regular-input limits, missing/failed tools, missing artifacts, compiler drift, runtime overflow traps, malformed result protocols, timeout/output overflow and CLI exit behavior. The existing [bounded-command tests](../tests/test_c_command.py) additionally verify owned descendant cleanup and retained process identity. Native CI executes the [seven-case example manifest](../examples/tests.json) on declared Linux x86-64 and ARM64 hosts and preserves its reports. Actual check results are recorded with the implementation pull request; broader M1 gates remain in the [roadmap](roadmap.md).

Local validation on 2 October 2026 used macOS ARM64, CPython 3.14.7 and Apple Clang 21 with the recorded strict C11/O2 flags. All 19 focused test-runner tests passed, and the full reference suite ran 464 tests in 208.070 seconds with no failures and one declared Linux-only skip. The CLI example manifest passed all seven cases. The separate reference borrow sanitizer probe passed six native executions across O0/O2 with ASan/UBSan. This Mac run does not substitute for Linux host evidence; CI rejects skipped tests on its declared Linux hosts.
