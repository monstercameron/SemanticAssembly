# Testing

Three tiers. The first two test the *toolchain* (DESIGN §15 round-trip honesty);
the third tests the *premise* — they are different kinds of evidence and neither
substitutes for the other.

1. **Validity** — does the `.s` assemble as real RISC-V? (catches every emitter
   syntax/operand/encoding bug)
2. **Behavior** — does the binary compute the right answer? (run under qemu)
3. **Premise** — do agents actually understand / edit / trace `.sasm` better
   than `.s`? (the DESIGN §16.1 benchmark — see below; not yet implemented)

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

## Tier 3 — the premise benchmark (planned; DESIGN §16.1, TODOS D1)

Tiers 1–2 prove the toolchain is honest; they say nothing about whether the
format helps an agent. That claim is tested by the §16.1 benchmark, summarized
here so the harness work has a fixed target:

- **Four arms**, same information, different form: (a) raw `.s` · (c) `.s` +
  prose fact block at top · (d) `.s` + the same facts as inline comments ·
  (b) `.sasm`. Arm (d) is the critical control — b-over-d isolates
  addressability + checkability from mere locality.
- **Three task families**, one per §2.1 pillar: comprehension questions
  (*understand*), the long-range mutation set scored by the Tier-1/2 oracle
  (*edit*), and stale-fact / which-edit-broke-the-contract probes
  (*manage/trace*).
- **Two protocols** for the edit family: one-shot (tests the representation) and
  closed-loop with **equal feedback budgets** — a/c/d get assembler + behavioral
  output, b additionally gets `sasm check` diagnostics (tests the §5.1 loop).
  Score success rate, rounds-to-success, and tokens-to-success.

The Tier-2 qemu harness doubles as the benchmark's behavioral oracle: a candidate
edit passes iff its lowered `.s` assembles and the harness exits green.

(Designed but gated behind Tier 3's result: the runtime debug API — DESIGN §18,
TODOS G — reuses this same qemu plumbing via the gdb stub to run trace-scoped
contract checks; it is not part of any test tier until the gate lifts.)
