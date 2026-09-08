# Proposal 0004: Reproducible agent evaluation

- Status: Draft
- Author(s): Talven contributors
- Requirements affected: R01, R02, R04, R05, R06, R08, R09
- Decisions affected: D01, D03, D15, D17, new D29
- Discussion: Pull request introducing this proposal

## Problem

The initial four tasks have written acceptance criteria but no executable evaluation harness. Compilation alone permits trivial solutions that remove a required move, bypass a binding, or hardcode a result. Token counts and costs without provenance would not establish agent effectiveness.

## Proposal

Add a Python standard-library runner under `experiments/`, separate from the compiler. Pin the corpus and protocol versions. For each task, context condition, and repetition, start from the original source and an empty conversation. Compare source-only input with the same source plus bounded compiler context (or diagnostics when the starting source is invalid). Both receive the current prototype and borrowing guides.

A trusted command adapter receives a versioned JSON request on stdin and returns a versioned JSON response on stdout. The model may submit only a complete replacement for `task.tal`. The runner creates the candidate itself; model output never selects commands, compiler flags, paths, tests, or verdicts. An adapter is trusted infrastructure, not an arbitrary coding agent with repository access. Adapters must provide provider usage and billing evidence separately from model-generated edits. Fixture adapters are explicitly labeled and excluded from model measurements.

Run structural acceptance and reviewer-controlled native C checks in a separate verifier process with timeouts. Compare exact i32 return values inside C instead of relying on truncated operating-system exit statuses. Keep verifier sources and generated checks out of the model request; return only diagnostic or criterion feedback. The model cannot submit replacements for them. This does not make public tests secret or provide an OS sandbox for a malicious adapter, compiler, or native executable.

Save the exact requests, responses, candidate sources, check output, source/guide/compiler/harness hashes, repository revision and dirty state, adapter identity/settings/artifact hashes, C flags/target/version, Python version, host information, and elapsed times. Bound repairs and process duration. Preserve each attempted call, including failed or malformed calls, in the denominator. Reject malformed metrics; missing usage or money remains null. Cache tokens are a separately reported subset of input tokens.

Sum actual provider input/output token counts across attempts. Model cost and adapter tool cost must be reported with provenance, never inferred from subscription usage or UTF-8 size. Total task cost additionally requires an explicitly supplied measured verification cost with provenance; otherwise report known subtotals and null total. Include failed tasks in total cost per correct completion, and leave that quotient null when there are no successes or any missing cost.

## Examples

The implemented CLI and adapter contract are documented in the [experiment guide](../../experiments/README.md). Offline fixtures verify harness behavior but are not model benchmarks. Recorded candidate artifacts can be independently reverified against matching trusted inputs.

## Alternatives considered

- A provider-specific runner couples the experiment to one API. Start with a small command protocol; adapters can select current providers without changing task acceptance.
- Letting agents run or edit their own acceptance tests makes success self-reported. The runner owns the edit boundary and invokes independent checks.
- Estimating missing tokens or dollars creates misleading totals. Preserve nulls and explicit coverage instead.
- A full container orchestration platform would add a deployment requirement. External isolation remains required for untrusted executables; this increment targets trusted adapters and the restricted Talven source interface.

## Costs and implications

- Agent context: two pinned guides, task instructions, source, optional bounded context, and prior repair conversation; actual token overhead is measured by the adapter.
- Runtime and memory: Python orchestration, per-attempt subprocesses, C compilation, native execution, and stored transcripts. No language runtime change.
- Security: trusted adapter/verifier/toolchain and host; artifact hashes identify bytes, not authorship. External operators enforce filesystem/network restrictions and protect billing evidence. No secrets belong in config, prompts, or committed transcripts.
- Targets: native execution requires a working host C11 compiler. No cross-target result is inferred from a target string.
- Ecosystem and interoperability: emitted C names remain an experimental test interface, not a stable foreign ABI.

## Evaluation

Use hand-checked successful repairs and adversarial candidates to test all four acceptance criteria. Exercise bounded repairs, repeated runs, both context conditions, invalid edits, failed adapters, timeouts, unavailable native tools, partial usage/cost, and provenance mismatches. Run all existing compiler tests unchanged, the dedicated borrowing sanitizer check, and documentation checks. Publish only actual execution evidence; controlled live model comparisons remain a separate experiment.

## Unresolved questions

Provider adapters, comparable cross-language corpora, statistical sample sizes, model-specific budget enforcement, stronger OS isolation, and accounting for shared infrastructure need measured follow-up. Model sampling is not made deterministic by recording a seed; reproducibility here means reconstructing inputs, settings, and acceptance.
