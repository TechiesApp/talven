# Proposal 0015: Mutable scalar locals

- Status: Draft; implemented experiment in compiler `0.5.0-dev`
- Author(s): Talven contributors
- Requirements affected: R01, R02, R07, R08, R10, R24
- Decisions affected: D43 (proposed)
- Discussion: the pull request introducing this proposal and implementation

## Problem

The [large-program pilot](../pilot-evidence.md#fifth-run-the-large-program-corpus) found scalar reassignment in 38 of 64 first-attempt failures. Agents routinely express a running result as a mutable local. Rejecting that familiar operation adds repair work even when it introduces no aliases or ownership transfers. Humans face the same friction when updating integers or booleans across branches.

## Proposal

Allow initialized `let mut` locals of `i32` and `bool`, alongside the existing mutable record owners. A statement `name = expression;` requires a mutable scalar local and exactly its original type. Parentheses around the destination are transparent. Evaluate the entire value before the store. Arithmetic checks and source-order evaluation remain unchanged.

Parameters remain immutable. A scalar parameter can be copied into a mutable local. Copying a mutable local into a plain `let` does not copy mutation permission. Names still cannot be shadowed; branch declarations do not escape their branch, but writes to outer locals persist when execution continues.

Whole-record and `str` reassignment, mutable `str` bindings, assignment expressions, chained or compound assignment, uninitialized locals, scalar borrows, loops, and mutable parameters remain unsupported. Record moves and call-scoped loans retain their rules; assigning a record cannot revive a moved owner.

Use reference profile `m1-scalar-mutation-v1`, formatter profile `m1-scalar-mutation-layout-v1`, and native profile `native-scalar-mutation-v1`. Existing JSON shapes retain their schema versions; profile identities and compiler hashes invalidate older semantic context. The Rust experiment supports mutable local declarations, including record owners used only by value, and scalar assignment. Record borrowing and field assignment retain its explicit `E0801` boundary.

## Examples

The experiment implements this example; the [language reference](../language-reference.md) is normative:

~~~text
fn adjusted(input: i32, increase: bool) -> i32 {
    let mut result = input;
    if (increase) {
        result = result + 2;
    } else {
        result = result - 2;
    }
    return result;
}
~~~

`let x = 1; x = 2;` is `E0303`; `let mut x = 1; x = false;` is `E0201`. Unsupported binding types and destination expressions are `E0305`; unknown names are `E0101`. A moved record destination remains `E0301`.

## Alternatives considered

- Keep scalars immutable: preserves the older subset but retains the observed source of repairs.
- Permit shadowing: makes linear rewrites convenient but does not directly represent updates to an outer local from a branch and changes name resolution.
- Add general reassignment, mutable text, or mutable parameters: broadens the language beyond the measured problem and needs separate ownership decisions.
- Add compound assignment and loops now: useful follow-ups, but unnecessary to establish the basic store contract.

## Costs and implications

- Agent context: a short mutation rule replaces the scalar prohibition. Editor references include assignment destinations. Historical pilots remain evidence for their recorded compiler, not the new profile.
- Runtime and memory: ordinary C locals and stores, with existing checked helpers and temporaries. No allocator, loan registry, or tracing collector is added. Optimizers may eliminate stores; no speedup or cost reduction is claimed.
- Security: no new capability or foreign boundary. Compiler checks remain independent of process and release authorization.
- Targets: reuse existing C11 lowering and declared native hosts; successful local execution does not establish other targets.
- Ecosystem and interoperability: no ABI change or package integration.

## Evaluation

Check accepted integer/boolean writes, branch persistence, immutable copies and parameters, type mismatches, unknown/out-of-scope destinations, unsupported text/record writes, and move rejection. Execute both branch outcomes at `-O0` and `-O2`, check overflow traps and borrowed helper order, and retain sanitizer checks.

Verify formatter token preservation, context rules, editor hover/definition/references/rename, and edit-preview acceptance. The differential suite compares both compilers' diagnostics and exact C and executes 64 additional seeded mutation programs against an independent evaluator. CI must run on Linux x86-64 and ARM64. A later explicitly budgeted pilot should test whether the observed repair cost falls; implementation tests alone do not establish model effectiveness.

## Unresolved questions

Loops, compound assignment, mutable text, record replacement, and mutable parameters need separate evidence and proposals. Design acceptance remains separate from this experimental implementation. Repeated live evaluations and cross-language task baselines remain open.
