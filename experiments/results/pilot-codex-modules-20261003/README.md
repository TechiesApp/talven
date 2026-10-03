# Codex module-editing pilot archive

See the [method, observations and limits](../../../docs/codex-module-pilot-evidence.md).
Eight live trials passed on their first attempts in both conditions; no repair or
infrastructure failure occurred. This is a correctness ceiling, not an agent-cost
benefit: added compiler context increased input tokens in this run.

- `run.json` preserves original input/model/compiler identities and actual usage,
  verdicts and command outcomes. Private command paths, artifact paths and nested
  process transcripts are normalized; original run/argv hashes are retained.
- `report.json` is the unmodified report. Dollar costs, cache-write usage, tokenizer
  identity and provider model snapshot remain unknown.
- `reverified.json` preserves fresh native results and toolchain agreement with
  normalized command metadata.
- `model-catalog.json` is the exact restricted catalog fingerprinted by the adapter.
- Every attempt retains exact `request.json`, `response.txt` and accepted `task.tal`
  bytes. All eight candidates passed module formatting checks and fresh native
  verification, including each helper-return sensitivity probe.

Historical replay requires trusted revision
`dc5cba341d427b812133b170f2420ac3d5d87636`, or identical pinned inputs:

~~~sh
python3 -m experiments reverify experiments/results/pilot-codex-modules-20261003 \
  --out build/codex-modules-reverified.json
~~~

Copy the archive into that trusted checkout first. Replay uses its verifier and
the selected trusted C compiler, never archived adapter/command paths. Exact
toolchain agreement requires the original C compiler identity; another target's
execution is separate evidence. The normalized public archive was itself
successfully reverified. Current-compiler candidate regressions remain separate
from this frozen historical experiment.
