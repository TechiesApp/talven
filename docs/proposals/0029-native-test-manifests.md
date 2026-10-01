# Proposal 0029: Bounded native test manifests

- Status: Implemented reference experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R08, R10, R12, R24
- Decisions affected: D57 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Scope and protocol

The current developer workflow lacks a user-facing test runner. Add `talven test MANIFEST` for a bounded versioned JSON manifest of existing single-file source programs, without new language syntax, packages or foreign ABI support. Each case names a relative source, explicit console selection and either a first compiler diagnostic or an expected full `i32` main result plus exact stdout/stderr. Default expected result/output is zero/empty.

Use the shared frontend and ordinary C lowering. For native cases, compile the ordinary subject with its generated C entry symbol renamed, then independently compile/link a private hosted C11 driver calling the already-lowered `tv_f_main`. Capture the full signed result in a bounded private trailing stdout protocol, remove that protocol and compare values/output. Operating-system exit status alone is insufficient: 256 can appear as exit zero. This driver is test-only and adds no release runtime, language FFI or supported target profile.

Frontend-diagnostic expectations are checked before any native invocation and cannot be satisfied by a missing tool, timeout or execution failure. Source I/O/setup errors fail independently. Native cases require actual normal driver completion, valid full-result protocol and exact expected bytes. Run case commands in owned private temporary storage with bounded input/artifacts/output, aggregate per-case command budget and process-group cleanup. Preserve structured failure details, current source/compiler identities and bounded output previews; hashes do not establish authentication or independent task acceptance.

## Inputs and evidence

Validate a bounded regular UTF-8 manifest, exact schema/known fields, duplicate keys/case IDs, relative source paths, booleans, signed result range, expected output byte limits and case count before source compilation. Use the existing regular-source reader and shared language/source limits. Keep test source/output files separate from user destinations; no source or existing artifact is overwritten. Relative paths are an accidental-path guard, not a hostile-filesystem/native sandbox or policy enforcement boundary.

Verify full return values including 0, 256, negatives and i32 extremes; exact UTF-8/NUL output; current diagnostics; borrow/store programs; malformed/duplicate/oversized manifests; FIFO/source failures; incorrect output/value; missing/failed compilers; truncated/forged protocol; runtime traps/timeouts/overflow and group cleanup. Run the shared reference/native/sanitizer suites and exercise the CLI on declared Linux CI hosts. Record target/compiler flags and actual pass/fail counts. This is correctness tooling, not a speed, model-cost or broader language support claim.

The [implemented command and limits](../testing.md), [behavioral tests](../../tests/test_test_runner.py) and [example manifest](../../examples/tests.json) define the current experiment. Compared with adding test declarations or discovering arbitrary function names, an explicit manifest retains the current source grammar and makes the acceptance criteria visible. Compared with shell exit-status checks, the independent driver preserves the full signed result. The cost is fresh strict C11 object compilation, linking and native execution for every runtime case; no cache, parallelism or timing improvement is claimed. Broader language test declarations remain a separate design.
