/* Linux AArch64 process entry for this probe, not a board startup/runtime. */
.equ LINUX_EXIT, 93
.equ TRAP_STATUS, 97

.text
.p2align 2
.global _start
.type _start, %function
_start:
    mov x29, xzr
    mov x9, sp
    and x9, x9, #-16
    mov sp, x9
    bl talven_probe
    mov x8, #LINUX_EXIT
    svc #0
    brk #0
.size _start, .-_start

.p2align 2
.global talven_trap
.type talven_trap, %function
talven_trap:
    mov w0, #TRAP_STATUS
    mov x8, #LINUX_EXIT
    svc #0
    brk #0
.size talven_trap, .-talven_trap

.section .note.GNU-stack,"",%progbits
