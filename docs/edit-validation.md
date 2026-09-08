# Read-only edit previews

The experimental `talven edit` commands identify source/compiler revisions and check a complete candidate before an applying host decides what to do with it. They use the shared frontend, write neither input file, and invoke no C compiler or model. See [Proposal 0008](proposals/0008-revision-checked-edit-validation.md) and the [actual validation evidence](edit-validation-evidence.md).

## Preview a repair

Run from the repository root with Python 3.11+. This example uses a broken type fixture as the base, writes a separate candidate under `build/`, and previews the repair:

~~~sh
mkdir -p build/edit-demo
python3 -m talven edit snapshot examples/invalid/type.tal --include-source > build/edit-demo/snapshot.json
cat > build/edit-demo/candidate.tal <<'TAL'
fn main() -> i32 {
    let count: i32 = 1;
    return count;
}
TAL
python3 - <<'PY'
import json
from pathlib import Path
import subprocess
import sys

snapshot = json.loads(Path('build/edit-demo/snapshot.json').read_text())
subprocess.run([
    sys.executable, '-m', 'talven', 'edit', 'validate', 'examples/invalid/type.tal',
    '--candidate', 'build/edit-demo/candidate.tal',
    '--expect-source-hash', snapshot['source_hash'],
    '--expect-compiler-hash', snapshot['compiler_hash'],
], check=True)
PY
~~~

The preview reports `ok: true`, a failed base analysis with the original type diagnostic, and a successful candidate analysis. `changes` is null because the base has no checked semantic model. The original fixture remains unchanged. Frontend success does not establish that a repair meets a task's independent correctness criteria.

## Snapshot a source revision

~~~sh
python3 -m talven edit snapshot examples/vectors.tal
~~~

`talven.edit-snapshot.v1` returns `ok`, `validation: "not-run"`, `source_hash`, `compiler_hash`, `profile`, `bootstrap_runtime`, `source_bytes`, and `diagnostics`. It accepts bounded UTF-8 input without parsing or type checking it. This makes revision identities available for invalid programs as well as valid ones.

`--include-source` adds the exact text under `untrusted_source_text`. It is omitted by default. Source comments are data and do not grant authority. Successful receipts omit paths and timestamps so repeated requests with the same inputs/runtime produce the same encoded document.

The hashes use the same identities as [context v2](prototype.md#compiler-generated-context). Source identity covers exact UTF-8 bytes, including CRLF, comments and whitespace. Compiler identity covers the current compiler module inventory. Runtime identity includes Python implementation/version and Unicode database version. These identifiers are not signatures, cache authentication or an execution attestation.

## Validate a complete candidate

`edit validate` requires both `--expect-source-hash` and `--expect-compiler-hash`, each a 64-character lowercase hexadecimal digest. Obtain them from a snapshot or matching context v2. `--candidate` names a complete UTF-8 source file, not a patch. The source and candidate may be the same file for a no-op preview.

The compiler identity and current source hash are checked before candidate analysis. A mismatch rejects the proposal; obtain fresh source/identities and reconsider the candidate. The command analyzes the base and candidate using the same type, move and call-scoped borrow rules used by `check`, context and LSP. It permits invalid-base repairs without fabricating declarations for the broken program.

`talven.edit-validation.v1` contains:

| Field | Meaning |
| --- | --- |
| `ok`, `validation` | The candidate passed all preview checks; validation remains `frontend-only` |
| `source_hash`, `candidate_hash`, `compiler_hash` | Observed input/compiler identities |
| `expected_source_hash`, `expected_compiler_hash` | Requested revision guards |
| `profile`, `bootstrap_runtime` | Language subset and Python/Unicode identity |
| `source_bytes`, `candidate_bytes`, `candidate_changed` | Exact UTF-8 lengths and whether source bytes differ |
| `base`, `candidate` | Each analyzed input's `ok` and first frontend diagnostic, or null before analysis |
| `changes` | Checked declaration/direct-call comparison, or null if either input is invalid |
| `diagnostics` | Blocking operation errors, each tagged with `input`: request, source, candidate or compiler |

Candidate syntax/type/borrow errors appear in `candidate.diagnostics` and make the preview fail. Base diagnostics can coexist with a successful repair. Ranges use the existing zero-based UTF-16 convention and refer to their respective input. Validation receipts never include source bodies. Expected IO, encoding and revision failures return the same operation schema with `ok: false` and available identities; unobserved fields can be null.

Both commands emit JSON without a `--json` switch. Exit zero means snapshot acquisition or candidate preview succeeded, according to the selected operation. Controlled failures exit one. Missing required command-line arguments follow the CLI's existing argument-error behavior.

## Interpret declaration changes

When both programs pass the frontend, `changes` contains four arrays:

- `added` and `removed`: full declaration contract facts, sorted by kind/name.
- `contracts_changed`: kind/name and complete before/after contract facts for declarations present in both inputs.
- `calls_changed`: name and sorted before/after direct-callee sets for functions present in both inputs.

Function facts reuse context's signatures, ordered parameters, passing/borrowing permissions and return types. Record facts contain ownership and ordered name/type fields. Call sets are separate from function contracts. A declaration identity is its kind/name pair; changing a function into a record produces a removal and addition.

Parameter/field order matters. Declaration order and layout do not. Changes to comments or function bodies may produce empty change arrays while `candidate_changed` remains true. The comparison does not infer renames, transitive impact, runtime call counts, behavior, ABI compatibility, resource effects or test selection. Added/removed functions have no separate call-change entry.

## Limits and error codes

Each source file has the existing **256 KiB UTF-8** input limit. `--max-bytes` defaults to **16384** and accepts 1 through 1048576. It caps the complete encoded snapshot or completed validation receipt, including the final newline. This is a byte budget, not a tokenizer count. A report that does not fit fails; fields and JSON are never silently truncated. Compact diagnostic failure envelopes are outside that requested report budget, as with context errors.

| Code | Meaning |
| --- | --- |
| E0701 | Malformed revision hash or invalid preview byte budget |
| E0702 | Compiler revision differs from the expected/initial revision |
| E0703 | Complete preview/snapshot receipt exceeds its byte budget |
| E0501 | Source revision differs, or a source/candidate change was observed during the operation |
| E0005 | Source input exceeds a frontend limit |
| E0901 | Input file or UTF-8 failure |

Candidate/base analysis retains ordinary [frontend diagnostic codes](prototype.md#structured-diagnostics). A compiler-tooling change alters the aggregate hash even when the language semantics stay the same. Old evaluation archives still require their matching trusted revision; this feature never relaxes their provenance checks.

## Application and trust boundary

The command re-reads inputs and checks compiler identity before reporting success. This catches changes it observes. It neither locks the files nor guarantees an atomic snapshot or compare-and-swap; files can change immediately afterward. A hash-matching no-op does not prove no intervening writer existed.

An applying host must coordinate writers and validate the current base, candidate and compiler identities within that enforced boundary. There is no `apply` operation in this increment. The existing formatter retains its documented single-writer assumptions. A successful preview provides no write/release permission, hostile-process isolation, native execution evidence or guarantee of task correctness. Independent acceptance remains necessary, and controlled agent evaluation remains an open M1 gate.
