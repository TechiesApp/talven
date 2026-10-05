# Supplied-storage byte blocks

Explicit experimental profile: `m2-supplied-blocks-v1`, selected with `--resources`.
[Proposal 0043](proposals/0043-supplied-blocks-compiler.md) implements the lexical
lifetime contract in [Proposal 0041](proposals/0041-supplied-storage-regions.md) using
the [tested C runtime](proposals/0042-supplied-storage-c-runtime.md). Both reference
and Rust compilers parse/check original source and emit the same C11 text.

## Storage and ownership

~~~text
region storage(64) {
    match (reserve(storage, 16, 8)) {
        Allocation::Granted(block) { release(block); }
        Allocation::InvalidRequest { }
        Allocation::Exhausted { }
    }
}
~~~

A region declares stable local backing storage with a literal capacity 1..4096.
One function may declare at most eight regions, including mutually exclusive
branches. There is one reusable slot per region. These limits do not bound recursive
total stack usage. The region name is a lexical capability accepted only by reserve;
it cannot move, become a parameter, be stored or escape through a result.

Reserve validates positive size and alignment in 1, 2, 4, 8, 16. Invalid requests
return `Allocation::InvalidRequest`; oversized requests or instance exhaustion
return `Allocation::Exhausted`. Successful requests zero exactly their visible
range before producing `Allocation::Granted(Block)`. The checked source rejects
another reserve while an allocation outcome or live child remains outstanding.

Block is opaque, linear and tied to that exact region. Moves preserve its release
obligation. `Allocation::Granted(real_block)` may rewrap an owner with the same
origin; failure alternatives are produced only by reserve. Allocation values cannot
be function parameters/results. User records/outcomes cannot store Block or
Allocation; Block has no constructor, fields, copying or reassignment.

Every owner, including a selected match payload or unused function parameter, must
be released or passed to a checked synchronous owning Block parameter before its
binding scope exits. Regions require no outstanding outcome/owner at exit. Every
normal return validates obligations before its path is excluded from joins;
continuing branches and optional boolean operands must agree on resource state.
Functions cannot return Block-bearing values. Traps terminate without cleanup or
unwinding guarantees; no implicit destructor or release occurs.

~~~text
fn finish(block: Block) -> i32 {
    return release(block);
}
~~~

The checker verifies this consume-and-release contract independently. Its caller
keeps the originating region alive throughout the synchronous call. A plain move
to another local does not satisfy the contract.

## Bytes and typed failures

| Operation | Contract |
| --- | --- |
| `release(Block) -> i32` | Consume owner; free its exact instance; normal result 0 |
| `read_byte(&Block, i32) -> ByteRead` | `Value(i32)` in 0..255 or `OutOfBounds` |
| `write_byte(&mut Block, i32, i32) -> ByteWrite` | `Written`, `OutOfBounds` or `InvalidByte` |

Bounds are checked before addressing bytes. Writes check bounds before the 0..255
value range, with no change on failure. Read/write outcomes must be handled using
ordinary exhaustive consuming matches. Loans remain nonescaping and call-scoped;
borrowed Block parameters cannot release an owner. An exclusive loan requires an
exclusive parameter or `let mut writable = block`, which transfers ownership while
permitting byte mutation. Existing overlapping-loan and use-after-move checks apply.

E0320 reports resource shape, bounds, forgery and escape restrictions. E0321 reports
unreleased/outstanding resources or inconsistent resource paths. Existing type,
borrow, move and outcome diagnostics retain their meanings. Arithmetic overflow and
invalid C runtime tokens trap. Source has no access to C pointer/token manufacture.

## Commands and editor facts

~~~sh
python3 -m talven check examples/resources/blocks.tal --resources --json
python3 -m talven fmt examples/resources/blocks.tal --resources --check
python3 -m talven context examples/resources/blocks.tal --resources
python3 -m talven emit-c examples/resources/blocks.tal --resources
python3 -m talven build examples/resources/blocks.tal --resources -o build/blocks
./build/blocks

experiments/native-compiler/target/release/talven-native check examples/resources/blocks.tal --resources --json
experiments/native-compiler/target/release/talven-native fmt examples/resources/blocks.tal --resources --check
experiments/native-compiler/target/release/talven-native emit-c examples/resources/blocks.tal --resources
~~~

CLI context and custom LSP `talven/resourceContext` share current checked
`talven.resource-context.v1` facts: source/compiler/runtime identities, opaque linear
passing, owning parameter effects, intrinsic contracts and lexical origins/capacities.
LSP parameters are explicit in-memory `source`, optional `maxBytes` (default 16384,
maximum 1048576), and `expectSourceHash`. Too-small budgets, invalid source and stale
hashes fail without partial facts. The request executes no code and reads no URI.

Normal commands and standard LSP document operations retain the base grammar.
Resource selection excludes `--outcomes`, module formatting, freestanding targets,
ordinary compact/focused context and native resource context. Modules, C ownership
exports/units, edit/test/watch/reuse/hot reload remain separate work. Formatter
success checks syntax/layout, not ownership or task correctness.

## Verification and costs

~~~sh
python3 scripts/check-resource-sanitizers.py --out build/resource-reference.json
python3 scripts/check-resource-sanitizers.py --native experiments/native-compiler/target/release/talven-native --out build/resource-native.json
~~~

The [original source workload](../tests/fixtures/resources/workload.tal) and
[independent driver](../tests/fixtures/resources/driver.c) test request validation,
byte values/failures, moves/rewrapping, checked delegation, reuse, counter saturation
and every initialization fault/retry point for sizes 1 and full capacity. Each
producer runs twelve O0/O2 ASan/UBSan workloads across capacities 1, 32 and 4096.
The driver computes expected requests, instances and bytes from inputs and requires
an empty independent ledger after every complete call. Source C adapters expose
events only in a trusted test build; production contains no test hook dependency.
The standalone runtime still checks stale-token/guard traps independently.

Receipts preserve exact source/driver/runtime/gate inputs, compiler identities,
target/settings, generated-C hashes and production object dependencies. Native
receipts archive embedded source/build information and binary identity; the gate
rejects stale embedded inputs and producer changes during execution. Required
CI uses actual Linux x86-64/ARM64 hosts, rejects skipped tests and retains separate
producer receipts. Local macOS ARM64 receipts are archived separately for the
[reference compiler](../experiments/results/resource-source-20261004/reference.json)
and [native compiler](../experiments/results/resource-source-20261004/native.json);
these are sanitizer/dependency acceptance, not performance measurements.

Capacity remains reserved until its lexical region ends after release. Descriptor,
owner/outcome temporaries, alignment padding and stack-probe helpers can affect
compiled costs. The separate [production cost experiment](resource-costs.md)
reports target layouts, compiler-reported bounded stack usage, artifact sizes and
complete-call batch timing for fixed sequential workloads, after independent
acceptance. Its production binaries omit the ledger. Total RAM, isolated
reserve/release latency and agent benefit remain unmeasured. Heap containers,
cancellation, general allocator lifetimes and concurrency remain open; this
sequential profile does not complete the broader M2 milestone.

[Proposal 0045](proposals/0045-supplied-byte-buffer-runtime.md) adds a separate
standalone C byte-buffer experiment on the same slot/token contract, with private
logical length, bounded push/pop and explicit close. It does not add Buffer types
or operations to this Talven source profile. Source ownership/tooling integration
and buffer production cost measurements are subsequent gates.
