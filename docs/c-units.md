# Hosted C function units

Status: implemented reference lowering experiment under [Proposal 0020](proposals/0020-hosted-function-c-units.md), emission profile `hosted-c11-units-v1`. This is a foundation for investigating native object reuse, not an incremental compiler or new build mode.

~~~sh
python3 -m talven emit-c-units examples/hello.tal --console
~~~

The command reads and fully checks a regular source file, then prints deterministic `talven.c-units.v1` JSON. It never writes source/unit files, invokes a C compiler or executes a program. There is no freestanding mode. Failures return the normal diagnostic JSON envelope and status 1; unknown options are usage errors. The same hosted main/console requirements as `emit-c` apply, including console calls in uncalled functions.

The receipt contains `source_hash`, `compiler_hash`, language/emission profiles, the console selection and an ordered `units` list. Each unit has `id`, exact `c` text and `c_hash`. `fn:NAME` defines that function; `entry` defines the C main wrapper. A language function named `entry` cannot collide. All current record layouts and function declarations repeat in every unit. Only needed arithmetic/trap/console definitions appear, retaining static helper linkage. Function-local temporary numbering makes unrelated bodies independent of earlier temporary counts.

Consumers can compile each unit separately and link all objects with the same trusted C11 toolchain, target and compatible ABI settings. This command does not provide that driver. Do not concatenate the unit texts into one translation unit: repeated type/helper definitions are intended for separate objects. No public C FFI or package ABI is established. Separate translation units can change optimizer decisions and final binary costs; no speedup or runtime performance equality is claimed.

Comment/whitespace and unrelated body edits can leave a unit byte-identical. Every unit conservatively includes all global declarations: signature, parameter-name, record-layout and declaration-order changes affect unit text. This is not a complete build-cache identity. Preprocessing/header changes, target/compiler/options, toolchain dependencies, object corruption and publication freshness must be handled before any reuse is permitted. Default build/dev paths still compile the ordinary whole-program C in full. The separate [opt-in native watcher](native-watch.md) tests private object reuse with fresh checking, preprocessing and linking.

The experiment permits at most 256 functions plus entry, 16 MiB total C text and 16 MiB compact receipt. Oversized results return `E0005`, with no partial successful units. Existing source/token/depth limits apply. Hashes identify bytes; they do not authenticate sources, running compiler code, executables or third-party tools. The separate [prepared-unit command](preprocessed-units.md) now freezes a fresh trusted preprocessing pass; it still does not compile objects or provide a reuse cache.

Eleven focused tests verify stable/conservatively invalidated units, helper selection, bounded receipts and no execution. Independent C drivers verify full i32 values and by-value record results; native tests cover scalar stores, forward calls/recursion, checked aborts/short-circuit and exact UTF-8/NUL output/static views. The three borrowing fixtures execute as separate objects with ASan/UBSan at both `-O0` and `-O2`. The ordinary emitter continues to produce byte-identical C to the Rust experiment across the existing differential corpus. CI repeats the reference/native checks on its declared Linux hosts; local macOS observations do not add a supported target profile.
