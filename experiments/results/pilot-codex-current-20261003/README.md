# Codex current-profile pilot archive

See the [method, result and limits](../../../docs/codex-pilot-evidence.md). Six live trials passed on the first attempt; all accepted sources were independently reverified. Nine preceding startup-warning integration failures are preserved separately in `setup.json`, rather than relabeled as task failures or successes.

- `run.json`: original run identities, input hashes, model/CLI/catalog settings, guards, trial receipts and independent verdicts. Local command paths and nested process transcripts are removed; the original local run's SHA-256 is recorded under `publication`.
- `report.json`: unmodified report from the successful live run, with unknown dollar/cache-write metrics retained.
- `reverified.json`: fresh native verdicts and toolchain agreement, with local commands omitted.
- `model-catalog.json`: exact restricted catalog whose SHA-256 is pinned in the run.
- Trial directories: exact `request.json`, adapter `response.txt`, and accepted `task.tal` bytes. Source hashes match the run, and all six retained sources pass formatter checks.
- `setup.json`: nine original rejected invocations, including token receipts and request/response identities. Private raw CLI diagnostics remain local.

Reverification executes the current trusted compiler/verifier, never archived adapter commands. Use a trusted checkout of recorded revision `1aa02fc2b30a5817e7198738b919d365f08633b1` (or identical pinned Python/guide/task bytes), copy this archive into that checkout, and run:

~~~sh
python3 -m experiments reverify experiments/results/pilot-codex-current-20261003 \
  --out build/codex-pilot-reverified.json
~~~

This requires the same C compiler identity for exact toolchain agreement. Reverification on another toolchain is fresh target evidence and must disclose that difference. No model call is made by reverification. The published normalized archive itself was successfully reverified before publication.
