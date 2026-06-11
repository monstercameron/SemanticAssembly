# FACTS (same information as the semantic source, in prose):
# function qsort64:
#   argument array (Int64Pointer) arrives in a0
#   argument low (Int64) arrives in a1
#   argument high (Int64) arrives in a2
#   stack frame: 48 bytes, 16-byte aligned
#   callee-saved returnAddress must be restored on return
#   callee-saved s0 must be restored on return
#   callee-saved s1 must be restored on return
#   callee-saved s2 must be restored on return
#   callee-saved s3 must be restored on return
#   slot SlotReturnAddress: offset 24 from sp, holds saved returnAddress
#   slot SlotSavedS0: offset 16 from sp, holds saved s0
#   slot SlotSavedS1: offset 8 from sp, holds saved s1
#   slot SlotSavedS2: offset 0 from sp, holds saved s2
#   slot SlotSavedS3: offset 32 from sp, holds saved s3
#   value array: base of the caller's array; must survive the first recursion
#   value low: left bound; carried in s3 for the whole function
#   value high: right bound; must survive the partition loop and the first recursion
#   value pivotValue: a[high], chosen pivot; loop-carried through the partition
#   value boundary: Lomuto i: last index of the <=pivot prefix; loop-carried
#   value scan: Lomuto j: the scanning index; loop-carried
#   value pivotIndex: final pivot position p; splits the two recursions, survives the first
#   across the call at `loopBackEdge`: pivotValue must survive in t2
#   across the call at `loopBackEdge`: boundary must survive in t3
#   across the call at `loopBackEdge`: scan must survive in t4
#   across the call at `qsort64`: array must survive in s0
#   across the call at `qsort64`: high must survive in s1
#   across the call at `qsort64`: pivotIndex must survive in s2
#
	.text
	.globl	qsort64
qsort64:
	addi	sp, sp, -48
	sd	ra, 24(sp)
	sd	s0, 16(sp)
	sd	s1, 8(sp)
	sd	s2, 0(sp)
	sd	s3, 32(sp)
	mv	s3, a1
	bge	a1, a2, .Lepilogue
	slli	t0, a2, 3
	add	t1, a0, t0
	ld	t2, 0(t1)
	addi	t3, s3, -1
	mv	t4, s3
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
	mv	a1, s3
	addi	a2, t0, -1
	call	qsort64
	mv	a0, s0
	addi	a1, s2, 1
	mv	a2, s1
	call	qsort64
.Lepilogue:
	ld	ra, 24(sp)
	ld	s0, 16(sp)
	ld	s1, 8(sp)
	ld	s2, 0(sp)
	ld	s3, 32(sp)
	addi	sp, sp, 48
	ret
