# Semantic Assembly (`sasm`)

> **Agent-editable RISC-V.** A thin, row-based layer over RISC-V assembly where
> the hidden assumptions of the enumerated vocabulary — register liveness, ABI
> contracts, stack layout, memory regions, effects, intent (LANGUAGE.md; the
> general "is this fact derivable?" oracle is still open, TODOS A1) — are
> promoted into explicit, *checkable* facts. A compiler lowers it to ordinary `.s`; a validator catches the mistakes
> assembly normally hides.

```text
.sasm  ──parse──▶  facts  ──validate──▶  diagnostics
                     │
                     └──emit (π)──▶  .s  ──▶  assembler ──▶  RISC-V binary
```

📖 **Project page:** [`docs/index.html`](docs/index.html) — a visual walk through
the idea space (enable GitHub Pages from `/docs` to publish it).

## Why

An AI agent editing raw assembly gets none of the hand-holding C provides — no
types, no checked calling convention, no managed frame. Those contracts live in
the programmer's head and fail silently. Worse, the facts an edit depends on
(which value is in `a1` here? what does this call clobber? is the frame still
16-byte aligned?) are not merely far away in the file — mostly they are
**nowhere in the text at all**, and must be derived by replaying the machine.

`sasm` makes machine code **agent-native** while staying thin (every instruction
row still maps to exactly one real assembler statement):

- **understandable** — every load-bearing fact is written down, locally, instead
  of left implicit in machine state;
- **editable** — every fact is an addressable row with a stable handle, and a
  wrong edit produces a targeted diagnostic instead of silent corruption;
- **manageable / traceable** — handles survive edits, `sasm facts` answers
  "everything about X" mechanically, and emission is deterministic, so every
  edit is a minimal reviewable `.s` diff.

The safety C buys by *thickening* its abstraction, `sasm` recovers from
**metadata plus a validator** with the abstraction kept thin. The price is
tokens — a `.sasm` file runs 10–20× its `.s` — and the price is accepted:
lowering (`π`) is a lossy projection that strips all context, so verbosity costs
source bytes, never code. What is *never* accepted is an unchecked fact: every
stored fact is either consumed by the emitter, checked by the validator, or
explicitly marked as intent. **No fact is silently believed.** (See
[`DESIGN.md`](research/DESIGN.md) §2.1.)

## The idea, in one example

Raw RISC-V:

```asm
add a0, a0, a1
ret
```

The same thing in `sasm` (`examples/simple_add2/add2.sasm`, abridged):

```text
left is value
left type Int64
right is value
right type Int64
result is value
result type Int64

Add2 is function
Add2 symbol add2
Add2 in left  Int64 a0       # arg arrives in a0   (register binding = authoritative)
Add2 in right Int64 a1
Add2 out result Int64 a0
Add2 effect none             # asserted: no memory / calls / syscalls

addLeftAndRight is insn
addLeftAndRight operation Add
addLeftAndRight destination a0
addLeftAndRight firstSource a0
addLeftAndRight secondSource a1
addLeftAndRight reads left           # a0 holds `left` here  (the long-range fact)
addLeftAndRight reads right
addLeftAndRight writes result

returnResult is insn
returnResult operation Return
returnResult returns result
```

Lower it back to assembly:

```console
$ python -m sasm emit examples/simple_add2/add2.sasm
	.text
	.globl	add2
add2:
	add	a0, a0, a1
	ret
```

Names are full words by design — `operation`/`destination`/`firstSource`
(never `op`/`rd`/`rs1`), descriptive instruction handles (never `I1`).

## Quickstart

Pure Python 3, **no dependencies**.

```console
$ python -m sasm emit  <file.sasm>             # print emitted .s
$ python -m sasm build <file.sasm> -o out.s    # emit to a file (refuses on errors)
$ python -m sasm check <file.sasm>             # validate, print diagnostics
$ python -m sasm exec  <file.sasm> fib 10 --expect 55 --coverage
                                               # run it in the taint interpreter:
                                               # facts checked DYNAMICALLY (R-*)
$ python -m sasm fmt   <file.sasm> [-i]        # canonical-format
$ python -m sasm facts <file.sasm> <entity>    # dump every fact about an entity
```

`exec` is the dynamic half of the trust story (DESIGN §19): a shadow-tagged
RV64IM interpreter executes the fact rows and *observes* the semantic facts —
`reads`/`writes` bindings, `liveOut` across calls, effects, callee-saved
preservation, frame size — reporting violations as `R-*` diagnostics and
ending with a coverage report of what the trace did **not** exercise. The
path-dependent clobber the static may-analysis provably misses is caught here
concretely.

Optional install (`pip install -e .`) gives a `sasm` command instead of
`python -m sasm`.

Every instruction is an addressable handle an agent can inspect and patch:

```console
$ python -m sasm facts examples/brainworms_fib/fib.sasm callFibNumberMinusOne
callFibNumberMinusOne is insn
  in Recurse
  operation Call
  symbol fib
  effect call
  liveOut s0:number
  purpose a0 = fib(number-1). number survives in s0 (callee-saved) — safe across the call
```

## What the validator catches

