# Talven language reference

Profile: `m1-static-text-v1` (compiler `0.4.0-dev`). This page is the complete, normative summary of what the reference compiler accepts. It omits rationale, tooling, and validation evidence; follow the links at the end for those. Anything not listed here is not supported.

## Source text

- Files are UTF-8, at most 256 KiB and 16384 tokens; syntax nests at most 128 levels.
- Whitespace is ASCII space, tab, and LF. CR is allowed only as part of CRLF.
- A lone CR, any other whitespace or control character, and bidirectional controls (U+202A–U+202E, U+2066–U+2069) are E0001 anywhere, including comments. Inside a text literal, raw control characters are E0006 instead.
- `//` starts a comment that runs to the end of the line. There are no block comments.
- Identifiers are ASCII: a letter or `_`, then letters, digits, or `_`.
- Reserved words: `fn struct let mut return if else true false`. The names `i32`, `bool`, `str`, and `print` cannot be declared.
- Integer literals are decimal digits only (leading zeros allowed); `-` is a separate operator.

## Grammar

~~~ebnf
program        = { record | function } ;
record         = "struct", identifier, "{", field, { ",", field }, [","], "}" ;
field          = identifier, ":", ( "i32" | "bool" ) ;
function       = "fn", identifier, "(", [ params ], ")", "->", type, block ;
params         = param, { ",", param }, [","] ;
param          = identifier, ":", ( type | "&", ["mut"], record_name ) ;
type           = "i32" | "bool" | "str" | record_name ;
block          = "{", { statement }, "}" ;
statement      = "let", ["mut"], identifier, [ ":", type ], "=", expression, ";"
               | identifier, ".", identifier, "=", expression, ";"
               | "return", expression, ";"
               | "if", "(", expression, ")", block, [ "else", block ]
               | expression, ";" ;
expression     = binary ;
primary        = integer | "true" | "false" | text
               | identifier                                   (* local name *)
               | identifier, "(", [ arg, { ",", arg }, [","] ], ")"   (* call *)
               | record_name, "{", [ init, { ",", init }, [","] ], "}"
               | "(", expression, ")"
               | ( "-" | "!" ), primary
               | primary, ".", identifier ;                   (* field read *)
arg            = expression | "&", ["mut"], identifier ;
init           = identifier, ":", expression ;
~~~

`else if` is not supported; nest an `if` inside the `else` block. Every function declares its result type; there is no unit type.

## Operators

From weakest to strongest binding; all binary operators are left-associative.

| Level | Operators | Operands → result |
| --- | --- | --- |
| 1 | `\|\|` | bool → bool, short-circuit |
| 2 | `&&` | bool → bool, short-circuit |
| 3 | `==` `!=` | two `i32` or two `bool` → bool |
| 4 | `<` `>` `<=` `>=` | `i32` → bool |
| 5 | `+` `-` | `i32` → `i32` |
| 6 | `*` `/` `%` | `i32` → `i32` |
| 7 | unary `-`, `!` | `i32` → `i32`; `bool` → `bool` |
| 8 | `.field` | record field read |

Comparisons do not chain: `a == b == c` and `1 < 2 < 3` are E0002. Write `(a == b) == c`. There are no implicit conversions; `str` and records support no operators.

## Types and values

| Type | Values | Copy or move |
| --- | --- | --- |
| `i32` | −2147483648 to 2147483647 | Copies |
| `bool` | `true`, `false` | Copies |
| `str` | Immutable static UTF-8 text literal | Copies (a view of static bytes) |
| Record | Named fields of `i32` or `bool` only | Moves |

Text literals use `"…"` with escapes `\"` `\\` `\n` `\r` `\t` `\0`. Raw control characters and other escapes are E0006. `str` is allowed for locals, parameters, and results, not record fields.

Record literals must provide every field exactly once, in any order. Fields cannot be records, `str`, or references.

## Names and functions

