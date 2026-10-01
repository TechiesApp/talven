# Experimental local function contracts

Status: implemented opt-in reference experiment under [Proposal 0026](proposals/0026-local-function-contracts.md), Proposed D54. It refines function declarations in hosted units, keeping the shared language frontend and ordinary whole-program C unchanged. It adds no module resolver, foreign ABI or target support.

~~~sh
python3 -m talven emit-c-units examples/borrowing.tal --local-contracts
python3 -m talven prepare-c-units examples/borrowing.tal --local-contracts
python3 -m talven dev examples/hello.tal --console \
  --incremental-build --stable-toolchain --local-contracts
~~~

Each function unit declares itself and its current checked direct source callees, sorted by name. The generated entry unit declares only Talven main. Prototype parameters contain types and borrow qualifiers without parameter names; definitions retain named bindings. All current record/static-text layouts and required headers remain. A parameter rename changes its definition while a caller with unchanged types/body can retain identical expanded C. Unrelated function insertion or reordering can leave existing units eligible. A changed signature affects the definition and direct callers; changed record layouts conservatively affect every unit. This is current lowered dependency text, not reuse of stale checked facts or an ABI-only hash.

| Boundary | Default profile | Explicit local profile |
| --- | --- | --- |
| [C unit emission](c-units.md) | `hosted-c11-units-v1` | `hosted-c11-local-contracts-v1` |
| [Fresh preparation](preprocessed-units.md) | `hosted-preprocessed-units-v1` | `hosted-preprocessed-local-contracts-v1` |
| [Private object build](object-reuse.md) | `hosted-object-reuse-v1` | `hosted-object-local-contracts-v1` |

The existing bounded receipt schemas remain. The selected build profile participates in cache configuration; changing profiles forces object misses. The private API accepts `UnitBuildSession(stable_toolchain=True, local_contracts=True)`. The watcher flag requires both native-mode flags and cannot be combined with check reuse. Session events record `local_contracts`; completed native receipts record `profile` and actual compiled/reused IDs.

Preparation still fully checks current source and freshly preprocesses headers/layouts once. Local prototypes appear inside each function segment before its definition/helpers. Own line markers are normalized only after expansion; system-header markers remain. Every valid build verifies eligible private objects and freshly links all current units. Stable-toolchain obligations, resource bounds, cancellation, last-successful retention and deployment freshness follow the existing preparation/object/watcher contracts. Source parameter names remain available to context, language checks and editor signatures.

Eight focused tests check strict native units, forward calls/recursion, parameter/type/declaration edits, global layouts, fresh prepared bytes, actual reused objects against independent integer oracles, invalid-edit repair, profile separation and raw/reused borrow sanitizers at both optimization levels. A real native watcher test checks current output and changed/reused decisions through invalid edits and repair. Both measurement runners verify the selected profile and native acceptance. Linux CI requires all native tests without skips; local host evidence does not expand supported targets.

The [object rebuild](object-rebuild-baseline.md) and [actual watcher](native-watch-baseline.md) runners accept `--local-contracts` for the unit condition; their ordinary full-build control remains unchanged. Lower invalidation counts alone do not establish lower latency, memory, agent cost or a better default. Retain all comparative observations and native acceptance before making performance claims. State-preserving reload, record dependency refinement and cross-session cache reuse remain open.

[Three same-checkout paired comparisons](local-contracts-evidence.md) retain actual native acceptance and reduced parameter-rename invalidation, with mixed cold/other edit costs. Existing defaults remain unchanged.
