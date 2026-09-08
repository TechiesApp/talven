# Proposal 0007: Freestanding Linux execution

- Status: Draft
- Author(s): Talven contributors
- Requirements affected: R09, R10, R11, R15, R16
- Decisions affected: D07, D09, D10, new D32
- Discussion: Pull request introducing this proposal

## Problem

The reference compiler emits freestanding C and has an object-symbol test, but that evidence stops before startup, linking, and execution. A working object does not establish that checked arithmetic and borrowing can run without libc or an allocator, or identify the remaining platform obligations.

## Proposal

Add a reproducible Linux x86-64/ARM64 probe using the existing compiler unchanged. Compile a small checked-arithmetic and ordered-borrowing program, a separate independent C driver, and minimal per-architecture startup. Link only these objects without standard startup, libc, libgcc, or a dynamic loader. Provide `talven_trap` through a dedicated Linux exit status.

Run normal-result and eight arithmetic-trap cases at `-O0` and `-O2`. Compare full scalar results in C, and require the precise trap status instead of accepting any nonzero exit. Inspect the generated object's dependencies and the final ELF before execution. Reject an unexpected runtime dependency, interpreter/dynamic segment, wrong target or entry, executable stack, or writable/executable load segment.

Archive source, tool identities/hashes, compiler settings, generated files, commands, exits, and measured file/section sizes in a fresh output directory. Failed and partial runs must retain their available evidence and cannot become passes or skips. Keep this workflow separate from model evaluation and existing hosted sanitizer execution.

## Examples

The [guide](../freestanding.md) gives the executable command and links the program/startup files. The example remains a Linux process whose only handwritten system call is exit. It is not bare-metal startup or a promise that every freestanding Talven program links without target support routines.

## Alternatives considered

- Relying on `-ffreestanding` and object generation alone misses linking and startup dependencies.
- Statically linking libc would remove the dynamic loader while retaining the library/runtime being investigated.
- Adding a board, linker script, interrupts, and device drivers would broaden the scope before the existing subset's runtime assumptions are known.
- Changing the compiler or exposing a stable foreign ABI is unnecessary for this probe. Generated `tv_f_*` symbols remain an internal test interface.

## Costs and implications

- Agent context: the language guide gains a scoped execution example; no syntax or provider protocol changes and no token-savings claim.
- Runtime and memory: explicit startup/trap code and stack values; actual executable/section sizes are recorded. These are not peak-memory, bounded-stack, or latency measurements.
- Security: no libc or allocator is linked into these artifacts, but the compiler, inspection tools, and Linux host remain trusted. This does not create a sandbox or prove all-target safety.
- Targets: only native Linux x86-64 and ARM64 with the exercised toolchain/flags. Other CPUs, OSes, boards, and emulation require separate evidence.
- Interoperability: C drivers and assembly meet existing platform conventions for the experiment; no public FFI or stable layout contract is added.

## Evaluation

Verify normal arithmetic/ordered mutation and exact trap behavior through actual executions. Check negative inspection cases for malformed symbols/ELF/size data, target mismatch, dynamic dependencies, and bad segment permissions. Require a fresh report directory and retain partial failures. Run all existing tests, formatting, hosted sanitizer checks, and documentation validation. CI exercises the probe on both declared Linux architectures; only completed executions and observed sizes count as evidence.

The [validation record](../freestanding-validation.md) identifies actual runs, toolchains, checks, and measured sizes without extending those results to untested targets.

## Unresolved questions

Board-specific startup, memory maps, stack limits, allocation/resource cleanup, foreign ABI design, production toolchain choices, and runtime costs for larger programs remain open. The M1 live-agent evidence gate also remains open under the separate evaluation workflow.
