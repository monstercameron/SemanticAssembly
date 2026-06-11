	.text
	.globl	fib
fib:
	addi	sp, sp, -32
	sd	ra, 24(sp)
	sd	s0, 16(sp)
	sd	s1, 8(sp)
	li	t0, 2
	blt	a0, t0, .Lepilogue
	mv	s0, a0
	addi	a0, s0, -1
	call	fib
	mv	t1, s0
	mv	s1, a0
	addi	a0, t1, -2
	call	fib
	add	a0, s1, a0
.Lepilogue:
	ld	ra, 24(sp)
	ld	s0, 16(sp)
	ld	s1, 8(sp)
	addi	sp, sp, 32
	ret
