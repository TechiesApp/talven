# Experimental current call type contracts

Status: implemented opt-in reference experiment under [Proposal 0027](proposals/0027-current-call-type-contracts.md), Proposed D55. It refines caller invalidation in the [persistent frontend](development.md#persistent-function-checks); default full checking and default persistent dependency identities remain unchanged.

~~~sh
python3 -m talven dev examples/hello.tal --console \
  --incremental-check --call-type-contracts
~~~

The private API is `IncrementalFrontend(call_type_contracts=True)`. The option requires check reuse in the watcher, and cannot accompany native object reuse. Every source revision is still parsed afresh. Native C emission and compilation remain full. This adds no module resolver, object cache, state-preserving reload or target profile.

The current language validates positional direct calls against ordered parameter types, exact borrow qualifiers, parameter count and result type. These values form the selected callee dependency identity. Own function text remains exact, including parameter names, bindings and body. Record schema dependencies remain current. A callee parameter rename rechecks its changed definition while eligible callers reuse successful checks. Type/mode/arity/result changes and removed declarations invalidate affected callers. This rule would need revision before adding named/default arguments, new effect contracts or other call semantics.

References remain current: each reused call's definition span is mapped to the freshly parsed callee, and its displayed signature is rebuilt from that declaration. Context and editor descriptions therefore show new parameter names without retrieving them from old cache text. Expression types and call facts remain immutable last-successful facts; the returned analysis/AST/references are fresh. Invalid revisions return current first diagnostics and never replace the successful cache. Existing source/depth/compiler identity limits apply.

Session-start receipts expose `call_type_contracts`; checked events retain actual `checked`/`reused` lists. The [checking measurement runner](incremental-checking-baseline.md) accepts the same option, archives compiler/runner/workload/experiment/example inputs and verifies complete analysis, diagnostics, context and ordinary C against fresh checking. Untimed independent native oracles establish workload acceptance. Default measurement behavior stays unchanged.

Tests compare complete analyses through repeated parameter renames, Unicode source shifts, declaration movement, recursion, borrowed calls, record/type/mode/arity/result changes, missing callees, invalid/repair revisions and mutation of previously returned facts. All valid example/fixture trivia revisions are compared against full analysis. A real watcher verifies current program output, eligible caller work and rejection/repair; usage tests require explicit check mode. Correct reuse counts alone do not establish lower latency, memory or agent cost.

[Three paired local comparisons](call-contracts-evidence.md) retain current native-accepted workloads, exact complete analysis/context/C and 2,016 samples including warmups. Recheck counts improve for parameter renames; timings remain mixed and defaults remain unchanged.
