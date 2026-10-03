# Hosted C11 scalar exports

Status: experimental reference/native emission under [Proposal 0036](proposals/0036-hosted-scalar-c-api.md). This creates a named C library unit and selected scalar header. It does not add Talven imports, foreign pointers or a package manager.

## Generate two named units

Run from the repository root. Neither compiler invokes a C compiler or writes source when generating these JSON receipts:

~~~sh
mkdir -p build/c-api
python3 -m talven emit-c-api examples/c-api-math.tal --module math --export adjust --export accepts > build/c-api/math.json
python3 -m talven emit-c-api examples/c-api-offset.tal --module offset --export adjust > build/c-api/offset.json
python3 - <<'PY'
import json
from pathlib import Path
root = Path('build/c-api')
for name in ('math', 'offset'):
    receipt = json.loads((root / (name + '.json')).read_text())
    (root / (name + '.h')).write_text(receipt['header'])
    (root / (name + '.c')).write_text(receipt['c'])
PY
~~~

The standalone native command has the same options, for example:

~~~sh
experiments/native-compiler/target/release/talven-native emit-c-api examples/c-api-math.tal --module math --export adjust --export accepts
~~~

No `main` is required. C/header bytes and interface facts match the reference in differential fixtures; producer compiler identities differ. Each receipt includes exact source/C/header SHA-256 identities and frontend-only validation. Compile and independently execute the actual emitted unit to obtain native correctness evidence.

## Call from a C host

The generated headers declare `talven_m4_math_f_adjust`, `talven_m4_math_f_accepts`, and `talven_m6_offset_f_adjust`. The length-framed module prefix avoids ambiguous names; both units can use private `helper`/`adjust` functions without symbol collisions.

Save this independent caller as `build/c-api/driver.c`:

~~~c
#include "math.h"
#include "offset.h"
#include <errno.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    char *end;
    errno = 0;
    long parsed = strtol(argv[1], &end, 10);
    if (errno == ERANGE || end == argv[1] || *end ||
        parsed < INT32_MIN || parsed > INT32_MAX) return 2;
    int32_t value = (int32_t)parsed;
    int32_t bounded = value < -1000 ? -1000 : value > 1000 ? 1000 : value;
    int32_t expected = bounded * 2 + 1;
    if (talven_m4_math_f_adjust(value) != expected) return 1;
    if (talven_m4_math_f_accepts(value) != (value >= -1000 && value <= 1000)) return 1;
    if (talven_m6_offset_f_adjust(expected) != expected / 2 + 7) return 1;
    return 0;
}
~~~

Compile explicitly with a trusted host C11 compiler and run it:

~~~sh
cc -std=c11 -O2 -fno-lto -Wall -Wextra -Werror -pedantic-errors build/c-api/math.c build/c-api/offset.c build/c-api/driver.c -o build/c-api/check
build/c-api/check -2147483648
build/c-api/check 2147483647
~~~

The driver uses libc `strtol` and checks range, consumed input and `errno` before narrowing. The independent tests also reject invalid/out-of-range inputs, check intermediate scalars and bools, link case-distinct namespace guards, and exercise overflow traps. Both compilers' emitted units execute under ASan/UBSan at O0/O2 in the required target CI.

## Interface limits

Exports permit only `i32`/`bool` parameters and results, represented by host C `int32_t`/`bool`. There are no record/text/borrow exports, foreign imports, escaping resource contracts or callbacks. Internally, the entire source retains normal checked records/borrows/text rules. Export order is deterministic; parameter order is significant. Module names are 1–64-byte ASCII identifiers, with 1–128 distinct function exports. The default complete JSON budget is 16 MiB; `--max-bytes` accepts 1 byte through that limit. E1001 reports invalid interface requests; E1002 reports invalid/exceeded budgets. Existing source and console failures retain their codes. Failure envelopes are outside the requested success budget.

Generated units use hosted trapping arithmetic; overflow/divide errors abort rather than returning a foreign error value. Console use anywhere in a unit requires `--console`. C hosts must use compatible compiler/target ABIs and respect declared types. Choosing artifact filenames, compiler flags, separate linking and source lifetime is the host's responsibility; compiler generation is read-only and identities do not authenticate binaries. C code is trusted native code, with no sandbox guarantee.

A separate reference [local-module companion](modules.md) now provides bounded source imports; project C API emission and native graph resolution remain open. Stable binary packaging, broader C-library ownership/error bindings and additional native wrappers also remain open. Call/bridge overhead, memory and agent benefits are unmeasured.
