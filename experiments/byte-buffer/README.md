# Supplied-storage byte-buffer experiment

Standalone internal hosted C11 profile: `c11-supplied-byte-buffer-v1`.
[Proposal 0045](../../docs/proposals/0045-supplied-byte-buffer-runtime.md) specifies
one fixed-capacity byte container on the existing
[region runtime](../supplied-storage/runtime.h). It is a C foundation for later
compiler integration; the Talven `--resources` profile still exposes only Block.

`tv_buffer` holds an allocation token and private logical length. Reserve zeroes
its fixed reserved capacity and starts length at zero. Push appends a byte, pop
returns/removes the last logical byte, read/write use logical bounds, and close
releases the slot. A Block and Buffer cannot occupy that same region concurrently.
The region descriptor and aligned backing storage must remain alive throughout.

| Operation | Failure precedence and state |
| --- | --- |
| Reserve | Nonpositive capacity is InvalidRequest; insufficient space, occupied slot or saturated instance is Exhausted |
| Read | Negative or one-past logical index is OutOfBounds before addressing bytes |
| Write | Bounds before invalid byte; failures preserve bytes and length |
| Push | Full before invalid byte; failures preserve bytes and length |
| Pop | Empty touches no bytes; success decreases length without scrubbing |
| Close | Validates/relinquishes the exact live token; double/stale/malformed tokens abort |

Pop leaves its retired byte inaccessible. A later push overwrites it before making
it accessible, and a new reservation initializes its whole visible capacity.
Neither pop nor close promises secure erasure. Initialization-fault builds retain
consumed instance numbers and roll back occupancy; partial initialized backing is
inaccessible until a successful retry. Production includes no fault hook.

C metadata is private by convention, not a safe foreign-pointer boundary. C callers
must not forge/copy matching tokens, mutate descriptors, supply undersized storage,
reinitialize while tokens remain valid or use dangling origins. The header cannot
enforce Talven moves, call loans, scope exits or consume-and-close contracts.

## Reproduce acceptance

~~~sh
python3 scripts/check-byte-buffer-runtime.py --out build/byte-buffer-runtime.json
python3 -m unittest tests.test_byte_buffer_runtime -v
~~~

The gate compiles captured inputs, executes independent byte/state-ledger checks
under O0/O2 ASan/UBSan for capacities 1, 32 and 4096, and exercises every allocation
initialization fault point. Separate negative processes must abort specifically
with SIGABRT without sanitizer failures. Mutation tests prove the independent
oracle rejects plausible wrong results and skipped work. Actual host/target,
compiler settings, source identities, raw commands and measured layouts are
recorded; unsupported tools/hosts fail rather than skip. Linux x86-64/ARM64 CI
retains separate receipts for 30 days.

Production-object dependency inspection excludes test hooks and direct heap
symbols. It does not inspect transitive libc/startup behavior. Layout measurements
exclude backing capacity, padding between objects, live temporaries and test
ledgers. This experiment measures no latency, total RAM, whole-stack usage or
agent benefit; original-source compiler integration and production costs remain
separate follow-ups.

The [retained macOS ARM64 receipt](../results/byte-buffer-runtime-macos-arm64-20261004.json)
records twelve sanitizer ledger executions and 144 negative trap processes for
its exact captured sources and tools. Ten focused tests also passed, including
compiled behavioral mutations and real source/artifact/tool-change rejection.
Its buffer sizeof is 40 bytes and allocation-result sizeof is 48 bytes; backing
capacity and live copies are separate. Linux CI produces independent target receipts.
