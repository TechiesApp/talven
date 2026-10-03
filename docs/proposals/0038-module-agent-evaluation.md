# Proposal 0038: Bounded multi-file agent evaluation

- Status: Draft; implemented corpus and harness integration, live results separate
- Requirements affected: R01, R02, R04, R05, R06, R08, R12
- Decisions affected: D66 (proposed), D42, D61, D65

## Problem

Existing single-file pilots hit first-attempt correctness ceilings. They do not
exercise the new module graph, alias contracts or distinct record identities.
Adding modules is implementation evidence; useful agent context needs its own
controlled experiment.

## Proposed experiment

Register `m1-module-tasks-v1` with two deterministic public tasks, containing
eight and twelve ordered stages. Each entry imports aliases from two fixed source
dependencies. Each dependency defines its own nominal `Account`, helpers with
four parameter forms and a private same-named helper. The entry defines a third
equally shaped record. A candidate implements only `pipeline`; all imports,
other declarations, signatures and dependency bytes remain fixed.

Both conditions receive identical core and [module references](../module-reference.md),
instructions, entry source, and complete read-only dependency sources. The
compiler condition additionally receives bounded fresh `talven.project-context.v1`
focused on `task.tal::pipeline`, or original-file diagnostics for an invalid
candidate. Qualified receipt labels are explained as identities, not source names.
The source condition receives language rejection without diagnostic text; native
acceptance feedback is shared. This tests adding context, not substituting shorter
interfaces for source or the native context/edit tools.

Task inputs, guides, compiler/harness Python bytes and adapter artifacts are
fingerprinted. The run records the companion language profile. Dependencies are
prompt data and trusted verifier inputs, outside the one-file edit set. Function
splicing uses token spans and retains the complete resulting entry artifact.
The verifier rejects a committed corpus that differs from its deterministic generator.

## Acceptance

The shared project checker enforces nominal typing, ownership and borrow rules.
Protected entry tokens must match the starter after restoring `pipeline`.
An independent C11 driver computes expected running values and account state
using 64-bit arithmetic on a finite grid of 24 inputs. Generator bounds keep
all expected values within i32. The driver instruments actual exported helper
entries and checks exact order/count, running arguments and record field values,
plus the final return and all three final account fields. Private helper calls
are implementation details, not extra stages. These checks reject decorative,
skipped, repeated, reordered and wrong-state calls.

For each required stage, a separate native probe adds one to that helper's actual
return without changing its mutation. The oracle propagates that perturbed value
through later calls. Every probe must pass: executing a call while ignoring its
return and recomputing arithmetic inline fails acceptance.

Native candidate/compiler execution uses existing process time and resource
bounds and retained command receipts. The verifier and C toolchain are trusted;
this is finite task acceptance, not an OS sandbox or general correctness proof.

## Measurement plan

Use a pinned adapter/model selector/effort and record any unavailable provider
snapshot, tokenizer or dollar cost as unknown. An initial descriptive pilot can
run two tasks × two conditions × two repetitions, interleaved with a recorded
seed, with at most one repair each and sixteen total adapter invocations.
This invocation bound is not a dollar, token or subscription quota guarantee.

Retain requests/responses/candidates, original input identities, condition-level
correctness, repairs, input/output/cache-read usage and latency. Reverify final
candidates with matching trusted inputs before publishing. Preserve failures and
infrastructure errors in denominators. Public artifacts omit private local command
paths/process transcripts, recording normalization and exact original archive hashes.

Eight trials of related tasks cannot establish a reliable causal benefit, a
cross-language advantage, general model support or M1 completion. A ceiling
remains a ceiling. More representative tasks, statistical power, alternative
models and native focused/edit-tool experiments remain separate work.

## Validation and cost

Behavioral tests cover correct pipelines and invalid nominal types, order/count,
unexecuted calls, missing mutation propagation, immutable declarations, context
budgets, original-file diagnostics and fixture run/reverification. Existing corpora,
protocol and accounting tests retain their original defaults. Module sources use
`fmt --module --check`; documentation uses the normal link/Mermaid gate.

No runtime language feature or compiler optimization is added. Prompt overhead
and whole-project checking are measured costs rather than presumed savings.
