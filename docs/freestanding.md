# Linux execution without libc

Status: a bounded experiment using the existing freestanding C emitter. The [probe script](../scripts/check-freestanding.py) links and runs a small Talven program with explicit Linux startup and trap handling on native Linux x86-64 or ARM64. This is not a board port, stable foreign ABI, or general runtime. See [Proposal 0007](proposals/0007-freestanding-linux-execution.md) and the [actual validation record](freestanding-validation.md).

## Run the experiment

From the repository root, on the declared Linux host, with Python 3.11+, a C11 compiler named `cc`, and GNU `nm`, `readelf`, and `size`:

~~~sh
python3 scripts/check-freestanding.py --out build/freestanding-check --expect-arch aarch64
~~~

Use `--expect-arch x86_64` on an x86-64 host. Omit that option to use the actual supported host architecture. There is no automatic cross-compilation or emulation mode. Unsupported hosts, missing tools, mismatched architectures, build failures, timeouts, or malformed inspection output fail explicitly. The output directory must be new; existing evidence is never overwritten.

The directory retains `report.json`, input and generated source, object files, executables, and command evidence. The report identifies the host, toolchain, flags, compiler/source hashes, actual exits, and measured binary sizes. Use the recorded inputs and toolchain to repeat the experiment. Hashes identify bytes; they do not promise identical binaries across compiler/linker versions or authenticate untrusted artifacts.

## Program and independent checks

The [Talven program](../experiments/freestanding/probe.tal) contains checked scalar arithmetic and a mutable counter. Its `ordered` function passes an initial field read and two mutations as arguments to `pack`, exercising source-order evaluation, shared/exclusive borrowing, and explicit reborrowing. It has no hosted `main` function.

A separate C driver compares full i32 results against independent expected values. It tests positive, negative, zero, and boundary arithmetic inputs, plus several counter inputs. The driver and generated Talven C are compiled separately with link-time optimization disabled, so the driver cannot replace calls with a known result during compilation. Successful checks return zero; mismatches return one. Full integer comparisons avoid operating-system exit-code truncation.

Eight additional executables exercise overflowing addition, subtraction, multiplication, and negation, zero-divisor division/remainder, and `INT32_MIN / -1` or `% -1`. Each must reach the supplied `talven_trap`, which exits with the dedicated status **97**. Returning normally produces status one; an unrelated crash or signal does not count as a correct trap. The normal check and eight trap cases run at both `-O0` and `-O2`: **18 executions** for a complete run.

## Explicit startup and dependency boundary

The [x86-64 startup](../experiments/freestanding/start-x86_64.S) and [ARM64 startup](../experiments/freestanding/start-aarch64.S) align the stack, call the C driver's `talven_probe`, and exit through a Linux system call. They also provide the trap entry. These files contain no allocator, library calls, file/network operations, or additional system calls. Register conventions follow [Linux syscall documentation](https://man7.org/linux/man-pages/man2/syscall.2.html); exit numbers follow the kernel's [x86-64 syscall table](https://github.com/torvalds/linux/blob/master/arch/x86/entry/syscalls/syscall_64.tbl) and [generic syscall definitions](https://github.com/torvalds/linux/blob/master/include/uapi/asm-generic/unistd.h), consulted on 8 September 2026.

Compilation uses `-ffreestanding`, `-fno-builtin`, `-fno-stack-protector`, `-fno-pie`, and `-fno-lto`. Linking uses `-nostdlib -static -no-pie` with only the experiment's objects and an explicit `_start` entry. No CRT startup, libc, or libgcc is supplied. This intentionally narrow link may fail when another target or source requires compiler support routines. GCC documents that [freestanding code can still need support functions](https://gcc.gnu.org/onlinedocs/gcc/Standards.html), and that [`-nostdlib` removes standard startup and libraries](https://gcc.gnu.org/onlinedocs/gcc/Link-Options.html). Required compile-time headers are still toolchain inputs.

The generated object must expose only `talven_trap` as an undefined symbol. The linked executable must have none. ELF inspection requires the expected 64-bit little-endian executable format and machine, an entry matching `_start`, loadable segments, no interpreter/dynamic segment or dynamic dependencies, and a non-executable stack. Writable/executable load segments are rejected. This verifies the produced artifact instead of inferring the result from compiler flags alone. The tools used are documented by [GNU readelf](https://sourceware.org/binutils/docs/binutils/readelf.html).

The program uses stack values and no heap allocator. The Linux kernel still creates the process, maps the executable and initial stack, and handles exit. Removing libc does not remove that operating-system dependency. The experiment does not measure peak stack, RSS, startup latency, or a universal memory bound; recursion and stack exhaustion remain outside its guarantee. It does not disable safety checks in the Talven compiler. Existing hosted sanitizer tests remain separate because their runtime would change this dependency experiment.

## Interpreting size evidence

`file_bytes` is the executable's actual file length, including headers, symbols, padding, and other non-loaded material. GNU `size` in Berkeley format reports text (including read-only data), initialized data, and BSS classifications; see [its definition](https://sourceware.org/binutils/docs/binutils/size.html). Those section counts are not peak RAM or total process memory. The probe reports measurements for each optimization/case and supplies no unmeasured performance or token-cost claim.

The compiler and existing independent evaluation tests remain unchanged. A controlled live-agent evaluation is still required for the M1 agent gate; this experiment addresses the separate no-heap/freestanding roadmap item.
