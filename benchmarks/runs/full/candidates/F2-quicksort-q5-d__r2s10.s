	.text
	.globl	qsort64
qsort64:
	addi	sp, sp, -32	# Allocate the 16-byte-aligned 32-byte frame
	sd	ra, 24(sp)	# saves returnAddress SlotReturnAddress; Every Call clobbers returnAddress
	sd	s0, 16(sp)	# saves s0 SlotSavedS0; Preserve caller's s0 before it carries array
	sd	s1, 8(sp)	# saves s1 SlotSavedS1; Preserve caller's s1 before it carries high
	sd	s2, 0(sp)	# saves s2 SlotSavedS2; Preserve caller's s2 before it carries pivotIndex
	bge	a1, a2, .Lepilogue	# reads low; reads high; low >= high: zero or one element, already sorted
	slli	t0, a2, 3	# reads high; byte offset of array[high] (adjacent scratch)
	add	t1, a0, t0	# reads array; address of array[high]
	ld	t2, 0(t1)	# writes pivotValue; pivotValue = array[high]
	addi	t3, a1, -1	# reads low; writes boundary; boundary = low - 1 (empty prefix)
	mv	t4, a1	# reads low; writes scan; scan = low
.Lpartitioncheck:
	bge	t4, a2, .Lpartitiondone	# reads scan; reads high; scan >= high: partition finished
	slli	t0, t4, 3	# reads scan; byte offset of array[scan]
	add	t1, a0, t0	# reads array; address of array[scan] — also reused by the swap store
	ld	t5, 0(t1)	# element = array[scan] (adjacent scratch, not named)
	bge	t2, t5, .Lswap	# reads pivotValue; element <= pivotValue: branch taken to swap code
	addi	t4, t4, 1	# reads scan; writes scan; scan++ (fall-through: element > pivot, advance scan)
	j	.Lpartitioncheck	# liveOut t2:pivotValue; liveOut t3:boundary; liveOut t4:scan; Loop-carried: pivotValue/boundary/scan must survive into the next iteration
.Lswap:
	addi	t3, t3, 1	# reads boundary; writes boundary; Grow the <=pivot prefix
	slli	t0, t3, 3	# reads boundary; byte offset of array[boundary] (t0 reused — old offset is dead)
	add	t6, a0, t0	# reads array; address of array[boundary]
	ld	t0, 0(t6)	# old array[boundary] (t0 reused again — offset consumed)
	sd	t5, 0(t6)	# array[boundary] = element
	sd	t0, 0(t1)	# array[scan] = old array[boundary] — t1 still holds the scan address
	addi	t4, t4, 1	# reads scan; writes scan; scan++
	j	.Lpartitioncheck	# liveOut t2:pivotValue; liveOut t3:boundary; liveOut t4:scan; Loop-carried: pivotValue/boundary/scan must survive into the next iteration
.Lpartitiondone:
	addi	t0, t3, 1	# reads boundary; writes pivotIndex; pivotIndex = boundary + 1
	slli	t1, t0, 3	# reads pivotIndex; byte offset of array[pivotIndex]
	add	t1, a0, t1	# reads array; address of array[pivotIndex]
	ld	t5, 0(t1)	# old array[pivotIndex], displaced to the end
	slli	t6, a2, 3	# reads high; byte offset of array[high]
	add	t6, a0, t6	# reads array; address of array[high]
	sd	t5, 0(t6)	# array[high] = displaced element
	sd	t2, 0(t1)	# reads pivotValue; array[pivotIndex] = pivotValue — pivot is finally seated
	mv	s0, a0	# reads array; writes array; array -> s0: the first Call clobbers a0
	mv	s1, a2	# reads high; writes high; high -> s1: needed by the second recursion
	mv	s2, t0	# reads pivotIndex; writes pivotIndex; pivotIndex -> s2: splits the two recursions
	addi	a2, t0, -1	# reads pivotIndex; left recursion bound: pivotIndex - 1 (a0=array, a1=low are already in place)
	call	qsort64	# liveOut s0:array; liveOut s1:high; liveOut s2:pivotIndex; qsort64(array, low, pivotIndex-1); three values ride out the call in s0/s1/s2
	mv	a0, s0	# reads array; first argument again: array
	addi	a1, s2, 1	# reads pivotIndex; right recursion bound: pivotIndex + 1
	mv	a2, s1	# reads high; third argument again: high
	call	qsort64	# qsort64(array, pivotIndex+1, high); nothing must survive this call
.Lepilogue:
	ld	ra, 24(sp)	# restores returnAddress SlotReturnAddress; Restore return address
	ld	s0, 16(sp)	# restores s0 SlotSavedS0; Restore caller's s0
	ld	s1, 8(sp)	# restores s1 SlotSavedS1; Restore caller's s1
	ld	s2, 0(sp)	# restores s2 SlotSavedS2; Restore caller's s2
	addi	sp, sp, 32	# Free the frame
	ret	# No result register: the work product is the mutated array
