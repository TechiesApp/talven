# Proposal 0040: Bounded concrete typed outcomes

- Status: Implemented experiment; companion profile `m2-concrete-outcomes-v1`
- Requirements: R01, R08, R10, R11, R16, R24, R25
- Decisions: D68 (proposed), D67, D06, D07, D27

## Problem and boundary

[Proposal 0039](0039-typed-failures-resource-contracts.md) requires typed failures
before allocating resources. A small nominal tagged value establishes explicit
error paths and ownership transfer without choosing an allocator or an executor.
The [outcome reference](../outcomes.md) specifies the implemented grammar and tools.
The ordinary [M1 reference](../language-reference.md) stays unchanged.

The explicitly selected profile adds `outcome` declarations, qualified constructors,
and exhaustive consuming `match` statements. Each variant has zero or one concrete
payload: `i32`, `bool`, or an existing owned scalar record. Declarations are nominal;
matching shapes do not permit conversions. Nested outcomes, reference/static-text
payloads, generics, borrowed matches, wildcard arms, propagation shorthand, outcome
mutation and user cleanup remain excluded.

## Chosen syntax and checking

~~~text
outcome ReadResult { Value(i32), Missing }

fn read(flag: bool) -> ReadResult {
    if (flag) { return ReadResult::Value(42); }
    return ReadResult::Missing;
}

fn use(result: ReadResult) -> i32 {
    match (result) {
        ReadResult::Value(value) { return value; }
        ReadResult::Missing { return 0; }
    }
}
~~~

An outcome moves even when its chosen payload is scalar. Construction transfers
an owned record payload once. Matching evaluates its scrutinee once, consumes it,
checks its tag, then introduces the selected payload binding in that arm's scope.
Scalar payloads copy; record payloads move. Each declared variant appears exactly
once, in any arm order. A payload variant requires one binding and a unit variant
requires none. Binding shadowing follows the existing prohibition.

Must-handle enforcement includes parameters and retained locals. On every returning
path each owned outcome must have been matched, returned or transferred to an
owning parameter. Newly declared outcomes cannot fall out of a block unhandled.
Expression-statement outcome results are rejected. Transfer to a callee delegates
the obligation to that callee's independently checked body.

The M1 conservative union of possible record moves remains unchanged. Outcomes
add a stronger constraint: every continuing branch must agree whether an outer
outcome has been consumed. Returning branches are checked before exclusion from
the join. The optional right side of `&&`/`||` is a continuing branch too; consuming
an existing outcome only there is rejected even if a literal condition could be
constant folded. No whole-outcome reassignment or borrowing is permitted.

E0310 covers invalid alternatives, unsupported payloads and non-exhaustive matches.
E0311 covers ignored outcomes and inconsistent continuing obligations. Existing
type, duplicate-name, move, borrow, unreachable-code and source-limit diagnostics
retain their roles. The companion checker reports the first error; multi-error
recovery remains limited to the ordinary profile.

## Layout, costs and trap boundary

Each outcome lowers to one C11 struct containing a `uint32_t` tag followed by a
union of its payload alternatives. Tags are declaration-order ordinals starting
at zero. An all-unit outcome uses one unused byte in its union to satisfy C11.
Existing record definitions precede outcomes, so forward-named record payloads
have complete layouts before union emission. Target C alignment/padding controls
the total size; source order and variant payload types are layout contracts.

Construction assigns a tag and its selected payload. A match emits a switch and
extracts a payload only inside the corresponding checked case. A default case
calls the existing nonreturning trap for a corrupt/foreign tag. There is no heap,
reference-count registry, unwind table, implicit allocator or dynamic tag registry.
By-value C copies implement checked source moves; logical old bindings are unusable.
No stable public outcome C ABI or permission to forge values is introduced.

Existing checked arithmetic still traps. These ordinary variants do not intercept
overflow, process traps, foreign exceptions or cancellation. Domain failures must
be returned explicitly. Resource cleanup and destructor elaboration are separate.

## Tools and deterministic contracts

Python CLI `check`, `fmt`, `context`, `emit-c` and `build` accept `--outcomes`.
The shared bounded Parser/Checker checks CLI and LSP `talven/outcomeContext`
requests; editor requests supply exact in-memory source and optionally its expected
hash. `talven.outcome-context.v1` records the selected profile, exact source/compiler
hashes, nominal names, declaration-order alternatives/tags, payload types, function
passing contracts and must-handle rules. It is whole-program frontend evidence,
bounded by the caller's byte limit, not execution evidence. Exact source remains
authoritative. Ordinary context, edit, project, watch/reuse, test-manifest and C API
commands do not select this grammar. Standard LSP document operations remain M1.

Rust independently parses/checks original outcome source and emits hosted C11 via
`check`/`emit-c --outcomes`; syntax-only `fmt --outcomes` has reference parity. Rust
outcome context/navigation, module composition, freestanding outcome execution,
incremental contracts and live-resource reload are not part of this slice. No
agent cost improvement or outcome compilation/runtime performance is measured.
Changing outcome alternatives invalidates exact source identities and requires
a fresh check/build; no reuse under a previous layout is claimed.

Source and lexer limits remain 256 KiB/16384 tokens, with AST depth 128 and active
block/expression parse depth 256. Match-arm bodies participate in both limits.
The lexer reserves `outcome`/`match` only under the explicit profile, preserving
ordinary M1 functions/parameters using those identifiers. Formatting preserves
tokens and inert comments and does not establish type or must-handle correctness.

## Verification

`tests/test_outcomes.py` covers declaration/constructor/arm failures, nominal
identity, ignored parameters/locals/results, scope exit, short-circuit paths,
borrow/mutation rejection, record payload moves, consuming scrutinees, continuing
joins, canonical syntax-only formatting, bounded/fresh context and the shared LSP.
Independent C drivers check all four example variants and tag/payload values on
eight inputs including `INT32_MIN`/`INT32_MAX`, at O0/O2 with ASan/UBSan. A separate
foreign C caller passes an invalid tag and requires trapping without sanitizer
reports or inactive payload extraction.

`experiments/native-compiler/tests/outcomes.py` requires independently checked Rust
diagnostics to match reference codes/messages/UTF-16 ranges, and exact C/layout and
formatter parity. It separately executes native-produced C through the same
independent drivers at O0/O2 with ASan/UBSan. Required Linux x86-64/ARM64 CI runs
these checks on the declared hosts; a merge or a local macOS run is not substitute
evidence for their results.

## Alternatives and next increment

A nullable record would not express multiple nominal failure alternatives and
would invite unchecked extraction. Exceptions would require unwinding/cleanup
contracts. Generic `Result<T,E>` would expand the type and layout model before a
concrete error path needs it. Nonconsuming matches would add reference lifetimes.
Defer these extensions until a separately verified workload requires them.

The [supplied-storage region draft](0041-supplied-storage-regions.md) specifies a
candidate sequential allocation experiment, including the
allocator lifetime representation, checked capacity/alignment, explicit release,
and independent fault-injection/live-owner accounting from Proposal 0039. This
typed-value slice begins M2 implementation; it does not pass the resource-lifetime,
cancellation or concurrency milestone gates.
