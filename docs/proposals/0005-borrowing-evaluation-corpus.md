# Proposal 0005: Borrowing evaluation corpus

- Status: Draft
- Author(s): Talven contributors
- Requirements affected: R01, R02, R04, R05, R06
- Decisions affected: D01, D03, D27, D28, D29, new D30
- Discussion: Pull request introducing this proposal

## Problem

The first executable evaluation corpus covers moves, strict types, and vector edits. It does not directly test repairs involving M1c loans, write permissions, explicit reborrowing, or ordered mutation. Adding tasks to its existing version would change the experiment's denominator without changing its identity.

## Proposal

Keep `m1c-agent-tasks-v1` as the default with unchanged tasks and acceptance. Add separately selected `m1c-borrowing-tasks-v1`, containing four bounded repairs:

1. End a shared read before starting an exclusive call by saving its scalar result.
2. Grant the required write permission to a borrowed parameter and its caller's owner.
3. Spell explicit shared/exclusive reborrows through an existing borrowed parameter.
4. Preserve a read followed by two ordered mutations and retain each returned value.

The first three starters fail with E0302, E0303, and E0304 respectively. The fourth type-checks but computes the wrong result, allowing compiler-context trials to exercise valid context v2 as well as invalid-source diagnostics.

Keep helpers and main's example checks fixed apart from the permission repair. Compare their tokens, allowing comments and formatting. Require a bounded straight-line `exercise` body with scalar bindings/calls and a final return; exclude record reconstruction, direct field writes, branches, and added functions. Publish these constraints in the task instructions. This is a focused repair corpus, not an open-ended programming benchmark.

Independent acceptance uses the shared compiler, structural constraints, and two native builds. The first compares returned i32 values and the original record after mutation on varied inputs. The second observes helper calls and pointee identity and varies individual helper return values without changing their writes. Expected results come from reviewer-owned calculations, separate from the starters and scripted solutions. The variation checks that required call results affect the answer; observing calls alone would permit decorative work followed by a reconstructed result.

Add `--corpus` to task listing and runs. Pin selected sources and the current trusted compiler/harness. Identify the corpus in requests, archives, reports, and reverification. Reject task IDs outside the selected corpus before any adapter invocation. Existing reports remain readable. Exact historical reverification requires a matching trusted checkout; hashes are not weakened and archived code is never executed as authority.

## Examples

The [experiment guide](../../experiments/README.md) documents both selectable corpora and their offline adapters. Each borrowing trial starts with the original source and an empty conversation in either source-only or compiler-context mode. A dedicated hand-written fixture submits the unchanged starter, then a valid repair. It reports no model usage or billing.

## Alternatives considered

- Appending tasks to v1 would silently change its meaning; a separate version preserves comparability.
- Compilation and final answers alone miss the required ownership and ordering work. Structural, mutation, and return-sensitivity checks address those specific gaps.
- Requiring one exact repaired source would overconstrain local names and expressions. Only protected helpers/main are token-fixed; the editable function is checked behaviorally within its stated boundary.
- Running a paid provider now would combine corpus validation with a new integration and budget decision. This increment stays offline.

## Costs and implications

- Agent context: longer task constraints and borrowing programs, using the existing byte budget; no token-cost claim without provider measurements.
- Runtime and memory: two native builds per accepted borrowing candidate, bounded commands, trace state, and additional artifacts. No language runtime or compiler semantics change.
- Security: the existing trusted adapter/compiler/host boundary remains. Public finite tests are neither secret nor a sandbox, and do not prevent deliberate overfitting.
- Targets and interoperability: actual Linux ARM64/x86-64 checks are required; generated C signatures remain internal prototype test interfaces.

## Evaluation

Check starter diagnostics, valid repairs, changed helper/main contracts, hardcoded results, copied/directly written records, decorative calls, compensated late reads, and unused helper returns. Exercise both context modes through run/report/reverify, mismatched corpus/task metadata, and original-corpus compatibility. Run the full existing tests without skips, sanitizers, examples, formatting, and documentation checks. Record only actual outcomes in the [validation record](../borrowing-evaluation-validation.md).

## Unresolved questions

Provider adapters, approved-budget live trials, statistical sample sizes, larger task variation, and cross-language equivalents remain later experiments. Offline success does not establish model effectiveness or complete M1.
