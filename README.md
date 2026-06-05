# Semantic Assembly (`sasm`)

> **Agent-editable RISC-V.** A thin, row-based layer over RISC-V assembly where
> every hidden assumption — register liveness, ABI contracts, stack layout,
> memory regions, effects, intent — is promoted into an explicit, *checkable*
> fact. A compiler lowers it to ordinary `.s`; a validator catches the mistakes
> assembly normally hides.

```text
.sasm  ──parse──▶  facts  ──validate──▶  diagnostics
                     │
                     └──emit (π)──▶  .s  ──▶  assembler ──▶  RISC-V binary
```

## Why

Raw assembly is hard for an LLM to edit *reliably* — not because the model can't
read it, but because correctness lives in **long-range, implicit, stateful**
dependencies (which value is in `a1` here? what does this call clobber? is the
frame still 16-byte aligned?). That is exactly the regime where attention
degrades.

`sasm` is an **attention-conditioning format**: it moves the information an edit
needs from *must-be-inferred-over-distance* to *present-locally*, as a row the
agent can address and patch — and a validator then catches the cases where the
edit broke a contract anyway. (See [`DESIGN.md`](DESIGN.md) §2.1.)

It is *thin*: every instruction row still maps to exactly one real assembler
statement. Lowering (`π`) is a lossy projection that strips all the context and
emits plain `.s` — so the verbosity costs source bytes, not code.

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
$ python -m sasm facts <file.sasm> <entity>    # dump every fact about an entity
```

## What the validator catches

`sasm check` implements the full diagnostic catalog (stable codes, each naming the
entity handle at fault — see [`DESIGN.md`](DESIGN.md) §14):

| area | codes |
|------|-------|
| ISA / structure | `E-ISA-OPCODE` `E-ISA-REG` `E-ISA-FIELD` `E-REF` `E-IMM-RANGE` `E-ORDER-MIXED` |
| ABI / contracts | `E-ABI-ALIGN` `E-ABI-PRESERVE` `E-LEAF` `E-EFFECT` `E-TYPE` `W-SLOT` |
| control flow | `E-CFG-EDGE` |
| liveness | `E-LIVE-UNDEF` `E-LIVE-RET` `W-DEAD` `W-CLOBBER` |
| value flow | `E-VALUE-FLOW` `E-DERIVABLE` |

For example, the recursive Fibonacci (`examples/brainworms_fib`) deliberately
moves `number` into a callee-saved register so it survives two calls. Break that —
leave it in caller-saved `a0` — and the value-flow analysis catches the clobber:

```console
$ python -m sasm check naive_fib.sasm
error E-VALUE-FLOW computeNumberMinusTwo: reads number but ['a0'] hold ['·call:callFibNumberMinusOne:a0']
```

That is the bug class assembly hides best — a value silently destroyed across a
call — surfaced mechanically.

## Examples

Each is a triptych: `*.c` (source) · `*.sasm` (semantic) · `*.s` (emitted, golden).

| example | exercises |
|---------|-----------|
| `simple_add2` | leaf function, ABI in/out |
| `challenging_sum_array` | loop, real CFG, memory reads, loop-carried values |
| `brainworms_fib` | recursion, stack frame, named slots, callee-saved save/restore, **clobber handling** |
| `hello_world` | standalone `_start`, `.rodata` data, syscalls (`EnvironmentCall`) |

## Testing

Two tiers (see [`testing/README.md`](testing/README.md)):

```console
$ bash tests/snapshot.sh     # compiler: π(x.sasm) is byte-identical to golden x.s
$ bash tests/check.sh        # validator: every example validates clean
$ bash testing/run.sh        # behavioral: assemble + run under qemu (needs Docker)
```

The behavioral tier compiles each example for `riscv64` and runs it under
`qemu-riscv64` (in a Docker image with the cross toolchain), asserting real
results: `add2(2,3)=5`, `sum_array([1..5])=15`, `fib(10)=55`, and `hello` prints
its message and exits 0.

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
examples/          four C / sasm / s triptychs
tests/             snapshot (compiler) + check (validator)
testing/           Docker + qemu behavioral harness
DESIGN.md          framework, projection model, validator design, falsifiability
LANGUAGE.md        the canonical fact vocabulary
OPCODES.md         rendered semantic op reference
TODOS.md           implicit-state → explicit-fact backlog / status
```

## Status

Working today: the **compiler** (RV64 "Tier A": RV64I + M + Zicond + scalar
atomics) emits byte-identical, assembling, *executing* RISC-V; the **validator**
implements the entire diagnostic catalog (19 codes) with zero false positives on
the examples. All proven on emulated RISC-V.

Honestly not done yet: the general `E-DERIVABLE` reachability linter; broader ISA
coverage (Tiers B/V/P, planned via the official `riscv/riscv-opcodes` generator);
and some compiler edges the examples don't exercise (multi-function files, the
compact pipe sugar, `ordinal` ordering). See [`TODOS.md`](TODOS.md).

## Design docs

Start with [`DESIGN.md`](DESIGN.md) for the *why* and the architecture, then
[`LANGUAGE.md`](LANGUAGE.md) for the exact vocabulary and
[`OPCODES.md`](OPCODES.md) for the op table.
