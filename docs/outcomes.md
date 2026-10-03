# Concrete typed outcomes

Profile: `m2-concrete-outcomes-v1`, selected explicitly with `--outcomes`.
This companion experiment adds ordinary typed error alternatives to the
[M1 core](language-reference.md). [Proposal 0040](proposals/0040-concrete-typed-outcomes.md)
records design, costs, tool boundaries and verification. It introduces no allocator,
exception unwinding or concurrent resource lifetime support.

## Grammar and ownership

~~~ebnf
outcome     = "outcome", identifier, "{", variant, { ",", variant }, [","], "}" ;
variant     = identifier, [ "(", payload_type, ")" ] ;
payload_type = "i32" | "bool" | owned_record_name ;
constructor = outcome_name, "::", variant_name, [ "(", expression, ")" ] ;
match       = "match", "(", expression, ")", "{", { arm }, "}" ;
arm         = outcome_name, "::", variant_name, [ "(", binding_name, ")" ], block ;
~~~

An outcome name is a nominal owned type usable in parameters, locals and returns.
`outcome` and `match` are reserved only in this profile. All M1 rules and input
bounds continue to apply. An outcome declares at least one unique variant;
payloads are optional concrete scalars or owned scalar-field records. Payload
types may name records declared later. Nested sums, `str`, references and generics
are excluded.

~~~text
outcome Lookup { Found(i32), Missing }

fn handle(result: Lookup) -> i32 {
    match (result) {
        Lookup::Found(value) { return value; }
        Lookup::Missing { return 0; }
    }
}
~~~

Construct with `Lookup::Found(42)` or `Lookup::Missing`. Payload presence and type
must match the variant. Constructors of distinct outcome types never convert
implicitly. `match` consumes its scrutinee, including scalar-payload outcomes,
and handles every variant exactly once. Arm order is arbitrary. Bind exactly one
payload name for a payload variant and none for a unit variant. It is visible only
inside that arm. Record payloads transfer once; scalars copy. A consumed outcome
and a moved record payload cannot be reused. There is no direct payload field
access, wildcard arm, borrowed match, propagation shorthand or outcome mutation.

Every outcome must be matched, returned or transferred to an owning parameter
before its scope exits or a function returns. Ignoring an expression result, local
or parameter is E0311. Continuing branches must agree on consumption of every
outer outcome; an optionally evaluated `&&`/`||` argument cannot be its only
handling path. Records retain their existing conservative move rules. Outcomes
cannot be borrowed, assigned or declared `let mut`.

Variant/declaration/arm errors use E0310; type and move failures retain E0201 and
E0301. Arithmetic failures continue to trap, and no cleanup/unwind guarantee is
added. Emitted C checks the tag before reading the selected union member and traps
on an invalid tag. Outcome layout is experimental and not a stable C export ABI.

## Commands and editor contract

~~~sh
python3 -m talven check examples/outcomes/decision.tal --outcomes --json
python3 -m talven fmt examples/outcomes/decision.tal --outcomes --check
python3 -m talven context examples/outcomes/decision.tal --outcomes
python3 -m talven emit-c examples/outcomes/decision.tal --outcomes
python3 -m talven build examples/outcomes/decision.tal --outcomes -o build/decision
./build/decision

experiments/native-compiler/target/release/talven-native check examples/outcomes/decision.tal --outcomes --json
experiments/native-compiler/target/release/talven-native fmt examples/outcomes/decision.tal --outcomes --check
experiments/native-compiler/target/release/talven-native emit-c examples/outcomes/decision.tal --outcomes
~~~

The first-error reference checker is shared by these commands and LSP custom
request `talven/outcomeContext`, with parameters `source`, optional `maxBytes`
(default 16384, maximum 1048576) and optional `expectSourceHash`. It returns the
same checked `talven.outcome-context.v1` object as CLI context, including source
and compiler hashes, alternatives/tags and function transfer contracts. No source
is loaded from a URI, and no code is executed. A stale hash or too-small budget
fails rather than returning partial facts. Whole-program context does not accept
ordinary `--compact`, `--symbol`, `--include-body` or `--freestanding` options.

Normal commands and standard LSP document operations retain the base grammar.
Modules, C exports, edit previews, test manifests, incremental/watch/hot reload,
Rust outcome context and freestanding outcome execution remain separate work.
`fmt --module --outcomes` is rejected. Syntax-only formatter success does not
establish ownership or task correctness.

The [example](../examples/outcomes/decision.tal) exercises record, integer, boolean
and unit alternatives. Independent reference/native C drivers verify variant
values and invalid-tag trapping with sanitizers at both O0/O2; CI requires actual
Linux x86-64/ARM64 hosts. No live-agent or performance benefit is claimed for this
new profile.
