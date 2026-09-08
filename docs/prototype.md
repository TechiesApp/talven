# Reference compiler guide

Status: experimental implementation of `m1c-call-borrows-v1`, building on the M1a/M1b increments. The grammar and file extension `.tal` are prototype choices. The broader language design remains under development.

[M1b](formatting.md) introduced canonical formatting and native CI. [M1c](borrowing.md) extends the grammar below with call-scoped borrowing and record-field mutation, with a new context schema. See the [current validation record](borrowing-validation.md); earlier M1a/M1b records remain historical evidence.

## Run it

Use Python 3.11 or later from the repository root. This compiler uses the Python standard library only; no package installation or build scripts are needed to analyze code. A trusted C11 compiler is needed for native builds.

~~~sh
python3 -m talven check examples/vectors.tal --json
python3 -m talven context examples/vectors.tal --symbol dot --include-body
python3 -m talven build examples/vectors.tal -o build/vectors
./build/vectors
python3 -m unittest discover -s tests -v
~~~

The vector example exits with status zero when its calculation is correct. Programs currently communicate success through exit status; printing and standard I/O APIs are not implemented. Hosted operating systems may reduce an integer return value to a smaller exit-status range.

`check` and `context` do not invoke a C compiler or execute source programs. `emit-c` writes generated C without invoking another tool. `build` explicitly invokes the executable selected by `--cc` (default `cc`) using an argument array, with a 30-second timeout. It replaces the requested output only after compilation succeeds. The selected C compiler is trusted software; this is not a sandbox.

## Implemented grammar

~~~ebnf
program    = { record | function } ;
record     = "struct", identifier, "{", fields, "}" ;
fields     = identifier, ":", scalar, { ",", identifier, ":", scalar }, [","] ;
function   = "fn", identifier, "(", [parameters], ")", "->", type, block ;
parameters = identifier, ":", parameter_type, { ",", identifier, ":", parameter_type }, [","] ;
parameter_type = type | "&", ["mut"], record_name ;
type       = scalar | record_name ;
scalar     = "i32" | "bool" ;
block      = "{", { statement }, "}" ;
statement  = "let", ["mut"], identifier, [":", type], "=", expression, ";"
           | identifier, ".", identifier, "=", expression, ";"
           | "return", expression, ";"
           | "if", "(", expression, ")", block, ["else", block]
           | expression, ";" ;
~~~

Expressions include decimal integers, `true`, `false`, local names, field reads, named record construction (`Vec2 { x: 1, y: 2 }`), positional calls to named functions, parentheses, unary `-`/`!`, and binary operators. Direct call arguments may also borrow a named record with `&name` or `&mut name`; see [the exact borrowing rules](borrowing.md). `mut` is a reserved keyword. Record construction allows a trailing comma. Call arguments allow a trailing comma. Identifiers use ASCII letters, digits, and underscores, with a letter or underscore first. `//` comments run to the end of the line; input is UTF-8. There are no string literals or imports.

Precedence, from weakest to strongest: `||`, `&&`, equality (`==`, `!=`), ordered comparisons (`<`, `>`, `<=`, `>=`), addition/subtraction, multiplication/division/remainder, unary operators, field access. Binary operators associate left-to-right. Comparisons do not chain. The frontend rejects operations with incompatible operand types.

Functions and record types have distinct declarations in one global namespace; duplicate global names and names replacing scalar types are rejected. Calls always name global functions. Local bindings and parameters occupy a local namespace; shadowing an existing local binding is rejected. Branch-local names do not escape their block. Functions may refer to later declarations and may recurse.

All parameters and return types are explicit. Local types may be inferred. Every reachable function path must return the declared type. Unreachable statements after an unconditional return are rejected. `if` conditions require `bool`; parentheses around the condition avoid ambiguity with record literals.

## Values and ownership

`i32` and `bool` copy by value. Records are nominal, move-only values whose fields are restricted to these scalars. A record moves when assigned to a new binding, passed to a function, returned, or discarded as an expression statement. It cannot subsequently be used on a reachable path. Reading a scalar field leaves its record available.

~~~text
struct Item { value: i32 }

