	.text
	.globl	pinModeOutput
pinModeOutput:
	lw	t0, 8(a0)
	li	t1, 1
	sll	t1, t1, a1
	or	t0, t0, t1
	sw	t0, 8(a0)
	ret
	.globl	digitalWrite
digitalWrite:
	lw	t0, 12(a0)
	li	t1, 1
	sll	t1, t1, a1
	beqz	a2, .Lclearbit
	or	t0, t0, t1
	j	.Lstorevalue
.Lclearbit:
	xori	t1, t1, -1
	and	t0, t0, t1
.Lstorevalue:
	sw	t0, 12(a0)
	ret
	.globl	digitalRead
digitalRead:
	lw	t0, 0(a0)
	srl	t0, t0, a1
	andi	a0, t0, 1
	ret
	.globl	blink
blink:
	addi	sp, sp, -48
	sd	ra, 40(sp)
	sd	s0, 32(sp)
	sd	s1, 24(sp)
	sd	s2, 16(sp)
	sd	s3, 8(sp)
	mv	s0, a0
	mv	s1, a1
	mv	s2, a2
	li	s3, 0
.Lblinkcheck:
	bge	s3, s2, .Lblinkdone
	mv	a0, s0
	mv	a1, s1
	li	a2, 1
	call	digitalWrite
	li	t0, 2000
.Ldelayhigh:
	addi	t0, t0, -1
	bnez	t0, .Ldelayhigh
	mv	a0, s0
	mv	a1, s1
	li	a2, 0
	call	digitalWrite
	li	t0, 2000
.Ldelaylow:
	addi	t0, t0, -1
	bnez	t0, .Ldelaylow
	addi	s3, s3, 1
	j	.Lblinkcheck
.Lblinkdone:
	slli	a0, s2, 1
	ld	ra, 40(sp)
	ld	s0, 32(sp)
	ld	s1, 24(sp)
	ld	s2, 16(sp)
	ld	s3, 8(sp)
	addi	sp, sp, 48
	ret
