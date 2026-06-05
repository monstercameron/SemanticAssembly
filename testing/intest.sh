#!/usr/bin/env bash
# Runs INSIDE the container (repo mounted at /work). Compiles each C harness
# against the function's .s, runs it under qemu-riscv64, asserts the result.
set -u
cd /work
CC=riscv64-linux-gnu-gcc
QEMU=qemu-riscv64-static
fail=0

run() {                       # name  expect  source-files...
  local name=$1 expect=$2; shift 2
  if ! $CC -static -O0 "$@" -o "/tmp/$name" 2>"/tmp/$name.err"; then
    echo "BUILD FAIL  $name"; sed 's/^/    /' "/tmp/$name.err"; fail=1; return
  fi
  $QEMU "/tmp/$name"; local got=$?
  if [ "$got" = "$expect" ]; then
    echo "PASS        $name"
  else
    echo "FAIL        $name (exit $got, want $expect)"; fail=1
  fi
}

echo "== behavioral tests, functions (qemu-riscv64) =="
run add2      0 testing/harness/add2.c      examples/simple_add2/add2.s
run sum_array 0 testing/harness/sum_array.c examples/challenging_sum_array/sum_array.s
run fib       0 testing/harness/fib.c       examples/brainworms_fib/fib.s

echo "== behavioral tests, standalone _start programs =="
# freestanding (no libc): build with -nostdlib, check stdout + exit code
standalone() {                # name  expected-stdout  source.s
  local name=$1 want=$2 src=$3
  if ! riscv64-linux-gnu-gcc -nostdlib -static "$src" -o "/tmp/$name" 2>"/tmp/$name.err"; then
    echo "BUILD FAIL  $name"; sed 's/^/    /' "/tmp/$name.err"; fail=1; return
  fi
  local out; out="$(qemu-riscv64-static "/tmp/$name")"; local code=$?
  if [ "$code" = 0 ] && [ "$out" = "$want" ]; then
    echo "PASS        $name"
  else
    echo "FAIL        $name (exit $code, stdout: [$out], want [$want])"; fail=1
  fi
}
standalone hello          "Hello from semantic assembly!" examples/hello_world/hello.s
standalone sum_of_squares "385"                           examples/sum_of_squares/sum_of_squares.s

echo "== assemble-validity (clang-independent, gcc as assembler) =="
for s in examples/*/*.s; do
  if $CC -c "$s" -o /tmp/chk.o 2>/tmp/chk.err; then echo "ASM OK      $s"
  else echo "ASM FAIL    $s"; sed 's/^/    /' /tmp/chk.err; fail=1; fi
done

exit $fail
