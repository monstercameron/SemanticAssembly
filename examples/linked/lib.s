	.text
	.globl	triple
	.type	triple, @function
triple:
	li	t0, 3
	mul	a0, a0, t0
	ret
