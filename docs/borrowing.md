# M1c call-scoped borrowing

Status: implemented experiment, compiler `0.3.0-dev`, language profile `m1c-call-borrows-v1`, formatter `m1c-layout-v1`, and context schema `talven.context.v2`. [Proposal 0003](proposals/0003-call-scoped-borrowing.md) remains Draft. This adds a bounded borrowing model to M1a/M1b; full M1 still needs controlled agent evaluation.

## Read and update a record

The following is implemented syntax:

~~~text
struct Counter { value: i32 }

fn read(c: &Counter) -> i32 {
    return c.value;
}

fn add(c: &mut Counter, amount: i32) -> i32 {
    c.value = c.value + amount;
    return c.value;
}

fn main() -> i32 {
    let mut counter = Counter { value: 40 };
    add(&mut counter, 2);
    return read(&counter) - 42;
}
~~~

`&Counter` grants shared read access for a call. `&mut Counter` grants exclusive read/write access. `let mut` makes an owned record's scalar fields writable. Plain `let` and by-value parameters stay immutable. To mutate an owned parameter, move it into a `let mut` local. Moving a mutable owner into a plain `let` does not preserve its write permission.

The shared/exclusive distinction uses familiar terminology from systems languages, including [Rust's borrow operators](https://doc.rust-lang.org/reference/expressions/operator-expr.html#borrow-operators). Talven implements its own restricted rules below, with no Rust lifetime, trait, ABI, or interoperability compatibility claim.

## Exact supported boundary

| Operation | M1c rule |
| --- | --- |
| Borrowed type | `&Record` or `&mut Record` on a function parameter only |
| Creating a borrow | Direct call argument `&name` or `&mut name`; parentheses around the name are harmless |
| Borrowed place | A named owned record or an existing borrowed parameter's pointee |
| Shared access | Multiple shared borrows and scalar reads may overlap |
| Exclusive access | One exclusive borrow; no overlapping reads, writes, moves, or other borrows of that record |
| Field assignment | `name.field = expression;` through a mutable owner or exclusive parameter; field type must match |
| Loan end | When the call receiving that borrow returns |
| Reborrowing | Explicit `read(&parameter)` or `add(&mut parameter, 1)`; cannot upgrade a shared parameter |
| Stored or returned reference | Rejected, including local reference bindings and reference fields in records |
| Unsupported places | Scalars, field-only borrows, record temporaries, nested references, and assignment through temporary records |

Records still contain only `i32` and `bool` fields. There is no general binding reassignment, dereference operator, pointer arithmetic, nullable reference, heap allocator, destructor, closure, global mutable value, FFI, async operation, or thread in this profile. `let mut` on a scalar is deliberately rejected until broader variable mutation is specified.

Passing a borrowed parameter requires an explicit new borrow expression. `read(parameter)` is rejected; `read(&parameter)` borrows the same underlying record. `&mut` to `&` conversion is not implicit: spell the desired shared borrow at the call. Bare references cannot become owned records.

## Argument evaluation and loan scope

Operands, call arguments, and record initializers evaluate left to right in their written order. Each loan starts when its argument is evaluated, remains active while later arguments are evaluated, and ends after the callee returns. A nested call releases its own loans while retaining loans held by earlier arguments of an enclosing call.

| Example | Result and reason |
| --- | --- |
| `both(&item, &item)` | Allowed when both parameters are shared |
| `write_and_read(&mut item, &item)` | Rejected: shared access overlaps an exclusive loan |
| `with_value(&mut item, item.value)` | Rejected: the later read overlaps the earlier exclusive loan |
| `with_value(&item, update(&mut item))` | Rejected: the nested mutation overlaps the outer shared loan |
| `combine(item.value, update(&mut item))` | Allowed for scalar parameters; the first read captures the old value |
| `combine(update(&mut item), update(&mut item))` | Allowed for scalar parameters; the first nested call finishes before the second starts |

Names in this table describe parameter shapes; see the [executable ordering fixture](../tests/fixtures/borrowing-order.tal) for complete functions. In a rejected read/update combination, taking a scalar snapshot in a preceding `let` can make the intended order explicit. This is conservative call scope, with no implicit reservation phase or inferred early loan termination.

Assignment evaluates its right-hand side before the final field store. `item.value = update(&mut item) + 1;` is allowed when `item` is mutable. An assignment whose right-hand side moves `item` is rejected; the store cannot revive a moved owner. Moves on continuing branches and potentially evaluated short-circuit operands retain M1a's conservative rules.

## Checker and lowering invariants

1. Owned records have no reference fields or hidden aliases. Logical moves invalidate the old binding on every possible continuing path.
2. Borrowed parameters originate from checked Talven calls. Incoming exclusive pointees are disjoint from every other incoming pointee; shared parameters may alias each other.
3. Every nested call checks access against active loans. A shared reference cannot create write permission, and an exclusive reference is temporarily unavailable through competing arguments while reborrowed.
4. References cannot be stored or returned, so a callee cannot keep a pointer after its call or expose a pointer to a dead local. This argument relies on the restricted syntax and checked callers; it is not a formal soundness proof.

The C backend passes addresses of records, with `const` for shared pointees, and emits explicit temporaries and separate statements for scalar reads and calls. This preserves Talven's order even where [C expression order is only partially specified](https://gcc.gnu.org/onlinedocs/gcc/Warning-Options.html). It does not rely on C argument order or emit `restrict` alias promises. C `const` alone does not enforce Talven's exclusivity rules.

Borrow enforcement adds compiler analysis but no runtime loan registry, reference counting, tracing GC, or language-level heap allocation. Address passing and temporary values can affect register use, optimization, stack space, and alias analysis. Optimizers may remove copies, but zero overhead, zero copying, RAM savings, and competitive throughput have not been measured. Recursion can still exhaust the stack.

## Agent context and editor migration

M1c increments the context schema because parameters now have four passing modes: `copy`, `move`, `borrow-shared`, and `borrow-exclusive`. Borrowed parameters additionally include:

~~~json
{"name":"c","type":"&mut Counter","passing":"borrow-exclusive","scope":"call","may_write":true,"escapes":false}
~~~

`may_write` means permission to mutate, not proof that the function actually writes or a complete effect analysis. `escapes:false` describes this checked profile's nonescaping reference rule. Relevant record schemas and direct callee contracts accompany selected functions, including records used through borrowed types. The rules also describe loan scope and assignment order.

Consumers must recognize `talven.context.v2` and the new passing modes before editing M1c code. A v1-only consumer should reject v2, refresh its pinned language guide, and request new context. Schema, language profile, formatter profile, exact source, compiler modules, and bootstrap runtime already contribute to cache identity. These hashes identify inputs; they do not authenticate external cache contents. Diagnostic envelopes remain `talven.diagnostics.v1`.

The shared LSP frontend reports borrow failures and shows shared/exclusive parameter permissions in hover. Field reads and assignment targets resolve to their field declarations. The formatter preserves borrow tokens, including separating invalid `& &name` tokens so they never become `&&`. `mut` is now reserved; an older program using it as an identifier must rename that identifier. Current open/proprietary models can use ordinary text and JSON; no comparative agent result or provider-cache improvement is claimed.

## Diagnostics

| Code | Meaning |
| --- | --- |
| E0301 | Use, borrow, or destination store after a possible move |
| E0302 | Conflict with an earlier argument's active loan |
| E0303 | Mutation or exclusive borrowing without write permission |
| E0304 | Escaping/stored reference, unsupported borrowed type position, or missing explicit reborrow |
| E0305 | Unsupported borrowed place/type or mutable binding/assignment target |
| E0201 | Exact field or argument type mismatch, including borrow mode |
| E0204 | Unsupported record field type, including reference fields |

The compiler reports the first error, so malformed combinations can fail earlier with syntax or name diagnostics.

## Security and target limits

These checks concern a single checked Talven program and its sequential native lowering. Handwritten C callers, edited generated C, compiler bugs, or an incompatible toolchain can violate the assumptions. A future safe foreign interface needs its own validation and ownership contract; generated C symbols are not that interface.

The compiler does not enforce filesystem, network, release, or agent permissions, authenticate firmware, contain a compromised OS, or prevent physical memory corruption. Those need independently enforced OS/runtime/hardware controls. GPU work may outlive a host call, so these call-scoped references must not be treated as a GPU buffer-lifetime contract. Async suspension and concurrent access remain separate future designs.

See the [validation record](borrowing-validation.md) for actual Linux x86-64/ARM64 execution and sanitizer results. Neither these tests nor address/undefined-behavior sanitizers prove general memory safety or all-target portability.
