# Bounded local modules

Status: implemented reference experiment under [Proposal 0037](proposals/0037-bounded-local-modules.md), explicitly selected as `m1-local-modules-v1`. Expressions, records and borrowing follow the [base language](language-reference.md). Normal single-file commands keep their existing profile.

## Source interfaces

~~~text
import "counter.tal" { Counter as Account, add as increment };

fn main() -> i32 {
    let mut account = Account { value: 35 };
    return increment(&mut account, 3) - 40;
}
~~~

`counter.tal` declares `pub struct Counter` and `pub fn add(counter: &mut Counter, amount: i32) -> i32`. Other declarations are private. Paths refer to the explicit root, including for importers in subdirectories. Imports come first and select directly exported names; aliases and trailing commas are optional. No implicit transitive names, wildcards, reexports or cycles are accepted.

The checker preserves record identities through aliases and the current copy/move/borrow rules. A public signature cannot expose an owned private record. Imported public types keep their defining identities; consumers import those types explicitly. Unrelated private helpers with identical names do not collide.

## Check, inspect and build

Run the implemented [example](../examples/modules/main.tal) from the repository root:

~~~sh
python3 -m talven project check main.tal --root examples/modules --json
python3 -m talven project context main.tal --root examples/modules --symbol main.tal::calculate --include-body
python3 -m talven project emit-c main.tal --root examples/modules -o build/modules.c
python3 -m talven project build main.tal --root examples/modules -o build/modules
./build/modules
python3 -m talven fmt examples/modules/main.tal --module --check
~~~

`check`/`context` invoke no external compilation/execution. `emit-c` emits one checked C unit. `build` invokes trusted `--cc` (default `cc`) and publishes only after successful compilation and closure rereads. Console use anywhere requires `--console`. These commands check/rebuild the whole closure and provide no object reuse/hot reload. They forbid overwriting captured source, including hardlink aliases. Existing outputs survive compiler/freshness failures.

Paths are canonical ASCII `.tal` paths of at most 128 bytes, with letter/digit/underscore/hyphen components separated by `/`. Absolute paths, `.`/`..`, empty components, backslashes and symlink traversal fail. The closure allows 32 modules, 16 import levels, 256 KiB aggregate original UTF-8 source and 16384 tokens. Individual modules and the lowered core snapshot also obey existing syntax/source limits; identifier expansion can exceed the lowered-source bound. `__talven_module_` is reserved for identifiers in the companion profile.

## Context and source identities

Receipts identify exact module sources, direct import bindings, current compiler, lowered source and canonical `graph_hash`. `--expect-graph-hash HASH` rejects a different checked closure. Retain graph and compiler hashes together. These identify snapshots, not authenticated build results or cached substitutes for current source.

Focused context uses semantic labels `file.tal::Name`; source uses local/imported names. It includes direct callees, relevant records, direct callers, all public interfaces and whole-closure console requirements. `--include-body` adds only selected exact declarations as untrusted text. Context/query success budgets count complete UTF-8 JSON/newline: default 16384, range 1 byte through 1 MiB. Failures yield no partial facts. Frontend success does not replace independent task acceptance.

Loading pins the root directory and rereads captured files before successful facts/publication. These are observations, not atomic compare-and-swap or multi-file transactions; coordinate other writers independently. The inspected POSIX directory-relative no-follow facilities are required; unsupported hosts fail explicitly.

## Editor and in-memory APIs

`talven.project.analyze_project(entry, sources)` takes `{relative_path: source_text}` and resolves only the reachable closure without fetching missing sources. `project_context` and `project_query` share checking and original source locations.

The LSP advertises experimental `talvenProjectQuery`. Send `talven/projectQuery` with `entry`, the explicit `sources` bundle, `file`, a zero-based UTF-16 `position`, and `kind` (`hover`, `definition` or `references`). Optional `maxBytes` defaults to 16384; `expectGraphHash` rejects stale graph inputs. Responses use `talven.project-query.v1`, exact identities and root-relative file/range locations. Clients map file labels to document URIs.

Each request freshly checks its supplied bundle. Invalid current sources return diagnostics and never reuse a previous query. It opens no source URI and executes no tool. This is separate from standard single-document requests. Automatic workspace synchronization, project rename/completion/signature help and project edit/test/watch integration remain open.

The Rust executable independently checks/emits the resolved core source in CI; standalone native graph resolution and raw module syntax are unimplemented.

## Diagnostics and evidence

E1101: invalid profile/path request; E1102: unavailable module/cycle; E1103: private export/signature type; E1104: graph/resource limit. Existing name/type/ownership diagnostics retain original module positions. E0501 rejects revision/observed source changes and E0502 output budgets.

Required CI executes the example, compares reference/Rust resolved-source output, and runs independent oracles under ASan/UBSan at O0/O2. Module startup/check/build costs, memory and agent effectiveness remain unmeasured; broader milestone gates stay open.
