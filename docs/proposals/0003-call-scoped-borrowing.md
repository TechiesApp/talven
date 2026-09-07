# Proposal 0003: Call-scoped borrowing

- Status: Draft
- Author(s): Codex, implementing the project owner's request to continue Talven
- Requirements affected: R01, R03-R12, R15, R21 from [requirements.md](../requirements.md)
- Decisions affected: proposed D27 and D28 in [decisions.md](../decisions.md)
- Discussion: implementation pull request for `prototype/m1c-borrowing`, building on Proposal 0002

## Problem

M1a/M1b can move records but cannot pass them for reusable reads or modify their fields. Agents therefore cannot express an ordinary in-place record update. Adding mutation also makes evaluation order observable: C lowering must capture earlier scalar reads before later calls change their source.

## Proposal

Implement `m1c-call-borrows-v1`: named scalar-field records can be borrowed through direct call arguments, with shared read or exclusive read/write permissions. Allow `let mut` owned records and scalar-field assignment. Restrict borrowed types to parameters and prohibit stored or returned references. Explicit reborrows refer to a borrowed parameter's pointee.

The [borrowing guide](../borrowing.md) defines the exact grammar boundary, argument loan scopes, access rules, reborrowing, assignment order, diagnostics, checker assumptions, and native lowering. Nested calls retain enclosing loans and release only their own loans. No inference permits a shared borrow to become exclusive or a reference to escape.

Emit ordered native temporaries and ordinary pointers, with shared pointees qualified `const`. Extend the existing frontend used by CLI, LSP, and context. Publish `talven.context.v2` with checked borrow passing modes, call scopes, mutation permissions, and nonescape facts; increment the formatter profile for new borrow/mutation syntax. Keep the diagnostic envelope at v1.

## Examples

Implemented experimental syntax:

~~~text
struct Counter { value: i32 }
fn increment(c: &mut Counter) -> i32 {
    c.value = c.value + 1;
    return c.value;
}
fn main() -> i32 {
    let mut c = Counter { value: 1 };
    increment(&mut c);
    return c.value - 2;
}
~~~

The complete [borrowing example](../../examples/borrowing.tal) also forwards an exclusive borrow and returns to shared reads. The [invalid example](../../examples/invalid/borrow-conflict.tal) rejects overlapping read/write aliases.

## Alternatives considered

- Implement escaping references, lifetimes, reference fields, heap storage, and a complete borrow checker immediately. That substantially broadens the soundness obligations before this model has independent review or agent evidence.
- Copy records for all calls. This prevents persistent in-place updates and can disguise memory and transfer costs.
- Add raw pointers first. That exposes lifetime and alias obligations without checked contracts for agents.
- Add a dynamic borrow registry or reference-counted objects. These introduce runtime state and cost that this bounded, nonescaping subset does not require.
- Defer mutable loan activation until the callee starts. This accepts more argument patterns but adds reservation rules. The experiment uses simpler immediate loan activation and explicit scalar snapshots instead.
- Add borrow fields to context v1. Consumers that assume only copy/move could misinterpret contracts. A new schema makes the migration explicit.

## Costs and implications

- Agent context: parameter facts become richer and slightly larger, but explain borrow permissions without inspecting every callee body. Measure task-level cost before claiming fewer tokens or repair attempts.
- Runtime and memory: borrow checking is compile-time. Pointer passing and ordered temporaries can influence optimization and stack/register use; there is no measured zero-overhead or RAM-reduction result. No allocator or mandatory GC is introduced.
- Security: restrict aliases and reference lifetimes within checked Talven calls. Handwritten foreign callers, hostile generated-C edits, OS permissions, build provenance, firmware integrity, and GPU completion remain outside these guarantees.
- Targets: preserve C11 lowering and test actual Linux ARM64/x86-64 execution, including address/undefined-behavior sanitizers. Other operating systems, ABIs, boards, and GPU targets require separate evidence.
- Ecosystem and interoperability: no package adapter or safe foreign ABI. A future bridge must validate pointer ownership and lifetime; it cannot assume a call-scoped host borrow covers deferred foreign work.

## Evaluation

The [validation record](../borrowing-validation.md) covers accepted/rejected aliases, nonescape rules, nested reborrowing, moves, scalar-field mutation, source-order reads, short-circuit effects, formatter token preservation, and shared LSP/context contracts. Native fixtures execute at `-O0` and `-O2`, with UBSan in the suite and a separate required ASan/UBSan CI step.

Controlled agent tasks still need a pinned M1c guide, fresh v2 context, protected independent tests, and cost/success measurements across models. Passing compiler tests is not a model evaluation or a formal safety proof.

## Unresolved questions

Does immediate call scope produce understandable diagnostics at a reasonable repair cost? Which workload first requires field-sensitive or escaping borrows? What lifetime rules should heap objects, destructors, suspension, and foreign callbacks use? Can measured optimization or editor costs justify a more sophisticated IR or checker? Those extensions require new evidence and proposals.
