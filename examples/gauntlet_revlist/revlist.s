	.text
	.globl	revlist
revlist:
	li	t0, 0
.Lreversecheck:
	beqz	a0, .Lreversedone
	ld	t1, 8(a0)
	sd	t0, 8(a0)
	mv	t0, a0
	mv	a0, t1
	j	.Lreversecheck
.Lreversedone:
	mv	a0, t0
	ret
	.globl	sumlist
sumlist:
	li	t0, 0
	li	t1, 1
.Lsumcheck:
	beqz	a0, .Lsumdone
	ld	t2, 0(a0)
	mul	t2, t2, t1
	add	t0, t0, t2
	addi	t1, t1, 1
	ld	a0, 8(a0)
	j	.Lsumcheck
.Lsumdone:
	mv	a0, t0
	ret
