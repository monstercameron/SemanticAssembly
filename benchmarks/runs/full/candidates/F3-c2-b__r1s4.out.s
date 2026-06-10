	.text
	.globl	qsort64
qsort64:
	addi	sp, sp, -32
	sd	ra, 24(sp)
	sd	s0, 16(sp)
	sd	s1, 8(sp)
	sd	s2, 0(sp)
	bge	a1, a2, .Lepilogue
	slli	t0, a2, 3
	add	t1, a0, t0
	ld	t2, 0(t1)
	addi	t3, a1, -1
	mv	t4, a1
.Lpartitioncheck:
	bge	t4, a2, .Lpartitiondone
	slli	t0, t4, 3
	add	t1, a0, t0
	ld	t5, 0(t1)
	blt	t2, t5, .Ladvancescan
	addi	t3, t3, 1
	slli	t0, t3, 3
	add	t6, a0, t0
	ld	t0, 0(t6)
	sd	t5, 0(t6)
	sd	t0, 0(t1)
.Ladvancescan:
	addi	t4, t4, 1
	j	.Lpartitioncheck
.Lpartitiondone:
	addi	t0, t3, 1
	slli	t1, t0, 3
	add	t1, a0, t1
	ld	t5, 0(t1)
	slli	t6, a2, 3
	add	t6, a0, t6
	sd	t5, 0(t6)
	sd	t2, 0(t1)
	mv	s0, a0
	mv	s1, a2
	mv	s2, t0
	addi	a2, t0, -1
	call	qsort64
	mv	t6, s2
	mv	a0, s0
	addi	a1, t6, 1
	mv	a2, s1
	call	qsort64
.Lepilogue:
	ld	ra, 24(sp)
	ld	s0, 16(sp)
	ld	s1, 8(sp)
	ld	s2, 0(sp)
	addi	sp, sp, 32
	ret
