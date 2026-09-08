# Reproducible agent evaluation

Status: implemented provider-neutral harness for the four-task corpus, schema `talven.eval.v1`, corpus `m1c-agent-tasks-v1`. No paid model run or comparative token/cost result is supplied. Offline fixtures test the runner and are explicitly **not model measurements**. See [Proposal 0004](../docs/proposals/0004-reproducible-agent-evaluation.md) and [actual validation](../docs/evaluation-validation.md).

Requires Python 3.11+, Git, and a native C11 compiler. Run from the repository root. Compiler and acceptance tests remain separate from model edits. The harness does not change the language or complete the full M1 gate.

## Run the offline fixture

These commands work without credentials or a network connection after the toolchain is installed:

~~~sh
python3 tests/fixtures/eval_adapter.py --write-config build/eval-fixture.json
python3 -m experiments run --adapter build/eval-fixture.json --out build/eval-smoke
python3 -m experiments reverify build/eval-smoke --out build/eval-reverified.json
python3 -m experiments report build/eval-smoke
~~~

Use fresh output/config paths for another run; existing results are never silently overwritten. The fixture deliberately submits an unsuccessful initial candidate, then a hand-written repair. It uses the same edit boundary, compiler, native verifier, and artifact recording as a live adapter. `measurement_kind` is `fixture`; reported token counts and dollar amounts stay null. Fixture completion rates and elapsed times describe only this scripted check.

`run` exits 0 when every trial passes, 1 for completed task failures, and 2 for infrastructure/configuration/protocol errors. It records failed calls and partial runs, saves progress before each adapter invocation, and leaves `complete:false` if interrupted. Incomplete suite reports do not claim a correctness rate or total cost. Reverification performs fresh correctness checks without model calls or new billing evidence.

## Corpus and independent acceptance

Each trial starts with an empty conversation and the exact original source. The default runs all four tasks in both conditions, once, in recorded order. `python3 -m experiments tasks` prints the precise public instructions.

| Task ID | Starting point | Requested change | Independent acceptance |
| --- | --- | --- | --- |
| `move-scalar` | [moved.tal](../examples/invalid/moved.tal) | Copy the original scalar before moving the record | Preserve immutable `original = Item { value: 7 }`, direct `let transferred = original`, and a scalar snapshot returned through bindings; exact native result 7 |
| `strict-type` | [type.tal](../examples/invalid/type.tal) | Return integer 1 through explicitly typed `count:i32` | Preserve binding/return provenance and `main() -> i32`; exact native result 1 |
| `rename-field` | [vectors.tal](../examples/vectors.tal) | Rename `Vec2.x` to `horizontal` everywhere | Check AST fields/uses, preserve `dot(a:Vec2,b:Vec2)->i32`, varied native vector checks, and meaningful main check of dot((2,3),(4,5)) == 23 |
| `squared-length` | [vectors.tal](../examples/vectors.tal) | Add `squared_length(value:Vec2)->i32`; main checks (3,4) == 25 | Preserve Vec2/dot; native positive, negative, and zero vectors; verify main detects wrong results for both original dot and new squared-length checks |

Scalar tasks intentionally require straight-line `let` bindings followed by a final binding return. For vector tasks, the verifier changes the required example calculation to several wrong results and checks that main rejects them. It compares full i32 values in reviewer-controlled C, avoiding operating-system exit-code truncation. Comments do not count as field uses. These finite tests catch specific cheats; they do not prove arbitrary program equivalence or prevent overfitting to a public corpus.

The [verifier](verifier.py) imports the shared frontend/backend but owns its acceptance rules and C harness. Model output never selects those rules, compiler flags, or commands. Emitted `tv_f_*` symbols remain a prototype test interface, not a stable foreign ABI.

## Context and repair protocol