`sasm check` implements the full diagnostic catalog (stable codes, each naming the
entity handle at fault — see [`DESIGN.md`](research/DESIGN.md) §14):

| area | codes |
|------|-------|
| ISA / structure | `E-ISA-OPCODE` `E-ISA-REG` `E-ISA-FIELD` `E-REF` `E-IMM-RANGE` `E-ORDER-MIXED` |
| ABI / contracts | `E-ABI-ALIGN` `E-ABI-PRESERVE` `E-LEAF` `E-EFFECT` `E-TYPE` `E-SLOT-RANGE` `E-RESERVED` |
| stack discipline | `E-STACK-OP` `E-STACK-BALANCE` (sp is an explicit, per-path-proven surface) |
| control flow / layout | `E-CFG-EDGE` `E-CFG-LAYOUT` `W-UNREACHABLE` |
| liveness | `E-LIVE-UNDEF` `E-LIVE-RET` `W-DEAD` `W-CLOBBER` |
| value flow | `E-VALUE-FLOW` `E-DERIVABLE` |
| smells | `W-LINT` (self-moves, discarded results, decisionless branches) |

For example, the recursive Fibonacci (`examples/brainworms_fib`) deliberately
moves `number` into a callee-saved register so it survives two calls. Break that —
leave it in caller-saved `a0` — and the value-flow analysis catches the clobber:

```console
$ python -m sasm check naive_fib.sasm
error E-VALUE-FLOW computeNumberMinusTwo: reads number but ['a0'] hold ['·call:callFibNumberMinusOne:a0']
```

That is the bug class assembly hides best — a value silently destroyed across a
call — surfaced mechanically.

### Clobber handling, made explicit

The check works because the *correct* `fib` writes the contract down. It keeps
`number` in a callee-saved register across the two recursive calls — and says so
(`examples/brainworms_fib/fib.sasm`, excerpt):

```text
Fib preserves s0                          # promise: caller's s0 restored on return
Fib stack bytes 32                        # 16-byte-aligned frame

moveNumberToS0 operation Move
moveNumberToS0 destination s0
moveNumberToS0 firstSource a0
moveNumberToS0 writes number              # number now lives in callee-saved s0

callFibNumberMinusOne operation Call
callFibNumberMinusOne symbol fib
callFibNumberMinusOne liveOut s0:number   # must survive the call — safe in s0
```

Save/restore is paired through a *named slot*, so there are no magic offsets to
get wrong:

```text
SlotSavedS0 is stackSlot
SlotSavedS0 offset 16
SlotSavedS0 stores s0

saveCallerS0 saves s0 SlotSavedS0         # prologue spill
restoreCallerS0 restores s0 SlotSavedS0   # epilogue reload
```

Break any of it and `check` points at the exact handle:

```console
$ python -m sasm check broken_fib.sasm
error   E-ABI-ALIGN    Fib: stack frame 24 is not 16-byte aligned
error   E-ABI-PRESERVE Fib: reuses callee-saved s0 but it is not restored
warning W-CLOBBER      callFibNumberMinusOne: t2 is live across this call but caller-saved (clobbered)
```

### Control flow & loops, made explicit

Labels and fall-through are implicit in raw assembly; here the CFG *is* facts. The
loop guard names both edges, and the back-edge declares which values are
loop-carried (`examples/challenging_sum_array/sum_array.sasm`, excerpt):

```text
Condition is block
Condition terminates branch
Condition successor Body
Condition successor Done

loopGuard operation BranchGreaterOrEqual
loopGuard firstSource t1
loopGuard secondSource a1
loopGuard target Done            # taken edge
loopGuard fallthrough Body       # not-taken edge — the implicit path, made explicit
loopGuard reads index
loopGuard reads count

loopBackEdge operation Jump
loopBackEdge target Condition
loopBackEdge liveOut t0:sum       # sum and index are loop-carried —
loopBackEdge liveOut t1:index     # they must survive into the next iteration
```