fn read_twice(item: Item) -> i32 {
    return item.value + item.value;
}

fn transfer(item: Item) -> Item {
    let next = item;
    return next;
}
~~~

Control-flow joins consider paths that continue execution. A move in a branch that returns does not invalidate the other continuing branch. Moves in the right side of `&&` or `||` are conservatively considered possible even when the left operand is a constant. This can reject programs a future flow-sensitive checker could accept.

These are **affine stack-value rules with call-scoped borrowing**, not a general resource-management implementation. M1c permits shared/exclusive borrowed parameters and scalar-field updates through `let mut` owners or exclusive parameters. References cannot be stored or returned. Records have no nested records, pointer/reference fields, destructors, heap storage, or foreign handles. Discarding a record performs no user-defined cleanup. C lowering may copy a record's representation while the Talven checker enforces its logical move. No zero-copy claim is made.

## Numeric and execution behavior

- `i32` ranges from -2147483648 through 2147483647. There are no implicit conversions, including between integers and booleans.
- Addition, subtraction, multiplication, and negation trap when the result is outside that range.
- Division and remainder trap for zero divisors and for `INT32_MIN / -1` or `INT32_MIN % -1`. Division truncates toward zero; remainder follows that quotient.
- Operands, call arguments, and record field initializers evaluate in source order. `&&` and `||` short-circuit.
- The C backend uses bounded `int64_t` intermediates and checked narrowing to avoid C signed-overflow undefined behavior for these operations. Hosted traps call `abort`; typed recoverable arithmetic errors are not implemented.
- Recursion and stack exhaustion are not bounded by the language. Runtime safety depends on the generated code, C compiler, execution environment, and this prototype's correctness. This is not production-hardened or audited code.

## Compiler-generated context

`context` emits one deterministic UTF-8 JSON document under `talven.context.v2`. M1c adds explicit borrowed-parameter contracts; v1 consumers must migrate using [the borrowing guide](borrowing.md). Its default budget is 16 KiB, measured in bytes including the final newline. `--max-bytes` accepts 1 through 1048576; oversize output produces `E0502` rather than truncated facts. Byte limits are not tokenizer-specific token counts.

| Field | Meaning |
| --- | --- |
| `source_hash` | SHA-256 of the exact UTF-8 source, including comments and whitespace |
| `compiler_hash` | SHA-256 over a canonical list of compiler module names and their SHA-256 hashes |
| `bootstrap_runtime` | Python implementation/version and Unicode database version |
| `profile`, `target`, `schema` | Language subset, C11 hosted/freestanding context profile, and context format version |
| `formatter_profile` | Added in M1b: the canonical layout profile, included in the cache identity |
| `symbol`, `include_body` | The request's selection and optional implementation-text inclusion |
| `cache_key` | SHA-256 over the preceding identity fields; a cache identifier, not an authenticity proof |
| `functions`, `records` | Checked selected function contracts and relevant record schemas |
| `dependencies` | Direct callees' contracts; not an unlimited transitive dependency closure |
| `callers` | Names of functions in this source file that directly call the selected function |
| `validation` | `frontend-only`: parsing, types, and the prototype's move/borrow rules passed |

`--symbol` selects a function or record. Omit it to request all declarations, subject to the same budget. `--include-body` adds the selected functions' original text as `untrusted_source_text`; comments in that field are source data and do not authorize tool actions. Comments are omitted from ordinary context facts.

`--expect-source-hash HASH` rejects a context request for a changed revision with `E0501`. It does not implement atomic editing or prevent a later filesystem race. A future edit API needs a separate compare-and-swap operation. Context does not expose ABI layout, infer platform permissions, authenticate its recipient, persist a cache, or control provider prompt caching.

## Structured diagnostics

`check --json` returns `{ "schema": "talven.diagnostics.v1", "ok": true|false, "diagnostics": [...] }`. Exit status is zero on success and one on failure. The prototype reports the first error. Ranges use zero-based lines and UTF-16 code-unit characters, shared with the LSP.