- `--context source`: pinned prototype/borrowing guides, task instructions, and complete current task source.
- `--context compiler`: the same input plus compiler context v2. Invalid source receives structured frontend diagnostics instead of fabricated context. Context is recomputed for each repair.
- `--context both` (default): separate trials for both conditions; no conversation or candidate is shared.

The default additional compiler-context budget is **16384 UTF-8 bytes**, including the newline. Guides, source, task text, and prior conversation are outside this byte cap and still count toward actual provider input usage. This is not a token budget. Oversized context fails explicitly instead of truncating facts. Both conditions receive acceptance feedback after failed attempts; native test source is not inserted into prompts.

Each adapter call is one attempt. Attempt 0 is the initial solution; every subsequent call is a repair, even if the output is identical or invalid. `--max-repairs 2` therefore permits three calls. Malformed protocol output, adapter launch/exit failure, and adapter timeout end the trial as an error; there are no hidden runner retries. Candidate scope/syntax/acceptance failures permit repair. Infrastructure failures cannot become successful or skipped evidence.

Useful controls:

~~~sh
python3 -m experiments run --adapter build/eval-fixture.json --out build/eval-repeat \
  --task strict-type --task move-scalar --context both --repetitions 3 \
  --max-repairs 2 --context-bytes 16384 --adapter-timeout 60 \
  --native-timeout 5 --verification-timeout 60 --task-timeout 300 --cc cc
~~~

Repetitions run sequentially, then tasks and context conditions in recorded order. Vector verification makes multiple compiler/native calls; each has the native timeout and the verifier has a separate total timeout. Cross-run experimental ordering, model seeds/settings, and enough repetitions to support conclusions are the operator's responsibility. Identical prompts do not guarantee deterministic model sampling.

## Trusted adapter contract

Supply an adapter config matching `talven.eval.adapter.v1`. The offline config generator demonstrates a complete executable example. To connect a provider, replace its command with your trusted adapter and set `kind` to `live`, with explicit provider, exact model/version, tokenizer/version (or an explicit unavailable reason), and all sampling/output-limit settings. `command` is an argv array, with no shell expansion; use absolute paths for file arguments. `artifacts` lists adapter scripts/configuration/dependency locks to archive and hash, relative to the config directory or absolute. The executable is also fingerprinted. Transitive dependencies must be pinned by the operator.

The adapter receives one UTF-8 JSON request on stdin:

~~~json
{
  "schema": "talven.eval.request.v1",
  "corpus_version": "m1c-agent-tasks-v1",
  "task_id": "strict-type",
  "context_mode": "source",
  "repetition": 1,
  "attempt": 0,
  "allowed_files": ["task.tal"],
  "model": {"provider": "provider identity", "model": "exact model version", "tokenizer": "version or unavailable reason", "settings": {}},
  "messages": [{"role": "system", "content": "exact pinned instructions"}, {"role": "user", "content": "JSON task/source/context/feedback"}]
}
~~~

This is an illustrative shape; the runner supplies full content. The adapter must forward the exact messages in order, use the declared model/settings, and disable model tools. It may translate the provider's output format into the following stdout envelope. Diagnostics belong on stderr. The response and error streams are capped at 4 MiB each; over-limit or nonfinite/duplicate-key JSON is rejected.

~~~json
{
  "schema": "talven.eval.response.v1",
  "edits": {"task.tal": "fn main() -> i32 { let count: i32 = 1; return count; }"},
  "usage": null,
  "provider_metadata": {}
}
~~~

`edits` must contain exactly `task.tal`, as a complete UTF-8 source replacement up to the compiler's 256 KiB limit. Extra paths, traversal, unsupported top-level fields, and malformed usage are rejected. A scope-rejected candidate still contributes any valid provider usage already reported. The provider-neutral harness does not itself call a provider or infer model usage from its own Codex session.

For live observations, the trusted adapter may supply any of these nullable `usage` fields:

