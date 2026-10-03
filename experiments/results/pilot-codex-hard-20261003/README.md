# Codex hard-task follow-up archive

See the [method, observations and limits](../../../docs/codex-hard-pilot-evidence.md). Eight live source/compiler trials passed at the first attempt; no repairs or infrastructure failures occurred in this run. The preceding large-program pilot's nine integration failures remain in its own archive and are not erased or attributed to this run.

- `run.json` retains original input hashes, model/transport/compiler settings, invocation guard, exact request/response/source hashes and verdicts. Local command paths and nested process transcripts are removed; the original run SHA-256 is under `publication`.
- `report.json` is the unmodified actual report; dollar and cache-write metrics remain unknown.
- `reverified.json` retains fresh native outcomes and toolchain agreement, with local command paths omitted.
- `model-catalog.json` is the exact restricted catalog identified by the run.
- Each trial retains exact `request.json`, adapter `response.txt` and accepted `task.tal` bytes. All eight sources passed canonical-format checks and fresh native reverification.

Historical replay requires a trusted checkout of revision `38116913e1080601243bf5e96420860127c5b258` (or identical pinned Python/guide/harness/task bytes). Copy this public archive there and run:

~~~sh
python3 -m experiments reverify experiments/results/pilot-codex-hard-20261003 --out build/codex-hard-reverified.json
~~~

The original C compiler identity is required for exact toolchain agreement; another toolchain provides separate fresh target evidence. The public normalized archive was itself successfully reverified. Replay invokes the matching trusted verifier and no model/archived adapter command. The current-compiler regression test intentionally remains separate from frozen historical replay.
