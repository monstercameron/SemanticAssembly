	.text
	.globl	ack
ack:
	addi	sp, sp, -32
	sd	ra, 24(sp)
	sd	s0, 16(sp)
	beqz	a0, .Llevelzero
	beqz	a1, .Lcountzero
	mv	s0, a0
	addi	a1, a1, -1
	call	ack
	mv	a1, a0
	addi	a0, s0, -1
	call	ack
.Lepilogue:
	ld	ra, 24(sp)
	ld	s0, 16(sp)
	addi	sp, sp, 32
	ret
.Llevelzero:
	addi	a0, a1, 1
	j	.Lepilogue
.Lcountzero:
	addi	a0, a0, -1
	li	a1, 1
	call	ack
	j	.Lepilogue
