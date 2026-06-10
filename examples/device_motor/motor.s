	.section .rodata
stepPattern:
	.word 3
stepPatternBC:
	.word 6
stepPatternCD:
	.word 12
stepPatternDA:
	.word 9
	.text
	.globl	pwmSetDuty
pwmSetDuty:
	slli	t0, a1, 2
	add	t0, a0, t0
	sw	a2, 32(t0)
	ret
	.globl	motorDrive
motorDrive:
	addi	sp, sp, -16
	sd	ra, 8(sp)
	lw	t0, 12(a0)
	li	t1, 1
	sll	t1, t1, a2
	blt	a4, zero, .Lreverse
	xori	t1, t1, -1
	and	t0, t0, t1
	j	.Lapplyduty
.Lreverse:
	or	t0, t0, t1
	sub	a4, zero, a4
.Lapplyduty:
	sw	t0, 12(a0)
	mv	a0, a1
	mv	a1, a3
	mv	a2, a4
	call	pwmSetDuty
	ld	ra, 8(sp)
	addi	sp, sp, 16
	ret
	.globl	stepperAdvance
stepperAdvance:
	li	t0, 0
	la	t1, stepPattern
.Lstepcheck:
	bge	t0, a2, .Lstepdone
	addi	a1, a1, 1
	andi	a1, a1, 3
	slli	t2, a1, 2
	add	t3, t1, t2
	lw	t4, 0(t3)
	sw	t4, 12(a0)
	li	t5, 500
.Lstepsettle:
	addi	t5, t5, -1
	bnez	t5, .Lstepsettle
	addi	t0, t0, 1
	j	.Lstepcheck
.Lstepdone:
	mv	a0, a1
	ret
