# GPU and platform design

Status: long-term requirements with staged proposed backends. No platform support is implemented yet.

## Host and device responsibilities

The host language controls device selection, allocation, transfer, submission, synchronization, and resource budgets. Device kernels execute under a restricted set of types, operations, address spaces, and synchronization rules.

Represent CPU memory and device memory explicitly. Distinguish owned allocations from borrowed views and from resources whose work is still in flight.

A submitted operation must retain or borrow the buffers it uses until completion is established. Dropping or cancelling a host task must not free memory a GPU may still access.

## Memory and transfers

Expose allocation size, capacity, alignment, device, and applicable memory domain. Make upload, download, synchronization, and readback visible.

On discrete GPUs, transfers between host RAM and device memory can dominate a workload. Unified memory or shared physical memory does not eliminate synchronization or guarantee that all access patterns are efficient.

Zero-copy exchange requires compatible devices, layouts, ownership, and synchronization. An interchange mechanism cannot guarantee zero-copy across every runtime or hardware combination.

Track resource quotas and in-flight work. Handle allocation failures, device loss, queue failures, and cancellation explicitly.

## Backend strategy

| Candidate backend family | Intended role | Important boundary |
| --- | --- | --- |
| NVIDIA CUDA | Native integration with NVIDIA compute libraries and devices | Vendor runtime, driver, architecture, and API compatibility |
| Apple Metal | Apple GPU compute and system integration | Apple platform APIs and applicable device capabilities |
| AMD ROCm / HIP | AMD-oriented compute integration where supported | Supported hardware, OS, runtime, and toolchain combinations |
| Vulkan compute | A possible portable compute surface | Available extensions and capability differences |
| Additional vendor APIs | Specialized accelerators and future hardware | Separate support and validation decisions |

These are candidate directions, not a promise of complete compatibility. Validate native host bindings before attempting a universal kernel compiler.

Offer a documented portable kernel subset plus explicit vendor-specific access. Common semantics do not imply identical performance or access to every feature on every GPU.

GPU kernels must not assume arbitrary host-language features, OS access, unbounded allocation, or compatibility with arbitrary npm or Python code.

## Concurrency and correctness

CPU task completion and GPU operation completion are distinct events. A device future or completion handle should make that relationship explicit.

Track buffer access across queues and submitted operations. Host ownership analysis can help, but correctness inside arbitrary kernels needs device-specific rules and verification.

Provide explicit synchronization primitives and reject unsupported capabilities. Avoid silently weakening barriers, precision, or memory-order assumptions on another backend.

## Deployment range

| Proposed profile | Initial direction | Work still required |
| --- | --- | --- |
| Hosted native | Linux ARM64 and Linux x86-64 | Compiler backend, ABI, linking, OS integration, test hardware |
| Desktop platforms | macOS and Windows after the first native subset | Platform ABIs, SDKs, linker support, libraries, CI |
| Freestanding | A small no-heap program on one selected board or emulator | Startup, linker script, panic behavior, interrupts, board support |
| GPU host application | One backend and workload first | Bindings, driver/runtime matrix, buffer lifetime validation |
| Portable device kernels | A restricted subset after native integration | Kernel IR, lowering, capability checks, cross-device correctness |

A Cortex-M experiment, if selected, is an additional ARM32 microcontroller target, not evidence that an ARM64 executable runs on a microcontroller.

An instruction-set backend alone does not provide an operating system, runtime, driver, or board support package. Publish a precise target matrix as implementations arrive.

## Early proof

Use the same small computation or parser on the initial ARM64 and x86-64 hosts. Attempt an early freestanding/no-heap variant to expose hidden runtime assumptions.

For GPU work, start with an explicitly allocated buffer and a simple compute operation. Test transfer behavior, correctness, completion, cancellation, resource exhaustion, and device loss handling before adding a broad abstraction layer.

