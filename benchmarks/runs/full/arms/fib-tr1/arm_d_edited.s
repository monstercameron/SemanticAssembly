	.text
	.globl	fib
fib:
	addi	sp, sp, -32	# Allocate a 16-byte-aligned 32-byte frame
	sd	ra, 24(sp)	# saves returnAddress SlotReturnAddress; Save returnAddress: every Call clobbers it
	sd	s0, 16(sp)	# saves s0 SlotSavedS0; Preserve caller's s0 before we reuse it for number
	sd	s1, 8(sp)	# saves s1 SlotSavedS1; Preserve caller's s1 before we reuse it for fib(number-1)
	li	t1, 2	# Constant 2 (adjacent scratch, not named)
	blt	a0, t1, .Lepilogue	# reads number; base case: if number < 2, a0 already holds the answer (fib(number)=number)
	mv	s0, a0	# reads number; writes number; number -> s0 (callee-saved): a0 is caller-saved and Call would clobber number
	addi	a0, s0, -1	# reads number; argument = number - 1 (transient, consumed by the call)
	call	fib	# liveOut s0:number; a0 = fib(number-1). number survives in s0 (callee-saved) — safe across the call
	mv	s1, a0	# writes firstResult; fib(number-1) -> s1 before the second Call clobbers a0
	addi	a0, s0, -2	# reads number; argument = number - 2
	call	fib	# liveOut s1:firstResult; a0 = fib(number-2). firstResult survives in s1 — safe; number (s0) is now dead
	add	a0, a0, s1	# reads firstResult; writes result; result = fib(number-1) + fib(number-2)
.Lepilogue:
	ld	ra, 24(sp)	# restores returnAddress SlotReturnAddress; Restore return address
	ld	s0, 16(sp)	# restores s0 SlotSavedS0; Restore caller's s0 (callee-saved contract)
	ld	s1, 16(sp)	# restores s1 SlotSavedS1; Restore caller's s1 (callee-saved contract)
	addi	sp, sp, 32	# Tear down the frame
	ret	# returns result; Return the Fibonacci number in a0
