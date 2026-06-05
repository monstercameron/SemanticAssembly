	.globl	triple
	.type	triple, @function
	.text
	.globl	_start
_start:
	li	a0, 14
	call	triple
	li	a7, 93
	ecall
