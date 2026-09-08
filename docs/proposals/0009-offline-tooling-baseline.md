# Proposal 0009: Offline compiler and tooling baseline

- Status: Draft
- Author(s): Talven contributors
- Requirements affected: R01, R04, R09, R11, R12, R15
- Decisions affected: D08, D22, D24, new D34
- Discussion: Pull request introducing this proposal

## Problem

The Python/C11 compiler has correctness evidence but no repeatable baseline for command latency and output size. Production compiler/backend decisions need actual measurements. Live agent evaluation remains separate and has not been authorized for this increment.

## Proposal

Add a dependency-free offline runner for four fixed workloads: the existing vector and borrowing examples, plus 32- and 128-helper chains. Measure complete check, formatting, selected context, snapshot, edit preview, C emission, direct C compile/link, and full Talven build processes. Preserve every measured sample, warmups, inputs, generated code, native oracles, tool identities, commands, outputs, and failures. Define the implemented interface and limits in the [guide](../tooling-baseline.md).

Correctness gates precede summaries. Separate native C oracles compare full values and record mutation; every build executes, and repeated tool outputs must match checked references. Reject incomplete suites or observed source/compiler/tool changes. Preserve independent compiler and agent acceptance tests. Record unknown hardware details and unmeasured quantities explicitly. Do not convert bytes to tokens, wall time to charges, or five samples into a tail-latency claim.

## Examples

The following invokes the implemented experiment on a fresh output directory:

~~~sh
python3 scripts/measure-tooling.py --out build/tooling-baseline --repetitions 5 --warmups 1
~~~

The candidate edit adds one unused scalar helper. It measures valid-base declaration comparison, not model repair effectiveness or arbitrary change impact.

## Alternatives considered

- Shell timing alone loses output/correctness checks, exact inputs, and failure provenance.
- In-process microbenchmarks can isolate frontend work, but omit Python startup and the public CLI path. They can follow this baseline if a measured question calls for them.
- Inferring frontend time by subtracting separate build medians confounds process/cache/toolchain conditions.
- Performance thresholds on shared CI runners would turn environmental noise into a correctness gate. CI checks successful execution and complete evidence instead.

## Costs and implications

- Agent context: machine-readable summaries and raw outputs become available; no agent context or token improvement is inferred.
- Runtime and memory: no language or generated runtime changes; repeated builds consume host time and artifact storage. Memory use is unmeasured.
- Security: trusted subprocess execution, bounded repetitions/timeouts, fresh output directories and observed input checks; no sandbox, archive authentication, or release authority.
- Targets: collect actual OS/architecture/toolchain evidence per run; compilation and execution are native, with an optional expected-architecture guard. No cross-compilation or board support is added.
- Ecosystem: the experiment is separate from provider adapters and agent task acceptance. Production compiler/backend choice remains open.

## Evaluation

Test invalid options, existing-output protection, raw-byte/hash preservation, timeout/launch/nonzero failures, partial reports, warmup exclusion, complete sample counts, deterministic outputs, and native rejection of a type-valid wrong program. Run the complete fixed suite and existing native regression checks. Publish observed sample distributions and byte sizes with exact environment and input identity, including cache/virtualization limitations.

## Unresolved questions

Representative larger workloads, diagnostic/error paths, incremental LSP operation, memory/allocations, fully pinned execution images, cache-state control, process-isolated microbenchmarks, statistical comparison, and controlled model task performance remain future experiments. This baseline alone does not justify replacing the bootstrap or closing M1.
