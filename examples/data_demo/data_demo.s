	.section .data
	.balign 8
answer:
	.dword 41
	.size	answer, 8
	.section .bss
	.balign 8
scratch:
	.zero 8
	.text
	.globl	_start
_start:
	la	t0, answer
	ld	t1, 0(t0)
	addi	t1, t1, 1
	la	t2, scratch
	sd	t1, 0(t2)
	ld	a0, 0(t2)
	li	a7, 93
	ecall
