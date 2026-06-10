	.text
	.globl	fib
fib:
	addi	sp, sp, -32
	sd	ra, 24(sp)
	sd	s0, 16(sp)
	li	t0, 2
	blt	a0, t0, .Lepilogue
	mv	s0, a0
	addi	a0, s0, -1
	call	fib
	sd	a0, 0(sp)
	addi	a0, s0, -2
	call	fib
	ld	t2, 0(sp)
	add	a0, t2, a0
.Lepilogue:
	ld	ra, 24(sp)
	ld	s0, 16(sp)
	addi	sp, sp, 32
	ret