| Field | Contract |
| --- | --- |
| `input_tokens`, `output_tokens` | Actual nonnegative integer counts from the provider, including all charged retries/internal work performed by the adapter |
| `cached_input_tokens` | Provider-reported subset of input tokens; never subtracted from total input or added again |
| `usage_source` | Required provenance when any token count is present; identify receipt/provider response(s) |
| `model_cost_usd`, `tool_cost_usd` | Actual recorded nonnegative decimal strings, not API list-price estimates or subscription conversions |
| `model_cost_source`, `tool_cost_source` | Required provenance for each present cost; explicit zero also needs a basis, such as no adapter tools used |

Put sanitized provider response IDs, raw usage/billing receipts, returned model version, and cache details in `provider_metadata`. This evidence must come from trusted adapter/provider instrumentation, not a model-generated usage claim. The runner can validate shapes and provenance presence, not independently authenticate a provider's bill. If a call may have been charged but no receipt is available, leave its usage unknown. Do not silently omit internal retries, extra context, or charged failures; include them and describe them in metadata, or treat the trial as noncomparable.

## Accounting and artifacts

`run.json` records task status, actual attempts/repairs, usage, limits, exact commands, process results, latency, host architecture/OS, Python version, C target/version/flags/executable hash, compiler hash, Git revision/dirty state, corpus, and input hashes. Each attempt retains `request.json`, `response.txt`, candidate `task.tal` when valid, and `verification.json`. Pinned source/guides/compiler/harness bytes and adapter config/artifacts are archived. Transcript requests/responses/candidates have hashes. These identify bytes; they are not signatures. A dirty run can be audited from its archived inputs but should not be represented as a clean release benchmark.

`report.json` and `report` provide per-trial and per-context totals. Input/output tokens sum across all attempts, including unsuccessful tasks. No known partial subtotal is presented as a complete total. Cache-token coverage is independent of ordinary token coverage. The successful-task denominator is independent native acceptance, not compiler success or adapter assertions.

**Total task cost = model charges + adapter tool charges + measured verification charges.** Human labor is excluded. Missing components yield null total cost. The harness reports measured wall time but does not price it automatically. To incorporate actual verification/compute receipts after a run, write a JSON object keyed by trial ID, each value containing `amount_usd` (decimal string) and `source` (billing/allocation provenance), then run:

~~~sh
python3 -m experiments report build/live-run --verification-costs build/verification-receipts.json \
  --out build/accounted-report.json
~~~

This creates a new report without altering original run artifacts. Do not double-count verification already included in a receipt. Shared infrastructure allocation belongs in the receipt's provenance. **Cost per correct task divides cost of all trials, including failures/errors, by the number of correct trials.** It remains null if any cost is missing, the suite is incomplete, or no task succeeds. This metric is not an assertion about subscription usage.

`reverify` uses the current trusted compiler/harness only when pinned input hashes match, checks candidate hashes, and writes fresh correctness evidence. It does not import/execute compiler code from an untrusted run archive or replay model requests. It defaults to the current `cc`, never an executable path selected by archived metadata. An alternative trusted C toolchain may be selected explicitly with `--cc`; the new environment is recorded. Compare host/settings before treating it as a repeat of the same experiment.

## Boundaries and remaining evidence

The model's edit interface is restricted by the runner. The adapter executes in a fresh temporary working directory and receives no verifier files. **The adapter, verifier, C compiler, and host remain trusted.** A temporary directory, hash check, or repository instruction is not a hostile-process sandbox: a same-user executable can access files/network or interfere with other processes. Use an externally protected checkout and OS/container policy for untrusted agents or toolchains. Process time/output limits are resource hygiene, not comprehensive memory/disk/CPU quotas. Public acceptance code is not secret. Keep credentials in adapter-owned secret handling and out of configs, argv, prompts, and archived receipts.

Model experiments, M1c-specific borrowing tasks, cross-language baselines, provider cache comparisons, and statistical significance remain follow-up work. Equivalent Rust/C/TypeScript tasks need independently validated baselines before comparative claims.
