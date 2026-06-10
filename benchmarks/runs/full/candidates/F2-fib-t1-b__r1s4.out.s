	.text
	.globl	fib
fib:
	addi	sp, sp, -48
	sd	ra, 40(sp)
	sd	s0, 32(sp)
	sd	s1, 24(sp)
	li	t0, 2
	blt	a0, t0, .Lepilogue
	mv	s0, a0
	addi	a0, s0, -1
	call	fib
	mv	s1, a0
	addi	a0, s0, -2
	call	fib
	add	a0, s1, a0
.Lepilogue:
	ld	ra, 40(sp)
	ld	s0, 32(sp)
	ld	s1, 24(sp)
	addi	sp, sp, 48
	ret
