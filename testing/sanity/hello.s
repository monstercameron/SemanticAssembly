	# Standalone RISC-V Linux program — no libc. Writes a message to stdout
	# via the write(2) syscall, then exits with code 42 via exit(2).
	# Build:  riscv64-linux-gnu-gcc -nostdlib -static hello.s -o hello
	# Run:    qemu-riscv64-static ./hello ; echo $?     # prints message, exit 42

	.section .rodata
msg:
	.ascii "Hello from RISC-V under qemu!\n"
	.set msglen, . - msg

	.section .text
	.globl _start
_start:
	li	a7, 64           # syscall number: write
	li	a0, 1            # fd: stdout
	la	a1, msg          # buffer
	li	a2, msglen       # length
	ecall

	li	a7, 93           # syscall number: exit
	li	a0, 42           # exit code
	ecall
