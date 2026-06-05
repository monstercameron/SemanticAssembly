	.section .rodata
stdoutMessage:
	.ascii "Hello from semantic assembly!\n"
	.text
	.globl	_start
_start:
	li	a7, 64
	li	a0, 1
	la	a1, stdoutMessage
	li	a2, 30
	ecall
	li	a7, 93
	li	a0, 0
	ecall
