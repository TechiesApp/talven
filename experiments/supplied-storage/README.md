# Supplied-storage runtime experiment

`runtime.h` is a hosted C11 single-slot prototype under
[Proposal 0042](../../docs/proposals/0042-supplied-storage-c-runtime.md), following
the [lexical region contract](../../docs/proposals/0041-supplied-storage-regions.md).
It is not connected to either Talven frontend. C callers keep aligned storage and
live descriptors valid; source lifetime/move/loan enforcement remains future work.

Run the independent ledger, fault injection, O0/O2 sanitizer and trap gate:

~~~sh
python3 scripts/check-region-runtime.py --out build/region-runtime.json
~~~

The output records exact inputs, target/compiler settings and measured C object
layouts. It creates a new receipt file and fails on verification or observed-source
changes. The test fixture's extra ledger/storage and hosted libc/startup are separate
from production helper layout/dependency inspection. No total RAM/latency or Talven
allocator support is claimed.

The [local macOS arm64 receipt](../results/region-runtime-20261004/receipt.json)
preserves the captured prototype sources and observed layouts. CI retains its own
Linux target receipts; a local run does not establish evidence for another host.
