# FACTS (same information as the semantic source, in prose):
# function fib:
#   argument number (Int64) arrives in a0
#   result result (Int64) leaves in a0
#   stack frame: 32 bytes, 16-byte aligned
#   callee-saved returnAddress must be restored on return
#   callee-saved s0 must be restored on return
#   slot SlotReturnAddress: offset 24 from sp, holds saved returnAddress
#   slot SlotSavedS0: offset 16 from sp, holds saved s0
#   slot SlotFirstResult: offset 0 from sp, holds firstResult
#   value number: the input; must survive both recursive calls
#   value firstResult: fib(number-1); must survive the second call
#   value result: the returned Fibonacci number; on the base path it IS number (declared phi)
#   across the call at `fib`: number must survive in s0
#   across the call at `fib`: firstResult must survive in the stack slot at offset 0
#
	.text
	.globl	fib
fib:
	addi	sp, sp, -32
	sd	ra, 24(sp)
	sd	s0, 16(sp)
	li	t0, 2
	blt	a0, t0, .Lepilogue
	mv	s0, a0
	addi	a0, s0, -1
	call	fib
	sd	a0, 0(sp)
	addi	a0, s0, -2
	call	fib
	ld	t2, 0(sp)
	add	a0, t2, a0
.Lepilogue:
	ld	ra, 24(sp)
	ld	s0, 16(sp)
	addi	sp, sp, 32
	ret
