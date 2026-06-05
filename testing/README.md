# Testing

Two tiers (DESIGN §15 round-trip honesty):

1. **Validity** — does the `.s` assemble as real RISC-V? (catches every emitter
   syntax/operand/encoding bug)
2. **Behavior** — does the binary compute the right answer? (run under qemu)

## What's installed where

- **Local (no Docker):** `clang --target=riscv64 -march=rva23u64 -c x.s` and
  `ld.lld` assemble + link riscv64 — enough for **Tier 1** with zero containers:
  ```
  clang --target=riscv64-unknown-elf -march=rva23u64 -c examples/simple_add2/add2.s -o /tmp/add2.o
  ```
- **Run** needs an emulator. No qemu/WSL on the host, so **Tier 2 uses Docker**:
  a Debian image with `gcc-riscv64-linux-gnu` (real libc) + `qemu-user-static`.

## Run the suite

Requires Docker Desktop running.

```
bash testing/run.sh
```

This builds the `sasm-riscv-test` image once, then runs `testing/intest.sh`
inside it with the repo bind-mounted at `/work`. For each example it compiles a C
harness (`testing/harness/<name>.c`) against the function's `.s`, statically links
with the cross-gcc, runs under `qemu-riscv64-static`, and asserts the result via
the process exit code. It also re-assembles every `examples/*/*.s` as a Tier-1
check.

Expected:
```
add2(2, 3) = 5            PASS
sum_array([1..5]) = 15    PASS
fib(10) = 55              PASS
ASM OK  (all three .s)
```

## How it plugs into the compiler (later)

Once `emit.py` exists, the loop becomes: `π(x.sasm) → x.s`, then

- assert `x.s` is **byte-identical** to the committed golden `.s` (snapshot test),
- assert `x.s` **assembles** (Tier 1),
- assert the harness **runs green** under qemu (Tier 2).

To test emitted output instead of the committed `.s`, point the harness build at
the freshly emitted file (same `intest.sh`, swap the `.s` path).

## Files

- `Dockerfile` — cross toolchain + qemu image
- `run.sh` — host driver (build image, run container with repo mounted)
- `intest.sh` — in-container suite (build + run + assert; also Tier-1 assemble)
- `harness/*.c` — one tiny C `main` per example; returns 0 on correct result
