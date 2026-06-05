	.text
	.globl	sum_array
sum_array:
	li	t0, 0
	li	t1, 0
.Lcondition:
	bge	t1, a1, .Ldone
	slli	t2, t1, 3
	add	t3, a0, t2
	ld	t4, 0(t3)
	add	t0, t0, t4
	addi	t1, t1, 1
	j	.Lcondition
.Ldone:
	mv	a0, t0
	ret
