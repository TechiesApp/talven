# Proposal 0036: Hosted scalar C API units

- Status: Implemented reference/native experiment; broader design acceptance remains open
- Author(s): Talven contributors
- Requirements affected: R08, R09, R11, R12, R13, R14, R15, R24
- Decisions affected: D64 (proposed), D11, D41
- Discussion: the pull request introducing this proposal and implementation

## Problem

Talven has no explicit foreign interface or modules. Native tests already call compiler-private symbols, but that test machinery is not a public ABI. Begin with an explicit scalar export boundary and separately compiled named C units, independently exercised by C callers and one host-library workload. This is a step toward module/interoperability contracts; Talven import syntax and foreign calls remain separate.

## Contract

Both compilers implement `emit-c-api SOURCE --module NAME --export FUNCTION [--export FUNCTION ...] [--console] [--max-bytes N]`. Perform complete current frontend analysis, validate the interface request and return a read-only `talven.c-api.v1` JSON receipt. Emit a hosted library translation unit without a C `main` wrapper or a required Talven entry. Keep default executable/freestanding/unit emission unchanged. A Talven function named `main` is an ordinary private library function in this mode.

`hosted-c11-scalars-v1` exports only initialized copy values: Talven `i32` uses C `int32_t` and Talven `bool` uses C11 `bool`. Parameters retain names/order; results use the declared scalar type. Zero-parameter prototypes explicitly use `void`. Reject records, borrowed records and static text at this external boundary, even when they are valid inside the complete checked unit. No foreign ownership, allocator, buffer lifetime, callback, foreign exception or pointer contract is implied.

A module name is an ASCII identifier of 1 through 64 bytes. Require 1 through 128 distinct exported function names, sort exports lexically, and reject missing/unknown functions. Let `prefix` be `m` + the decimal module byte length + `_` + the module. Public names are `talven_PREFIX_f_FUNCTION`; compiler-private function/record tokens are rewritten to `tv_PREFIX_f_FUNCTION` and `tv_PREFIX_s_RECORD`. Length framing avoids collisions between module `a_b`/function `c` and module `a`/function `b_c`. Header guards preserve module case. Local fields, temporaries and static arithmetic/console helpers retain their private per-unit names. Internal externally visible symbols are not supported public contracts; this increment does not implement symbol hiding or shared-library packaging.

Generate wrappers with the explicit public signature and a direct call to the checked internal function. The header declares only the selected public functions and includes `stdint.h`/`stdbool.h`. Generated text literals are numeric byte arrays and source comments are omitted, so namespace rewriting touches complete compiler-owned identifiers without interpreting arbitrary source text. Emit every checked declaration/body, including unexported functions. Console use anywhere in the unit still requires explicit hosted POSIX `--console`.

The receipt contains `schema`, `abi_profile`, `language_profile`, current producer `compiler_hash`, exact `source_hash`, hosted `target`, `validation: frontend-only`, `module`, console selection, ordered `exports`, exact `header`/`c` and their SHA-256 hashes. Reference and native compiler identities are distinct and use their respective snapshot/context identity algorithms; artifacts/interface fields match across implementations. The receipt is neither a C compilation result nor an authenticated binary attestation.

Budgets default to 16 MiB and accept 1 byte through 16 MiB, counting the implementation's complete UTF-8 JSON and final newline. E1001 rejects module/export/boundary requests; E1002 rejects invalid/exceeded budgets. No receipt truncation occurs; error envelopes are outside the success budget. Existing input/depth/token/source/type/borrow and console diagnostics apply. CLI usage errors retain status 2, controlled diagnostics status 1 and successful receipts status 0. Source validation precedes interface-request checks. JSON serializers may encode escapes differently; compare exact decoded artifacts, not identical receipt bytes.

## Implemented examples

The [C API guide](../c-api.md) demonstrates generation from [math](../../examples/c-api-math.tal) and [offset](../../examples/c-api-offset.tal), separate C compilation and a caller that uses libc `strtol`. These are implemented examples with preserved input checks; they do not introduce Talven import syntax. The C host decides when/how to call each unit and validates native-library results before converting to `int32_t`.

## Alternatives

Publishing all existing `tv_f_` symbols would accidentally freeze compiler-private conventions and cause collisions when unrelated units reuse names. Exposing records/text first would require ownership/layout/lifetime rules not yet chosen. Adding source-level imports, foreign pointers or a package manager now would conflate separate design questions. Explicit scalar C exports plus independently compiled named units establish a small concrete boundary while those decisions remain open.

## Costs, trust and targets

The compiler constructs C/header/JSON in its existing heap; final byte checks are not a general resource quota. Wrappers perform one ordinary typed call; optimization/inlining and actual call/copy/build/memory costs remain unmeasured. No allocator, new Talven runtime, dynamic loader or mandatory package dependency is added. The host C compiler/linker and libraries remain separately trusted tools selected by the applying host.

Checked arithmetic retains trapping overflow/divide semantics inside the unit, with hosted `abort`; exported scalar calls do not convert traps to recoverable errors. A C caller must respect its selected platform C ABI and declared scalar types. Native in-process C code is not sandboxed or repaired by a typed header. This profile provides no C++/Rust/native-binary compatibility promise, cross-architecture ABI, foreign callbacks, exception containment, package resolution or Talven foreign-import capability.

The existing Linux x86-64/aarch64 CI compilers execute C consumers; macOS supplies local evidence. General OS/compiler/library support is not inferred from C11 syntax. The libc workload exercises one concrete host API and explicit range/end/errno validation, not broad registry compatibility. The native input path retains its previously inspected OS/architecture limits.

## Evaluation and open work

Both compilers must produce exact matching C/header bytes, artifact hashes and interface facts for accepted selected functions in the differential corpus; compiler identity differs. Existing default C emission, diagnostics/context/layout and independent execution remain gates. Standalone tests cover module/namespace/header-guard collisions, C-keyword source names, bool/zero-argument interfaces, invalid boundary types, byte-budget edges, console selection and unchanged input files.

Independent drivers separately compile/link two units with identical private function names, consume libc-parsed inputs including i32 boundaries, verify independent expected scalar/bool results and reject invalid/out-of-range parses. ASan/UBSan executions run at O0/O2. Exported checked arithmetic must still trap on overflow. Required Linux jobs run these reference/native fixtures without skips.

This evidence does not measure bridge overhead or complete M3. Native imports, source-level modules, stable object/shared-library packaging, ownership/error contracts, reviewed C-library bindings and an additional foreign native wrapper remain open. Preserve independent acceptance and propose those contracts before expanding the interface.