The validator builds the CFG from these edges (`E-CFG-EDGE` flags a branch target
that isn't a declared successor) and the liveness fixpoint follows the back-edge.

## Examples

Each is a triptych: `*.c` (source) · `*.sasm` (semantic) · `*.s` (emitted, golden).

| example | exercises |
|---------|-----------|
| `simple_add2` | leaf function, ABI in/out |
| `challenging_sum_array` | loop, real CFG, memory reads, loop-carried values |
| `brainworms_fib` | recursion, stack frame, named slots, callee-saved save/restore, **clobber handling** |
| `hello_world` | standalone `_start`, `.rodata` data, syscalls (`EnvironmentCall`) |
| `sum_of_squares` | **multi-function program** — 3 functions, calls, loop with `mul`, decimal conversion with `div`/`rem`, stack buffer; prints `385` |
| `data_demo` | `.data` + `.bss` sections, alignment, global loads/stores; exits `42` |
| `linked` | **two translation units** (`main` + `lib`) — external `symbol`, cross-TU call; exits `42` |
| `gauntlet_ackermann` | **nested recursion** — `ack(m-1, ack(m, n-1))`, call-result binding, 3-way dispatch CFG; `ack(3,3)` = 2432 calls |
| `gauntlet_quicksort` | **two recursions + mutating partition loop** — 8-block CFG, three values riding a call in `s0`/`s1`/`s2` |
| `gauntlet_revlist` | **pointer rotation** — in-place list reversal where row order is the algorithm; two functions, one TU |
| `device_gpio` | **Arduino-style LED I/O** — `pinMode`/`digitalWrite`/`digitalRead`/`blink` over an mmap-style GPIO base; `kind device` + `volatile` regions, RMW bit ops |
| `device_motor` | **motor control** — PWM duty (`analogWrite`), sign-driven H-bridge direction, table-driven 4-phase stepper; readonly + device regions in one loop |

## Testing

**One command, fully self-contained** (the reproducible eval environment — Python
toolchain + riscv64 cross-gcc + qemu baked into one image, no host deps):

```console
$ docker build -t sasm-eval .
$ docker run --rm sasm-eval        # runs eval.sh: snapshots + validator + qemu
...
==================== ALL EVAL CHECKS PASSED ====================
```

Or run the tiers individually on a host with Python (and Docker for the last one):

```console
$ bash tests/snapshot.sh     # compiler: π(x.sasm) is byte-identical to golden x.s
$ bash tests/check.sh        # validator: every example validates clean
$ bash testing/run.sh        # behavioral: assemble + run under qemu (mounts repo)
$ bash eval.sh               # all three (behavioral tier auto-skips without qemu)
```

The behavioral tier compiles each example for `riscv64` and runs it under
`qemu-riscv64`, asserting real results: `add2(2,3)=5`, `sum_array([1..5])=15`,
`fib(10)=55`, `ack(3,3)=61` (2432 recursive calls), quicksort over four arrays
(duplicates, sorted, reverse, single), a list-reversal round-trip with
order-sensitive checksums, `hello` prints and exits 0, `sum_of_squares` prints
`385`, and `data_demo`/`linked` exit `42`. Two Dockerfiles:
top-level `Dockerfile` is the self-contained whole-suite image;
`testing/Dockerfile` is the leaner behavioral-only image used by `testing/run.sh`.

## Project layout

```text
sasm/              the toolchain (pure Python)
  parser.py        .sasm text  → facts (Program/Entity)
  isa.py           loads the TSV tables
  emit.py          facts → .s   (the projection π)
  validate.py      facts → diagnostics
  cli.py           emit | build | check | facts
  optable.tsv      semantic ops (source of truth)
  regs.tsv abi.tsv formats.tsv extmap.tsv syscalls.tsv csr.tsv
examples/          thirteen C / sasm / s triptychs (gauntlet + device sets)
tests/             snapshot (compiler) + check (validator) + regressions
testing/           behavioral harness (testing/Dockerfile + qemu)
docs/              project webpage (index.html, for GitHub Pages)
Dockerfile         self-contained eval image (runs eval.sh)
eval.sh            full suite: snapshots + validator + behavioral
research/          all the docs (every .md except this README)
  DESIGN.md        framework, projection model, validator design, falsifiability
  LANGUAGE.md      the canonical fact vocabulary
  OPCODES.md       rendered semantic op reference
  TODOS.md         implicit-state → explicit-fact backlog / status
  examples.md      guide to the example triptychs
  testing.md       the three-tier test harness
  docs.md          how to view / publish the webpage
```

## Status

Working today: the **compiler** (RV64 "Tier A": RV64I + M + Zicond + scalar
atomics) emits byte-identical, assembling, *executing* RISC-V across thirteen
examples; the **validator** implements the entire enforced set of the DESIGN §14
catalog — all 32 codes, nothing pending — with zero
false positives on the examples; the **taint interpreter** (`sasm exec`) checks
the semantic facts dynamically (the `R-*` runtime catalog, DESIGN §19.2); and
the **mutation tier** fuzzes the verifier itself — 75 mutants, every
behavior-changing one caught statically or dynamically, and its first run found
and fixed a real hole (`E-SLOT-RANGE`). All proven on emulated RISC-V.

Honestly not done yet: the general `E-DERIVABLE` reachability oracle (its
register-restatement and effect-restatement slices are live — the full
"could a tool re-derive this fact?" analysis is the project's one open
research item); the premise benchmark's FULL study (the D1 harness is live and a first
Protocol-1 pilot has run — `benchmarks/runs/pilot/results.md` — but scale,
n≥10, Protocol 2, and two task families remain); the real-binary debugging
adapter (DESIGN §18, gated on D1's Protocol-2 result); and ISA breadth beyond Tier A (Tiers B/V/P via the official
`riscv/riscv-opcodes` generator). Every diagnostic code in the catalog is
enforced; every vocabulary predicate is checked, demoted-with-reason, or
tier-scoped (LANGUAGE §10.5). See [`TODOS.md`](research/TODOS.md).

## Design docs

Start with [`DESIGN.md`](research/DESIGN.md) for the *why* and the architecture, then
[`LANGUAGE.md`](research/LANGUAGE.md) for the exact vocabulary and
[`OPCODES.md`](research/OPCODES.md) for the op table.
