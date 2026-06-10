# Testing

Five tiers. 0–2 test the *toolchain*, 3 tests the *verifier itself*, 4 tests
the *premise* — different kinds of evidence; none substitutes for another.

0. **Facts (dynamic)** — `sasm exec`: the taint interpreter (DESIGN §19.2) runs
   the fact rows in-process, checks the semantic facts on the trace (`R-*`
   codes), and reports coverage. No Docker, no toolchain, milliseconds.
   (`tests/test_interp.py`)
1. **Validity** — does the `.s` assemble as real RISC-V? (catches every emitter
   syntax/operand/encoding bug)
2. **Behavior** — does the binary compute the right answer? (run under qemu)
3. **Mutation** — fuzz the verifier (DESIGN §19.3): every behavior-changing
   mutant of a known-good example must be caught statically or dynamically;
   uncaught non-equivalent mutants fail the build. (`tests/test_mutation.py`)
4. **Premise** — do agents actually understand / edit / trace `.sasm` better
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
inside it with the repo bind-mounted at `/work`. For each function example it
compiles a C harness (`testing/harness/<name>.c`) against the function's `.s`,
statically links with the cross-gcc, runs under `qemu-riscv64-static`, and
asserts the result via the process exit code; `_start` programs are built
`-nostdlib` and checked on stdout/exit code; the `linked/` pair is linked
cross-TU. It also re-assembles every `examples/*/*.s` as a Tier-1 check.

Expected (abridged):
```
PASS  add2 · sum_array · fib · ackermann · quicksort · revlist
PASS  hello · sum_of_squares · data_demo (exit 42) · linked (exit 42)
ASM OK  (all thirteen .s)
```
The gauntlet harnesses assert real behavior: `ack(3,3)=61` through 2432
recursive frames, quicksort over duplicate/sorted/reverse/single arrays, and a
list-reversal round-trip with order-sensitive checksums.

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

## Tier 4 — the premise benchmark (planned; DESIGN §16.1, TODOS D1)

Tiers 0–3 prove the toolchain and verifier are honest; they say nothing about whether the
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

(Designed but gated behind Tier 4's result: the real-binary debug API — DESIGN §18,
TODOS G — reuses this same qemu plumbing via the gdb stub to run trace-scoped
contract checks; it is not part of any test tier until the gate lifts.)
