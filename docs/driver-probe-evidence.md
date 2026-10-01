# Stable driver probes: local comparison

The [private object session](object-reuse.md) now retains successful version/target probes under its explicit stable-toolchain assumption. It matches driver path/bytes, effective environment and actual working-directory identity, while still freshly preprocessing current source and checking final identities. Standalone preparation still probes on every call. Working-directory/environment capture also binds all commands in a candidate to one context; their identity fields retain hashes instead of values. Trusted compiler output can still contain host paths.

[Retained paired evidence](../experiments/results/stable-driver-probes-macos-arm64-20261001.json) contains all 288 samples from six runs: three before/after pairs in AB/BA/AB order, one measured repetition per condition/pair, no warmup. Every run uses the [existing native acceptance method](object-rebuild-baseline.md), including expected invalid edits and repairs. All pairs passed exact frozen function-C and object-byte equality, identical compiled/reused decisions, full diagnostics and independent native acceptance of actual objects. Compiler/driver/Python/configuration/workload identities are retained; only `talven/preprocessed_units.py` and `talven/unit_build.py` differ among archived measurement inputs.

Host: Apple M4, macOS ARM64, CPython 3.14.7, Apple Clang 21.0.0 (`clang-2100.3.34.2`), target `arm64-apple-darwin27.0.0`, strict C11/O2/warnings/no-LTO. UTC range: 2026-10-01 14:35:10–14:37:54. Before condition: archived commit `a8087c2` compiler inputs; after: working-tree probe/directory changes recorded by exact input hashes. Host caches were warm/uncontrolled; no concurrent local agent test/documentation/measurement jobs ran. Ordinary background load was uncontrolled. Both processes started with `PYTHONHASHSEED=0`. No model/provider/tokenizer was used.

Unit-build timings in milliseconds, one observation in each pair:

| Workload / edit | Before, pairs 1 / 2 / 3 | After, pairs 1 / 2 / 3 |
| --- | --- | --- |
| chain-32 comment | 88.125 / 90.393 / 82.834 | 77.719 / 59.717 / 62.139 |
| chain-32 body | 137.764 / 161.875 / 117.822 | 128.691 / 97.863 / 97.089 |
| chain-128 comment | 157.235 / 105.681 / 104.358 | 105.310 / 90.751 / 89.977 |
| chain-128 body | 170.997 / 175.910 / 145.694 | 163.016 / 129.819 / 118.573 |
| stores-128 comment | 160.068 / 143.721 / 145.451 | 115.348 / 125.658 / 169.595 |
| stores-128 body | 190.438 / 188.664 / 176.873 | 159.273 / 157.034 / 247.274 |
| borrowing comment | 97.824 / 102.564 / 81.665 | 56.178 / 60.647 / 60.142 |
| borrowing body | 129.155 / 124.062 / 117.456 | 90.084 / 100.355 / 96.982 |

The complete evidence also retains initial, contract/schema, invalid, repair and ordinary full-build controls. Initial builds still probe; subsequent successful builds reuse probes when identities match. Invalid source launches no compiler, and repairs retain the last successful probes/objects. This work metadata is excluded from object-key configuration so fresh/reused probe labels cannot themselves invalidate objects.

The observed chain/borrowing comment and body timings were lower in all three pairs. Store-heavy changes were mixed: pair 3 was higher after the change. Repairs and cold/contract builds also vary; cold units still start many separate compiler processes. These observations support reducing repeated probes within the stated contract, not a general build-speed percentage or consistency guarantee. Do not combine these timings with the earlier differently ordered/run-configured [whole/reused baseline](object-rebuild-evidence.md).

The public artifact preserves exact sources/oracles, orchestration text/hash, all raw timing/order/work receipts, input/executable/configuration identities and each original report hash. Repeated object lists are losslessly interned under `object_sets`. Local paths, command arguments and working-tree status are omitted; complete local archives remain under `build/stable-probe-paired/`, with baseline sources under `build/stable-probe-baseline-inputs/`. Hashes are byte identities, not authenticated acceptance or full toolchain capture. Memory, save-to-running/readiness, state preservation, default-watch integration and agent cost remain unmeasured.