| Code | Category |
| --- | --- |
| E0001 / E0002 | Lexical / syntax error |
| E0005 | Input, token, syntax-depth, or parser-recursion limit |
| E0101 / E0102 | Unknown / duplicate name |
| E0201 / E0202 | Type mismatch / integer literal range |
| E0203 / E0204 | Arguments or fields / unsupported type operation |
| E0205 / E0206 | Missing return / unreachable statement |
| E0301 | Use after a possible move |
| E0302 / E0303 | Conflicting active loan / missing mutation permission |
| E0304 / E0305 | Reference escape or missing explicit reborrow / unsupported borrow or mutation place |
| E0401 / E0402 / E0403 | Invalid native entry / C build failure / output would replace source |
| E0501 / E0502 | Stale source / context byte budget |
| E0601 / E0602 / E0603 / E0604 | Noncanonical layout / formatting output limit / unsupported in-place target / token-preservation failure; see [formatting](formatting.md) |
| E0901 | File, encoding, process-launch, or build-timeout failure |

## Editor integration

Launch `python3 -m talven lsp` through an LSP client, with the repository root available on `PYTHONPATH` or as the process working directory. No editor extension is bundled.

The stdio server supports initialization/shutdown, full document synchronization, diagnostics, hover, definition lookup, top-level document symbols, and whole-document formatting. It reads editor-supplied text and never fetches document URIs. UTF-16 positions and version checks prevent old document updates from replacing a newer in-memory model. Parsing an invalid edit clears the previous successful semantic model. Formatting returns edits for the client to apply; see [the M1b guide](formatting.md).

This is an initial LSP integration, not the planned full editor experience. Incremental parsing, completion, references/rename, semantic tokens, multi-file workspaces, and error recovery remain unimplemented. Definition/hover coverage is limited to references recorded by the checker; constructor field labels are not indexed yet.

Prototype limits: 256 KiB UTF-8 source; 16384 tokens; syntax trees at most 128 levels; LSP JSON at most 128 levels, message bodies at most 1 MiB, headers at most 8 KiB, and at most 32 open documents. These limits reduce accidental resource growth; they are not OS-level CPU or RAM quotas.

## Native and freestanding profiles

Hosted builds require `fn main() -> i32` with no parameters. They emit C11 and use a local C compiler. Python is a build-time dependency and is not embedded into the generated executable. The Talven subset introduces no language-level heap allocation or tracing GC, but the hosted executable still uses the platform's C startup, termination, and trap facilities.

~~~sh
python3 -m talven emit-c examples/vectors.tal --freestanding -o build/vectors.c
cc -std=c11 -O2 -ffreestanding -fno-builtin -c build/vectors.c -o build/vectors.o
nm -u build/vectors.o
~~~

Create `build/` first if a previous build has not created it. Freestanding emission omits the hosted `main` adapter and libc trap implementation. It declares `_Noreturn void talven_trap(void)` for the platform to provide. These commands stop at object generation. The separate [Linux execution probe](freestanding.md) supplies bounded startup/trap code and checks a linked executable without libc on the declared Linux hosts; broader startup, board support, and target-specific helper routines remain the integrator's responsibility. GCC can require memory/compiler support routines in a freestanding environment depending on emitted operations and target. [GCC C language and freestanding support](https://gcc.gnu.org/onlinedocs/gcc/Standards.html)

The historical [M1a validation](prototype-validation.md) and [M1b validation](formatting-validation.md) record earlier target results. The [M1c validation](borrowing-validation.md) records current borrow and native-ordering evidence. A target declaration alone is not verified execution.

## Why this bootstrap

Python's standard library lets the project test semantics, diagnostics, and editor/agent contracts without third-party parser dependencies. A C11 backend provides inspectable native output and a small freestanding experiment using an existing compiler. This adds a two-stage build and Python tooling overhead; it does not demonstrate final compiler throughput, a stable ABI, or competitive LSP latency. Production bootstrap and backend choices remain open. The frontend/backend boundary allows a later implementation to reuse the conformance cases and versioned interfaces.

The LSP subset follows the [official LSP specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/). Compiler and context checks do not replace independently enforced process, filesystem, network, build, or release permissions.
