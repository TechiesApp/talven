# Proposal 0001: M1a reference compiler and agent interface

- Status: Draft
- Author(s): Codex, implementing the project owner's request to begin the next stage
- Requirements affected: R01-R12, R15-R16, R21-R23 from [requirements.md](../requirements.md), with partial evidence only
- Decisions affected: proposed D22, D23, D24 in [decisions.md](../decisions.md)
- Discussion: accompanying implementation pull request for branch `prototype/m1a-compiler`

## Problem

Talven's design baseline cannot yet test its central claim: that a precise shared semantic model helps humans and coding agents change native programs correctly. Starting with the whole ownership, concurrency, GPU, and foreign-runtime design would make it difficult to isolate why an experiment succeeds or fails.

## Proposal

Introduce the experimental profile `m1a-owned-values-v1`: strict `i32`/`bool` values, immutable locals, functions, conditionals, affine scalar-field records, checked arithmetic, and one source file per compilation.

Use one Python standard-library frontend for command-line checking, deterministic bounded context, and a small stdio LSP. Emit inspectable C11 for native execution, with an optional freestanding translation-unit profile. Record the exact grammar, input limits, diagnostics, evaluation order, and move behavior in the [prototype guide](../prototype.md).

Keep this as a reference experiment. The production compiler language, final syntax, backend, ABI, allocator, and borrowed-reference design remain open. Do not report full M1 completion from this increment.

## Examples

The following example compiles in the M1a implementation. It is experimental syntax, not a finalized language specification.

~~~text
struct Item { value: i32 }
fn read(item: Item) -> i32 { return item.value; }
fn main() -> i32 {
    let item = Item { value: 0 };
    return read(item);
}
~~~

Moving `item` into another binding and then reading the old binding is rejected with `E0301`. Passing a boolean where an integer is required produces `E0201`. `context --symbol read` exposes the checked signature, move passing convention, relevant record schema, and versioned input identities. Optional original source is explicitly marked untrusted data.

## Alternatives considered

- Build the production compiler in Rust immediately. This remains plausible, but a small reference implementation first makes semantic and agent-interface experiments cheap and independently inspectable. Python has greater compiler startup and memory overhead; that cost must be measured before choosing the production implementation.
- Integrate LLVM directly. It offers native target support and optimization infrastructure but adds integration work before the language rules are exercised. C11 adds a second compiler stage and limits control over low-level lowering; it is an experiment, not a commitment to a permanent backend.
- Begin with a full borrow checker and heap containers. These remain necessary later; scalar-field affine values first establish move diagnostics and path reasoning without pretending to solve resource destruction or escaping references.
- Build an independent editor parser. Sharing the frontend makes CLI, agent context, and editor diagnostics agree by construction for this subset.

## Costs and implications

- Agent context: compact checked contracts, explicit byte budgets, source/compiler/profile/target/query identities, and first-error diagnostics. Bytes are not model tokens. No provider-specific cache feature is required.
- Runtime and memory: native C11 output, stack-value records, checked integer operations, and hosted C startup/traps. Logical moves may still copy record representations. Python is required for compiler tooling, not generated program execution.
- Security: analysis and LSP do not run packages, build scripts, or source programs. Native building invokes a separately trusted local C compiler. Hashes identify inputs without authenticating them. Process isolation, protected policy, signed updates, and hardware integrity remain outside this prototype.
- Targets: Linux x86-64 execution is tested. Freestanding object generation is tested for one example. ARM64 execution, boards, and other OS/ABI profiles still need evidence.
- Ecosystem and interoperability: no package adapter or foreign runtime is included. Emitted C symbol names are an experimental test interface, not a stable public ABI.

## Evaluation

The [validation record](../prototype-validation.md) records 39 passing local tests, including negative ownership/type cases, context invalidation, LSP framing/Unicode/version behavior, native scalar conformance with sanitization, arithmetic traps at two optimization levels, and a freestanding object experiment.

The [initial agent task corpus](../../experiments/README.md) specifies bounded repair and API-change tasks with independent verification. No model comparison or token-saving result is claimed. Completing M1 still requires ARM64 runs, a defined borrowing subset, a formatter, and controlled agent evaluation.

## Unresolved questions

Should the production compiler use Rust and a direct native backend? Which borrowing rules produce useful diagnostics with a compact language guide? How should a canonical formatter preserve comments? What editor/context latency and task cost do representative models achieve? Which protected runner will enforce task edit scopes and safe tool execution? Those questions require further evidence and proposals.
