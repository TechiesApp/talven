# Proposal 0045: Supplied-storage byte-buffer runtime

- Status: Implemented standalone C experiment; source integration remains open
- Requirements: R08, R09, R10, R11, R16
- Decisions: D73 (proposed), D69, D70, D71

## Scope and integration order

Build one concrete fixed-capacity byte container on the existing
[supplied-storage runtime](0042-supplied-storage-c-runtime.md) before extending
[checked source ownership](0043-supplied-blocks-compiler.md). The internal hosted C11
profile is `c11-supplied-byte-buffer-v1`. This increment adds no Talven syntax,
compiler built-ins, resource context, heap allocation, generic containers, loops,
concurrency, automatic cleanup or new foreign ABI. Source integration is a separate
follow-up with original Python/Rust diagnostic, formatter, emission and source-ledger
parity. The broader [M2 gate](../roadmap.md#m2-memory-and-concurrency-foundations)
remains open.

## Internal representation and exact operation contract

The header `experiments/byte-buffer/runtime.h` includes the existing region header.
`tv_buffer` contains a `tv_block block` allocation token and a private `size_t length`.
The block's immutable length is reserved capacity; the buffer's logical length is
initialized accessible content. All operations validate the region token, require
alignment 1, and require logical length not to exceed reserved capacity before any
byte address. Matching forged C tokens, copied metadata, dangling descriptors and
undersized backing objects remain outside the trusted C boundary. Source must later
make Buffer opaque and linear; this header alone cannot enforce those rules.

| Internal operation | Result and behavior |
| --- | --- |
| `tv_buffer_reserve(tv_region *, int32_t)` | `tv_buffer_allocation`, using `TV_GRANTED`, `TV_INVALID_REQUEST`, `TV_EXHAUSTED`; Granted payload member `buffer`; positive capacity, alignment 1, length zero |
| `tv_buffer_length(const tv_buffer *)` | Validated logical length as i32 |
| `tv_buffer_capacity(const tv_buffer *)` | Validated reserved capacity as i32 |
| `tv_buffer_read(const tv_buffer *, int32_t)` | Existing `tv_byte_read`; bounds use logical length |
| `tv_buffer_write(tv_buffer *, int32_t, int32_t)` | Existing write discriminators; bounds before value; length unchanged |
| `tv_buffer_push(tv_buffer *, int32_t)` | `TV_BUFFER_PUSHED`, `TV_BUFFER_FULL`, `TV_BUFFER_INVALID_BYTE`; full before invalid byte; write old length then increment |
| `tv_buffer_pop(tv_buffer *)` | `tv_buffer_pop_result` with `TV_BUFFER_VALUE` and i32 value, or `TV_BUFFER_EMPTY`; read last logical byte then decrement |
| `tv_buffer_close(tv_buffer)` | Consume/release exact region token; normal result zero |

Values represent bytes 0..255. Negative/one-past indices fail before pointer
arithmetic. Ordinary allocation/operation failures leave metadata and all backing
bytes unchanged. Pop does not scrub its retired byte: it becomes inaccessible,
later push overwrites before exposure, and fresh reserve zeroes the entire reserved
range. No secure-erasure claim follows. Block and Buffer share the same single
slot: either live owner prevents another reservation until release/close.

Reserve delegates exactly once to the existing zero-filling region operation.
The existing `TV_REGION_TEST_FAULT` hook covers acquisition, each initialized byte
and token publication; failed initialization clears occupancy/live request fields,
retains the consumed instance and may leave inaccessible partially initialized
bytes. Buffer wrapping itself is infallible and publishes length zero only after
region success. Saturation cannot wrap or reuse an instance number. Closing releases
the slot but does not end the lifetime of backing storage or reclaim its stack frame.

## Independent acceptance

A separately authored C driver derives expected requests, lengths, capacities,
instance progression, operation results and every backing/sentinel byte from its
input plan. It never derives expected values from observed runtime metadata.
Compare full byte/state snapshots after every operation. Every normal complete
workload leaves zero live owners; nonsaturated slots must be reusable.

For capacities 1, 32 and 4096, execute O0/O2 ASan/UBSan builds with and without
initialization faults. Cover invalid capacities, occupied preservation and mixed
Block/Buffer reservations, empty/full transitions, negative/one-past/extreme indices,
all byte boundaries, failure precedence, repeated fill/drain/refill, write without
length change, close/reuse and all initialization fault points at size 1/full capacity.
Inject saturation at creation under trusted test control, check failed retry and
permanent exhaustion, and verify bytes outside reserved capacity remain unchanged.

Separate processes must abort specifically with SIGABRT, without sanitizer reports,
for stale same-request owner reuse, double close, invalid length, mismatched block
capacity/alignment/instance, and read/write/push/pop/query after close. Unknown probe
names must not be counted as successful traps. Mutation tests must reject plausible
wrong results, missing writes, incorrect length transitions and changed failure
precedence against this independent oracle.

The gate captures exact header/driver/script/test inputs and source texts/hashes,
records actual host, C target/compiler, flags, raw command results and layouts,
compiles captured bytes and rejects observed input/tool/artifact changes. It refuses
unsupported host/tool configurations instead of skipping. Production wrappers build
without hooks/sanitizers; undefined symbols are restricted to abort, byte copy/fill
and compiler stack/GOT support, excluding direct heap or test dependencies. This
inspection covers that object, not transitive host startup/libc. Linux x86-64/ARM64
CI requires no skipped checks and retains separate receipts.

## Cost, agent context and alternatives

Report measured descriptor/block/buffer/allocation/pop-result sizeof values for each
target, separately from backing capacity, padding, live copies and test ledgers.
No timing, total RAM, whole-stack, p99, agent-cost or broader container/concurrency
claim follows. [Proposal 0044](0044-supplied-block-production-costs.md) remains the
separate production-cost contract; it must be extended with original buffer source
acceptance before publishing buffer production timings.

General resource-bearing structs need aggregate provenance and partial-move
analysis. Returned owners need stable allocator lifetimes. Generics, loops and
concurrency add separate semantic obligations. One opaque byte container tests
length/capacity invariants first without weakening the existing owner model. Future
source contracts should retain explicit typed failures, call-scoped loans,
consume-and-close parameters, origin-specific release obligations and bounded,
versioned context. No new source support is claimed by this runtime increment.

## Retained local evidence

The [macOS ARM64 receipt](../../experiments/results/byte-buffer-runtime-macos-arm64-20261004.json)
passed twelve O0/O2 ASan/UBSan ledger executions and 144 SIGABRT probes for the exact
captured inputs. It records effective Apple Clang 21.0.0 and the selected macOS SDK,
with ten focused tests passing separately, including four compiled behavioral
mutations and source/artifact/tool-change rejection. On this target the descriptor
is 48 bytes, block 32 bytes, buffer 40 bytes, allocation result 48 bytes and pop
result 8 bytes. These are target-specific sizeof observations, excluding backing
capacity and live copies. Required Linux CI retains its own receipts before merge;
local sanitizer success does not establish those target results.
