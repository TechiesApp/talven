/* Linux x86-64 process entry for this probe, not a general runtime or ABI. */
.equ LINUX_EXIT, 60
.equ TRAP_STATUS, 97

.text
.p2align 4
.global _start
.type _start, @function
_start:
    xor %ebp, %ebp
    and $-16, %rsp
    call talven_probe
    mov %eax, %edi
    mov $LINUX_EXIT, %eax
    syscall
    ud2
.size _start, .-_start

.p2align 4
.global talven_trap
.type talven_trap, @function
talven_trap:
    mov $TRAP_STATUS, %edi
    mov $LINUX_EXIT, %eax
    syscall
    ud2
.size talven_trap, .-talven_trap

.section .note.GNU-stack,"",@progbits