- Functions and records share one global namespace and may be used before their declaration. Recursion is allowed.
- Locals and parameters share one namespace per function. Redeclaring or shadowing a local is E0102. Names declared in a branch do not escape it.
- Local types may be inferred; parameter and result types are explicit.
- Every reachable path must `return` the declared type (E0205). Statements after an unconditional `return` are E0206.
- An expression statement discards its value; discarding a record moves it.

## Ownership and borrowing

Records are affine: assigning, passing by value, returning, or discarding a record moves it, and a moved record cannot be used again on any path that may follow (E0301). Reading a scalar field does not move the record. A move inside a branch that returns does not affect the other branch. A move on the right side of `&&`/`||` counts as possible.

Borrows exist only as call arguments and last until that call returns:

- `&name` is a shared borrow and `&mut name` is an exclusive borrow of a named record or a borrowed parameter.
- A parameter typed `&R` can read fields. A parameter typed `&mut R` can read and assign fields.
- References cannot be stored in locals, fields, or results (E0304).
- To pass a borrowed parameter on, reborrow explicitly: `read(&p)` or `add(&mut p, 1)`. `read(p)` is rejected, and a shared parameter cannot be reborrowed as `&mut`.
- Shared borrows may overlap each other. An exclusive borrow overlaps nothing: no other borrow, read, write, or move of that record while it is active (E0302).

Mutation:

- `name.field = value;` requires a `let mut` record owner or an `&mut` parameter (E0303).
- `let mut` is only allowed for records (E0305). There is no reassignment of whole bindings.
- To mutate an owned by-value parameter, move it into a `let mut` local first.

## Evaluation

- Operands, call arguments, and record initializers evaluate left to right.
- A loan starts when its argument is evaluated. It stays active while later arguments evaluate and ends when the call returns, so `f(&mut r, r.x)` is E0302 but `f(r.x, g(&mut r))` is allowed.
- In a field assignment, the right side is evaluated first, then stored.
- `+ - * unary-` trap on overflow. `/` and `%` trap on a zero divisor and on `-2147483648 / -1` or `% -1`. Division truncates toward zero; `%` takes the dividend's sign.
- Hosted traps abort the process. Recursion depth is not bounded.

## Programs and output

- A native program needs `fn main() -> i32` with no parameters (E0401). Its result becomes the process exit status, which the host may truncate.
- `print(text: str) -> i32` writes the bytes of `text` to stdout with no added newline. It returns `0` on success and `1` if a write fails; earlier bytes may already be visible.
- Programs that call `print` must be built with `--console`; freestanding builds reject it (E0404).

## Example

~~~text
struct Counter {
    value: i32
}

fn read(c: &Counter) -> i32 {
    return c.value;
}

fn add(c: &mut Counter, amount: i32) -> i32 {
    c.value = c.value + amount;
    return c.value;
}

fn main() -> i32 {
    let mut counter = Counter { value: 40 };
    add(&mut counter, 2);
    if (read(&counter) == 42) {
        return print("ok\n");
    }
    return 1;
}
~~~

## Diagnostics

The checker reports the first error with a code:

| Code | Meaning |
| --- | --- |
| E0001 / E0002 | Lexical / syntax error |
| E0005 | Size, token, or nesting limit |
| E0006 | Invalid text literal |
| E0101 / E0102 | Unknown / duplicate or shadowed name |
| E0201 / E0202 | Type mismatch / integer literal out of range |
| E0203 / E0204 | Wrong arguments or record fields / unsupported operation or field type |
| E0205 / E0206 | Missing return / unreachable statement |
| E0301 | Use after a possible move |
| E0302 / E0303 | Conflicting active borrow / missing mutation permission |
| E0304 / E0305 | Stored, returned, or missing reborrow / unsupported borrow or `let mut` place |
| E0401 / E0404 | Invalid `main` / console option missing or incompatible |

## Not in this profile

Loops, general reassignment, arrays, heap allocation, string operations, modules or imports, generics, closures, concurrency, input, file access, and foreign calls. The [prototype guide](prototype.md) (tooling and contracts), [borrowing guide](borrowing.md) (rationale and lowering), and [text and console guide](text-console.md) (output details) describe the same profile in more depth.
