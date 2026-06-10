# FACTS (same information as the semantic source, in prose):
# function fib:
#   argument number (Int64) arrives in a0
#   result result (Int64) leaves in a0
#   stack frame: 48 bytes, 16-byte aligned
#   callee-saved returnAddress must be restored on return
#   callee-saved s0 must be restored on return
#   callee-saved s1 must be restored on return
#   slot SlotReturnAddress: offset 40 from sp, holds saved returnAddress
#   slot SlotSavedS0: offset 32 from sp, holds saved s0
#   slot SlotSavedS1: offset 24 from sp, holds saved s1
#   value number: the input; must survive both recursive calls
#   value firstResult: fib(number-1); must survive the second call
#   value result: the returned Fibonacci number; on the base path it IS number (declared phi)
#   across the call at `fib`: number must survive in s0
#   across the call at `fib`: firstResult must survive in s1
#
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
