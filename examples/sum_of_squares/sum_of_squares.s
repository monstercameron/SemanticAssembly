	.section .rodata
newline:
	.ascii "\n"
	.size	newline, 1
	.text
	.globl	_start
_start:
	li	a0, 10
	call	sum_of_squares
	call	print_int
	li	a7, 64
	li	a0, 1
	la	a1, newline
	li	a2, 1
	ecall
	li	a7, 93
	li	a0, 0
	ecall
sum_of_squares:
	li	t0, 0
	li	t1, 1
.Lsoscond:
	blt	a0, t1, .Lsosdone
	mul	t2, t1, t1
	add	t0, t0, t2
	addi	t1, t1, 1
	j	.Lsoscond
.Lsosdone:
	mv	a0, t0
	ret
print_int:
	addi	sp, sp, -32
	mv	t0, a0
	li	t1, 10
	addi	t2, sp, 32
	addi	t4, sp, 32
.Lpiloop:
	remu	t3, t0, t1
	addi	t3, t3, 48
	addi	t2, t2, -1
	sb	t3, 0(t2)
	divu	t0, t0, t1
	bnez	t0, .Lpiloop
	li	a7, 64
	li	a0, 1
	mv	a1, t2
	sub	a2, t4, t2
	ecall
	addi	sp, sp, 32
	ret
