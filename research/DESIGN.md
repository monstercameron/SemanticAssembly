# Semantic Assembly — Design

> Agentic RISC-V: a structured, auditable assembly dialect where every machine
> instruction is still real, but every hidden assumption is promoted into
> source-level facts.

## 1. Problem

Raw assembly is hard for agents (and humans) to edit safely because it is
**compact, implicit, and stateful**:

- An instruction's effect on registers, memory, and control flow is implicit in
  the opcode.
- Register *ownership* (who holds what value, when) is invisible.
- The calling convention (ABI) is a contract that lives only in the programmer's
  head.
- Stack offsets are hardcoded magic numbers that silently couple instructions.
- Memory accesses don't say *which* region (stack / heap / global / readonly /
  device) they touch.

Most novice and AI assembly bugs are **register-liveness bugs**, **clobber
bugs**, and **ABI-contract violations** — exactly the things raw `.s` hides.

## 2. Idea

Keep the instructions real, but lift every instruction, register use, memory
access, effect, ABI rule, and intent into **agent-addressable facts** using a
row-based entity model:

```
<subject> <predicate> <arg>...
<subject> is <Type>
```

Raw RISC-V:

```asm
add a0, a0, a1
ret
```

Semantic assembly (`.sasm`) — every fact tagged with its tier so the model is
visible: **A** survives lowering, **S-check** is validator-verified, **S-intent**
is the irreducible *why* (§11). Two real instructions become this:

```
prog is program
prog target rva23u64                       # A   which ISA the code assumes
prog xlen 64                               # A
prog abi linux.riscv64                     # S-check  default calling convention

# --- values: "what does a register mean, here" made local and typed ---
left is value                              #          (the long-range fact raw asm hides)
left type Int64                            # S-check
left signed yes                            # S-check
left meaning "first addend"                # S-intent

right is value
right type Int64                           # S-check
right signed yes                           # S-check
right meaning "second addend"             # S-intent

result is value
result type Int64                          # S-check
result meaning "left + right"             # S-intent

# --- the function: ABI contract stated, not assumed ---
Add2 is function
Add2 symbol add2                           # A   emitted label
Add2 visibility global                     # A   -> .globl
Add2 abi linux.riscv64                     # S-check
Add2 in  left  Int64 a0                    # A(reg) + S-check(type)  arg arrives in a0
Add2 in  right Int64 a1                    # A(reg) + S-check(type)
Add2 out result Int64 a0                   # A(reg) + S-check(type)  result leaves in a0
Add2 effect none                           # S-check  asserts: no memory/calls/syscalls
Add2 leaf yes                              # S-check  asserts: makes no calls
Add2 stack bytes 0                         # S-check  no frame; checked vs explicit prologue
Add2 purpose "Return left + right"        # S-intent

Entry is block
Entry in Add2                              # A
Entry entry yes                            # A   gets the function label
Entry terminates return                    # S-check  cross-checked against the terminator

addLeftAndRight is insn
addLeftAndRight in Entry                    # A
addLeftAndRight operation Add               # A   semantic op (mnemonic derived by π)
addLeftAndRight destination a0              # A
addLeftAndRight firstSource a0             # A
addLeftAndRight secondSource a1            # A
addLeftAndRight reads left                  # S-check  a0 holds `left` at this point
addLeftAndRight reads right                 # S-check  a1 holds `right` at this point
addLeftAndRight writes result              # S-check  a0 now holds `result`
addLeftAndRight purpose "result = left + right, into the return register"   # S-intent

returnResult is insn
returnResult in Entry                       # A
returnResult operation Return               # A
returnResult returns result                 # S-check  the value handed back must be defined here
returnResult purpose "Hand result back to the caller"        # S-intent
```

Note the full-word vocabulary: `operation`/`destination`/`firstSource`/
`secondSource` (never `op`/`rd`/`rs1`/`rs2`), descriptive instruction handles
(never `I1`/`R1`), full-word value names. Note also what is *not* written: no
`reads returnAddress` on `Return` (the op table already says it uses
`returnAddress` — that would be S-derivable), nothing restates that `Add` uses
`secondSource`, and no mnemonic appears. Those are **S-derivable** — unchecked
copies of table knowledge, forbidden by §11. But `reads left`/`writes result`
*are* present: they
name **values**, not registers, so they assert the long-range register↔value
binding (§11.2) that earns its place.

The agent no longer patches opaque text — it patches `addLeftAndRight.secondSource`,
`Add2.stack bytes`, an `effect`, a `value` type, a stack slot. Each is a
**semantic handle**: an addressable row the agent edits and the validator
re-checks (§5.1). And the fact raw assembly hides hardest — *which value is in
`a1` here* — is now the local, checkable row `addLeftAndRight reads right`, not
something to reconstruct across the function.

## 2.1 Stance: an agent-native machine format

`.sasm` exists so that an AI agent can do three things to machine code that raw
`.s` does not support:

1. **Understand it.** Every fact an edit depends on is *written down, where the
   edit happens*. Nothing must be reconstructed by replaying the machine in the
   model's head — liveness, who-owns-`a1`-here, what a call clobbers, whether
   the frame is still aligned are rows, not inferences.
2. **Edit it.** Every fact is an *addressable row with a stable handle*. An edit
   is a structured patch to named rows, not a textual splice into a fragile
   listing — and a wrong edit produces a targeted diagnostic (§5.1), not silent
   corruption.
3. **Manage and trace it.** Handles survive edits; `sasm facts <entity>` answers
   "everything about X" mechanically; `π` is deterministic, so every change is a
   minimal, reviewable `.s` diff; every diagnostic carries a stable code an agent
   can route on. The file is a queryable fact base, not prose.

This matters because assembly has none of the hand-holding of C and other
high-level languages. There is no type system, no compiler-enforced calling
convention, no managed frame — in raw `.s` those contracts exist only in the
programmer's head and fail silently. A high-level language buys its safety by
*thickening* the abstraction until the dangerous states are inexpressible.
`.sasm` refuses that trade. The layer stays **thin** — roughly 1:1 with
*assembler statements*, never a new IR that reorganizes computation. In the
default mode (`program emission assemblerStatements`) every `insn` row emits
exactly one assembler-level statement; pseudos like `LoadImmediate`/
`LoadAddress`/`Call`/`Return` are allowed even though the assembler may expand
them. A stricter `encodedInstructionsOnly` mode requires every row to be one
encodable machine instruction, rejecting pseudos unless explicitly expanded.
(Saying "one real machine instruction" would be a lie about `li`/`la`/`call`.)

**Safety comes from metadata plus the validator, not from abstraction.** The
contracts a C compiler enforces structurally are here promoted into explicit,
checkable facts, and `sasm check` recomputes the ground truth from authoritative
facts and fails loudly when an edit breaks a contract. Same safety class,
opposite mechanism: instead of making wrong states unwritable, make them
**un-silent**.

### The cost model: tokens are the price, trust is the constraint

That safety is paid for in tokens, and the payment is accepted up front. Two
real instructions become ~30 rows; a real function can cost 10–20× the tokens of
the `.s` it lowers to. **Token count is explicitly not the optimization
target.** Lowering is a lossy projection `π : .sasm → .s` that strips all
context, so verbosity costs source bytes, never code — and context windows are
large, while implicit machine state is the actual failure mode.

What is *not* accepted is a fact the model might believe wrongly. The failure
mode that kills an agent format is not a big file — it is a fact that is stale,
unverifiable, or an unchecked copy of something the toolchain already knows. A
wrong fact is worse than an absent one: an absent fact forces the model to
derive (slow, sometimes wrong, but at least *attempted*); a wrong fact is
conditioned on directly. So the inclusion test is about **trust**, not size:

> **Every stored fact must be (a) consumed by the emitter (A), (b) a checkable
> contract (S-check), or (c) syntactically marked as unverified intent
> (S-intent). No fact is ever silently believed.**

Unpacking (b): an S-check fact is a **pinned contract**, not a description. A
correct `liveOut s0:number` on a call restates what liveness analysis already
derives *today* — that redundancy is exactly what makes it checkable — and its
value is that it constrains *tomorrow*: when a later edit changes the dataflow,
the validator flags the divergence instead of letting the program drift. This is
the same job a type annotation does in C, recovered without thickening the layer.

The ban on **derivable** facts (§11) follows from the trust rule, not from token
economy. `addLeftAndRight reads a1` beside an `Add` whose table already says it reads its
`secondSource` is a *zero-information copy*: it pins nothing that the row and
the table do not already pin locally, it can never fail except by being a stale
duplicate, and it trains the reader to trust unverified text. Drop it; a tool
can synthesize the register-level view on demand. (Such restatements are also
attention dilution — but that is the secondary reason now; the benchmark in
§16.1 is the empirical arbiter for any dilution argument.)

**Why explicitness helps — two mechanisms, one fix.** When an agent edits raw
`.s`, the facts its edit depends on are not merely far away in the file — mostly
they are **nowhere in the text at all**, and must be derived by simulating the
instruction stream. Two distinct hypotheses predict failure here: attention
degrading over long-range retrieval, and the model failing at serial multi-step
*derivation* of machine state. `.sasm` fixes both at once, by making the facts
explicit *and* local — good engineering, but bad science, so the benchmark
(§16.1) carries arms designed to tell the mechanisms apart. The design does not
depend on which one dominates.

Two structural consequences, unchanged:

- **Lowering is a lossy projection** `π : .sasm → .s` that discards all context,
  keeping only the minimal facts forming real instructions/operands/labels/data.
- **The handle, not the prose, is the point.** `addLeftAndRight secondSource a1`
  beats a comment because it is an *addressable, editable unit*: an agent emits a
  structured edit to one row, and the validator catches if that edit broke a
  contract. The edit → validate → diagnostic → re-edit loop (§5.1) is the product.

This is why the two-tier fact model (§11) exists: the "tier" of a fact is which
side of `π` it sits on — but the *inclusion* decision above is sharper than the
tier, and it is what keeps every stored fact either consumed, checked, or
visibly untrusted.

## 3. Why RISC-V

RISC-V is already close to an explicit IR — most instructions have a regular
`op rd, rs1, rs2` shape, so they normalize into rows cleanly. x86 hides too much
(`mul` implicitly uses rax/rdx, `push` mutates rsp+memory, `rep movsb` is a
hidden loop). Fewer hidden behaviors → fewer facts to reconstruct → a tractable
first target.

## 4. The three layers

```
  Layer 1   Semantic source IR        (SemanticScript-style; arch-free intent)
              │  lower
  Layer 2   Agentic machine IR        (.sasm — arch-aware but still semantic)   ← THIS PROJECT
              │  emit
  Layer 3   Raw assembly (.s)         (assembler/linker consume this)
```

Agents mostly edit Layer 1 or 2. Humans/toolchains consume Layer 3. This repo
is **Layer 2 + the emitter to Layer 3 + the validator**. Layer 1 integration
(SemanticScript) is out of scope for the prototype.

## 5. The killer feature: the validator

Syntax is not the point — **validation** is. Facts come in two kinds:

- **Authoritative facts** — the ground truth the emitter uses: `operation`,
  `destination`, `firstSource`, `secondSource`, `immediate`, `offset`, `symbol`,
  `target`, stack slots, data.
- **Assertions** — claims the agent makes about intent/contract: `effect none`,
  `liveIn`, `liveOut`, `leaf yes`, `out result a0`, `purpose`.

The validator recomputes the truth from authoritative facts and **checks the
assertions against it**. Target diagnostics:

```
error: function SumArray claims `effect none` but writeStdout performs EnvironmentCall
error: loadElement reads t0 before it is defined
error: stack frame 24 violates 16-byte ABI alignment
error: function main calls puts but does not preserve returnAddress
error: branch target Done is not declared a successor of Condition
error: return path leaves result register a0 undefined
error: s0 is callee-saved but written without a save/restore slot
warning: a2 is live across callPuts (caller-saved) — value may be clobbered
```

## 5.1 The product is the loop

The validator is not a final gate; it is half of the loop that makes `.sasm`
editable by an agent at all:

```
  agent edits one row  →  validate  →  diagnostic (stable code + handle + site)  →  re-edit
```

The reframe in §2.1 says the format moves information from inferred-over-distance
to local; the loop is what catches the residual cases where attention failed
*despite* that. For the loop to close, a diagnostic must be a usable gradient,
not just a description. So every diagnostic must:

1. carry a **stable code** (§14) the agent can target programmatically;
2. name the **entity handle** at fault (`I12`, `Add2`, `SlotReturnAddress`), not
   a line number — handles survive edits, line numbers do not;
3. point at the **candidate fix site** where possible — the row to change or the
   nearest conflicting fact.

Weak: `register used before def`. Strong:
`E-LIVE-UNDEF loadElement: t0 used before definition on path Prologue→Body; nearest def is computeByteOffset`.
The second is something an agent can act on in one step. Diagnostic *locality* is
as important as the check itself.

## 6. Fact schema (prototype subset)

> The **complete, refined vocabulary** — including the explicit constructs for
> values, memory regions, symbols, vector state, and the full per-entity
> predicate tables — lives in `LANGUAGE.md`. This section is the original v0
> subset, kept as a quick orientation. `LANGUAGE.md` supersedes it where they
> differ.

### Function
```
F is function
F symbol      <name>            # emitted label
F visibility  global|local
F abi         linux.riscv64 | linux.riscv64.syscall
F in   <value> <Type> <reg>     # parameter: name, type, incoming register
F out  <value> <Type> <reg>     # result
F effect      none | memory.write | memory.read | syscall | call | control.return
F leaf        yes|no            # asserts: makes no calls
F stack bytes <N>               # frame size; must be 16-aligned if > 0
F preserves   <reg>             # callee-saved reg this fn promises to restore
F purpose     "..."
```

### Block (basic block / CFG node)
```
B is block
B in          <function>
B entry       yes
B terminates  return|branch|jump|fallthrough
B successor   <block>           # may repeat
B predecessor <block>          # may repeat
B purpose     "..."
```

### Instruction
```
someInsn is insn
someInsn in            <block>
someInsn operation     <Semantic>   # semantic name from optable.tsv, e.g. Add, LoadDoubleword
someInsn destination   <reg>        # also firstSource | secondSource | thirdSource | base
someInsn immediate     <int>
someInsn offset        <int|stackSlot>
someInsn symbol        <data|extern>
someInsn target        <block>      # branch/jump destination
someInsn syscall       write|exit   # documents an EnvironmentCall
someInsn reads|writes  <value>      # value-binding dataflow (assertion, §11.2)
someInsn effect        <effect>     # assertion checked against the op's table effect
someInsn purpose       "..."
```
The authoritative field is `operation` (a **semantic name**, not a mnemonic).
The mnemonic, emit template, def/use roles, effect, control kind, and tier all
come from `sasm/optable.tsv` (see `OPCODES.md`). The mnemonic never appears in a
fact; it is produced only by `π` at lowering. `emitKind` (real/pseudo) is derived
from the table, not declared. Operand fields use full words
(`destination`/`firstSource`/`secondSource`/`thirdSource`/`immediate`), never the
RISC-V acronyms; instruction handles are descriptive, never `I1`/`R1`.

### Data
```
D is data
D section     rodata|data|bss
D type        Bytes|Int64|Int32
D value       "..." | <int>
D size        <N>
```

### Stack slot (named frame location)
```
S is stackSlot
S in          <function>
S offset      <int>            # offset from sp
S type        Int64|Address
S stores      <reg|value>      # what lives here
```

## 7. Scope & coverage strategy (target: RVA23)

The goal is a prototype that **covers the entire RVA23 profile** — but "cover"
means two different things with very different costs, so we separate them.

### 7.1 Two axes

- **Coverage** — can the model *represent* and the emitter *lower* an
  instruction? Cheap and mechanizable. **Target: all of RVA23U64 from day one.**
- **Validation fidelity** — how deeply does the validator *understand* an
  instruction (def/use, effects, liveness)? Expensive, and for the vector
  extension it is dynamic-state-dependent. **Target: tiered, scalar-first.**

This split is only possible *because* the abstraction is thin (§2.1): emission is
templating, so coverage rides on a data table, not on bespoke code per opcode.

### 7.2 Coverage is generated, not hand-written

We do not hand-maintain specs for hundreds of instructions. We generate the ISA
table from the official machine-readable **`riscv/riscv-opcodes`** repo, which
encodes, per instruction: mnemonic, operand fields, and bit encoding. From it we
derive, for free and across every RVA23 extension:

- the **emit template** (operand order, e.g. `op dest, src1, src2` / `op dest, imm(src1)`)
- **structural validation** (which fields are required; valid register classes)
- **basic def/use** (operand roles: the destination is a def, the sources are uses)

`isa.py` becomes `gen/` (the generator) + a checked-in generated table +
curated **overrides** for the things encodings don't tell us (effects, control
flow, ABI implicit regs, pseudo expansions).

### 7.3 Validation fidelity tiers

| Tier | Extensions | Fidelity |
|------|-----------|----------|
| **A — full semantics** | RV64I, M, Zicond, scalar A (Zaamo/Zalrsc/Zacas) | def/use, effects, intra-proc liveness, ABI, stack, leaf, return-defined |
| **B — structural + def/use + coarse effects** | F, D, C, B (Zba/Zbb/Zbs), Zfa, Zcb, Zfhmin, Zicbom/p/z, Zawrs, hints | emits + round-trips; effects classified coarsely (memory.read/write, float, fence); liveness over scalar regs; fp regs tracked structurally |
| **V — special / frontier** | RVV 1.0 (V, Zvfhmin, Zvbb …) | coverage + structural now. Real validation needs modeling `vsetvli → vtype/vl/LMUL/SEW` + mask regs `v0`. Deferred, designed-for (§17). |
| **P — opaque** | Zicsr, privileged, Sv*, H (S-profile) | structural only; treated as effectful black boxes |

A fact file may use any RVA23 instruction; the validator simply reports its tier
and applies the checks it can. **No silent gaps**: if liveness can't reason about
a vector instruction, it says so rather than passing it silently.

### 7.4 First working slice (still scalar)

Coverage is broad from day one, but the *first end-to-end* path we get green is
Tier A: `add2` / `hello` / `buggy`, exercising these ops (semantic names; see
`OPCODES.md`):
`Add Subtract AddImmediate LoadImmediate LoadAddress Move LoadDoubleword
StoreDoubleword LoadWord StoreWord BranchEqual BranchNotEqual BranchLessThan
BranchGreaterOrEqual BranchIfZero BranchIfNonzero Jump Call Return EnvironmentCall`.
That proves model → validate → emit before we lean on the generator for breadth.

- **ABI:** Linux riscv64 LP64D (+ raw syscall flavor for `_start`)
- **Pipeline:** `.sasm` → parse → validate → emit `.s` (no linker magic yet)
- **Run target (later):** `clang --target=riscv64 -march=rva23u64` to assemble,
  `qemu-riscv64` to execute. Both now run in the `testing/` Docker image — every
  example is snapshot-verified, assembled, and executed (see `testing.md`).

Out of scope even at RVA23 ambition: interprocedural dataflow, multiple
translation units, relocations/linker scripts, Layer-1 lowering, full RVV
semantic validation.

## 8. CLI

```
python -m sasm check  <file.sasm>          # parse + validate, print diagnostics
python -m sasm build  <file.sasm> [-o x.s] # validate then emit .s (fails on error)
python -m sasm facts  <file.sasm> <entity> # dump all facts about an entity (agent query)
```

## 9. Non-goals / pitfalls

- **Not "assembly with comments."** `# purpose: add inputs` is weak. The value
  is in *structured facts* the validator can mechanically check, not prose.
- **Don't merge Layer 1 into assembly.** The middle layer earns its keep by
  being lower than the source IR but higher than raw `.s`.
- **Authoritative vs asserted facts must stay distinct** — otherwise the
  validator has nothing to check claims against.

## 10. Repo layout

```
semanticassembly/
  README.md            ← quickstart / front door
  Dockerfile           ← self-contained eval image (runs eval.sh)
  eval.sh              ← full suite: snapshots + validator + behavioral
  research/            ← all docs (every .md except the root README)
    DESIGN.md          ← this file (framework + deep design)
    LANGUAGE.md        ← canonical fact vocabulary (refined, complete)
    OPCODES.md         ← rendered semantic op reference
    TODOS.md           ← implicit-state → explicit-fact backlog
    examples.md        ← guide to the example triptychs
    testing.md         ← the three-tier test harness
    docs.md            ← how to view / publish the webpage
  sasm/                ← the toolchain (pure Python, no deps)
    model.py           ← Entity / Program (fact store)
    parser.py          ← .sasm text → Program
    optable.tsv        ← semantic ops (source of truth)
    regs.tsv           ← register roles / save discipline
    abi.tsv            ← calling-convention tables
    isa.py             ← loads the TSV tables; exposes specs to the toolchain
    validate.py        ← diagnostics
    emit.py            ← Program → .s (the projection π)
    cli.py / __main__.py
  examples/
    simple_add2/       ← leaf function (c / sasm / s)
    challenging_sum_array/ ← loop + memory + CFG
    brainworms_fib/    ← recursion, stack frame, callee-saved
    gauntlet_ackermann/    ← nested recursion, call-result binding
    gauntlet_quicksort/    ← two recursions + mutating partition loop
    gauntlet_revlist/  ← pointer rotation, two functions per TU
    sum_of_squares/  data_demo/  linked/   ← _start programs, data, cross-TU
    hello_world/       ← standalone _start + syscalls
  tests/               ← snapshot (compiler) + check (validator)
  testing/             ← qemu behavioral harness
```

---

# Deep design

## 11. Two-tier fact model (locked)

This is the formal version of the projection from §2.1. Every predicate sits on
one side of the projection line `π : .sasm → .s`:

- **Authoritative (A)** — *survives* `π`. The minimal set of facts the emitter
  needs to produce a real instruction/operand/label/datum.
- **Asserted / context (S)** — *stripped by* `π`. Intent, dataflow, effects, ABI
  contracts, naming, rationale. The validator derives truth from A-facts and uses
  it to judge S-facts; an S-fact never changes emitted code — it can only pass,
  fail, or simply document.

The S tier splits further (per the inclusion test in §2.1) — and this split is
what governs whether an S-fact belongs in a file at all:

- **S-check** — a *checkable assertion*: a claim the validator verifies against
  derived truth (`effect none`, `liveOut`, `leaf yes`, `out result a0`, the `in`
  row's `Type`). Its job is to fail loudly when an edit broke a contract.
- **S-intent** — *irreducible intent*: the why, not derivable and not checkable
  (`purpose`, `meaning`, `condition`, a block's rationale). It is the only S-fact
  that may legitimately go unchecked, **because it is explicitly marked intent**
  and a reader/agent knows not to treat it as ground truth.
- **S-derivable** — *forbidden*. Anything inferable from A-facts plus the tables
  (restating `reads a1` beside an `Add`, or `kind pseudo` the table already
  knows). These are zero-information copies of toolchain knowledge: they pin no
  contract, they can drift stale, and a reader conditions on them as if they were
  checked. They must not be stored; a tool can synthesize them on demand.

So "adding context" is **not** unconditionally safe — and not because of token
cost (§2.1 accepts that). A derivable S-fact cannot alter the `.s` (the
projection invariant below), but it is an *unchecked* row in a format whose
entire safety story is that no row goes unchecked. The rule is therefore
stronger than "S-facts don't change `.s`":

> **Every S-fact is S-check or S-intent. There are no S-derivable facts in a
> well-formed file**, and intent facts are syntactically marked as intent.

| Entity | A facts (survive `π`) | S facts (stripped; checked or intent) |
|--------|-----------------------|----------------------------------------|
| function | `symbol`, `visibility`, `binding`, `in`.reg, `out`.reg | `in`.type, `out`.type, `effect`, `leaf`, `stack bytes`, `preserves`, `usesCalleeSaved`, `purpose` |
| block | `in`, `entry` | `terminates`, `successor`, `predecessor`, `purpose` |
| insn | `operation`, `destination`, `firstSource`, `secondSource`, `thirdSource`, `base`, `immediate`, `offset`, `symbol`, `target`, `ordinal` | `reads`, `writes`, `effect`, `syscall`, `liveOut`, `saves`, `restores`, `purpose` |
| data | `section`, `type`, `value`, `size`, `align`, `binding` | `purpose` |
| stackSlot | `offset`, `in` | `type`, `role`, `stores` |
| value | — | `type`, `signed`, `bits`, `unit`, `meaning` (all S) |

Two `type`s, two tiers — be explicit:

- **`data type`** (e.g. `Int64`) is **A**: it picks the emission directive
  (`.dword` vs `.word`), so it changes the `.s`.
- **`value type`** and the **`in`/`out` row's `Type`** are **S-check**: they do
  not change emitted bytes; they are validated (known type; width consistent with
  the accesses the value flows through, `E-TYPE`).

The `in`/`out` rows are split-tier: the **register binding is A**, the **Type is
S-check**.

Subtle cases:

- **`function in <name> <Type> <reg>`** — the *register binding* is authoritative
  (it tells the emitter/liveness where the arg arrives). The *type* is **S-check,
  not unchecked**: an unchecked fact is the worst case — it occupies attention
  and can silently be stale, so the model may condition on a wrong one. Even in
  v0 the `Type` gets a cheap structural check (known type name; width consistent
  with the access widths the value flows through). If we will not check it, it
  does not belong on the row.
- **`stack bytes N`** is S-check: the emitter does *not* generate a prologue from
  it (the prologue is explicit instructions). It exists so the validator can
  cross-check alignment and that the explicit `addi sp, sp, -N` matches.
- A fact's tier is fixed by the schema, not per-file. Tools share one table
  (`isa.py: TIER`).

**Invariant (two clauses):**
1. **Projection:** deleting every S-fact must leave a still-emittable program with
   byte-identical `.s`. (Keeps A and S honest.)
2. **No dead weight:** every S-fact present is S-check or S-intent — never
   S-derivable. (Keeps the format from diluting its own signal.)

Clause 1 is mechanically testable today (strip and diff). **Clause 2 is partially
enforced** — `E-DERIVABLE` now rejects the clearest case (a `reads`/`writes`
naming a register, §11.2), but the *general* derivable-fact linter (any S-fact
reconstructable from A-facts + tables) is still unbuilt. Two honesty notes:

- The linter is **not syntactic**. "Reconstructable from A-facts + tables" is a
  *reachability* question — e.g. deciding a `reads <value>` is redundant requires
  knowing the register binding is already forced, which is the same dataflow as
  §11.2/§13. So the linter is a real analysis, not a pattern match.
- It is therefore **load-bearing for the central claim**, not a nicety: the whole
  "no unchecked copies — no fact silently believed" guarantee rests on it. The
  register-restatement slice is live (`E-DERIVABLE`); the general analysis remains
  the one genuinely unbuilt validator.

**Update:** the value-binding side of §11.2 is now implemented — `E-VALUE-FLOW`
runs a may-analysis (set of possible values per register, unioned at merges) so a
benign phi (fib's epilogue, `a0 ∈ {number, result}`) passes while a register that
*provably* holds something else is caught. **This is deliberately one-sided, and
weaker than the §11.2 contract as stated.** Union-merge means the check fails only
when the asserted value is impossible on *every* incoming path; a
**path-dependent clobber** — value intact on one path, destroyed on another —
passes silently, and an empty (unknown) set is never flagged. §11.2 specifies the
ideal must-semantics ("on every incoming path"); closing the gap statically
requires first-class phi *values*. The minimal phi — a declared **`mergesFrom`**
(LANGUAGE §4) — has landed, and the **runtime taint check (§19.2) enforces the
must-semantics on every executed path**, catching exactly the path-dependent
clobbers this paragraph concedes (verified: fib's naive variant). Statically,
E-VALUE-FLOW still catches must-clobbers, not may-clobbers, and the docs say so
rather than overclaiming.

## 11.1 Ordering: positional, canonical, and formatter-protected

Instruction order is authoritative — it determines the emitted sequence — but it
is the **one authoritative property carried by position rather than a predicate.**
That is a deliberate choice, justified by the inclusion test (§2.1), and it is
split cleanly so position never carries a *long-range* dependency:

- **Within a block**, execution order = the order the `insn` rows appear in
  source. The next instruction is the adjacent row — a **local** fact, so we add
  no `next`/`seq` *chain* (a linked list would be a long-range structure to
  maintain, and S-derivable). The one allowed explicit form is an optional
  **`ordinal`** key (`allocateFrame ordinal 10`, gaps for insertion): it is *authoritative*
  for order, the formatter sorts file layout by it, and it exists purely for
  agent-edit robustness — an ordinal survives reformatting and lexical sorting,
  decoupling order from physical position. Absent an `ordinal`, source order
  applies. Either encoding keeps the dependency local; neither is a chain.
- **Across blocks**, control-flow *semantics* are never positional — they live
  in the explicit CFG (`successor`/`target`/`fallthrough`/`terminates`). But
  block *layout* **is positional and authoritative**: the emitter places blocks
  in source order (entry block first), and `π` never synthesizes an instruction
  (thinness, §2.1 — inserting a jump would emit a statement no row asked for).
  The two are reconciled by a **checked constraint**, not an assumption: every
  implicit fall-through edge — a branch's not-taken path, or a block whose
  terminator falls through — must land on the **physically next block** in
  source order, else `E-CFG-LAYOUT` naming the block to move (or the explicit
  `Jump` row to add). Reordering blocks is a legal edit exactly when it keeps
  every fall-through edge adjacent; the validator, not the agent's memory, is
  what enforces that. *(Specified; enforcement is TODOS A3 — today a block
  reorder emits silently wrong code, the sharpest unguarded edge in v0.)*

Because intra-block order is positional, it must be **protected** so an edit or a
reformat cannot silently corrupt it:

1. **Stable handles, not line numbers.** Entities are addressed by descriptive
   handle (`saveReturnAddress`), and handles do *not* imply order — never sort
   them. Order is insertion order of `insn` rows within their block, nothing else.
2. **The formatter (`sasm fmt`) defines the one canonical layout** — entities
   grouped by container, `insn` rows in execution order, deterministic spacing —
   and is **idempotent and order-preserving** (it never reorders rows, only
   normalizes them). Canonical layout means a re-serialized file diffs minimally.
3. **Round-trip determinism makes accidents visible — the layout check makes
   them errors.** Since `π` is deterministic, any reorder shows up as a `.s`
   diff; but a diff only protects an edit that has a golden to compare against.
   The guards that hold during ordinary editing are `E-CFG-LAYOUT` (fall-through
   adjacency, above) and the terminator rules below.
4. **The terminator is the last instruction of its block.** A row after a
   `return`/`jump`/`branch` terminator in the same block is `E-CFG-LAYOUT` (it
   would emit as unreachable text the CFG does not describe); a non-entry block
   with no terminator must have exactly one declared successor — its
   fall-through — and that successor must be physically next. The block's
   `terminates` fact, when present, is S-check: it pins the terminator kind and
   is cross-checked against the actual last instruction.

An agent that wants to reorder instructions does so by reordering rows (a
structured edit the formatter preserves); an agent that wants to change control
flow edits `successor`/`target`, not file position; an agent that reorders
*blocks* must keep every fall-through edge adjacent or add an explicit `Jump`
row — and `E-CFG-LAYOUT` tells it which block broke. The three are never
confused.

**Two encodings, one per block — no mixing.** Source position and explicit
`ordinal` are both legal, and "ordinal wins if present" is only unambiguous when a
block commits to one. So the rule is **all-or-nothing per block**: either *every*
`insn` in a block carries an `ordinal`, or *none* does. A block with some
ordinaled and some bare rows is `E-ORDER-MIXED` — the ambiguous case is rejected
rather than silently resolved. The formatter normalizes a fully-ordinaled block by
sorting rows to match ordinals (and may renumber to a canonical gap, e.g. 10/20/30);
it leaves a bare block in source order. Choosing the mode is per block, not per
file, so a function may keep simple blocks positional and ordinal only the block an
agent is actively churning.

## 11.2 When `reads`/`writes` is allowed (the value-binding rule)

`insn reads`/`writes` is the sharpest place the S-derivable ban bites, so the
rule is explicit:

- **A register name is forbidden.** `addLeftAndRight reads a1` is **S-derivable** —
  the op table says `Add` uses `secondSource`, and `secondSource a1` is right there
  on the row. Restating it is dilution (`E-DERIVABLE`). The register-level def/use
  set is *always* computed from `operation` + the register fields, never written by
  hand. (This is why the §2 example carries no `reads returnAddress` on `Return` —
  the table already knows.)
- **A `value` name is allowed, as S-check.** `addLeftAndRight reads left` asserts
  the *register↔value binding at this program point* — that the register the op reads
  currently holds the value `left`. That is **not** derivable from any single row;
  it is the long-range dataflow fact raw assembly hides (§2.1's "which value is in
  `a1` here"). It is checkable by value-flow: the value read must equal the value
  last written to that register on every incoming path. (That is the ideal
  must-semantics; v0 implements the weaker may-form — see the §11 update for the
  exact gap.) Promoting it converts a long-range inference into a local, checkable
  row — exactly what earns inclusion.

So the discriminator is simply **value-names yes, register-names no**, and every
referenced value must resolve to a declared `value` entity (else `E-REF`) — that
resolution is what makes the binding checkable rather than decorative. A
`reads`/`writes` naming something that is neither a declared value nor checkable
is not S-intent (it is not marked intent) — it is just wrong, and the linter
rejects it.

**The call-result rule** (found by the gauntlet shakedown, 2026-06-09): `writes
<value>` on a `Call` row binds the **callee's result**, which arrives in the
ABI's first return register (`a0`) — *not* the link register the op table lists
as the call's def. Without this rule the most common dataflow fact of all — "a0
now holds f's result" — was inexpressible, and every call-result merge had to
stay a comment-only phi (fib's epilogue note). With it, `callOuter writes
result` makes the value checkable downstream like any other binding.
Multi-register returns (a0+a1) stay out of scope with LANGUAGE §13.

**Honest caveat — the row is local to *read*, but global to *verify*.** "Converts
a long-range inference into a local, checkable row" is true for the *reader*: an
agent sees `addLeftAndRight reads left` in one place instead of reconstructing it. But the
*checker* does not get off cheaply. "The value read equals the value last written
to that register on every incoming path" is **reaching-definitions over named
values** — a real intra-procedural dataflow pass with the same CFG and fixpoint
machinery as liveness (§13), which it shares. So the value-binding check is not a
local row comparison; it is a whole-function analysis. That is fine — it is the
validator's job, and it is exactly the analysis a human would have to run in their
head to edit raw `.s` correctly — but the design states it plainly so an
implementer is not surprised that a "local fact" needs a global pass to confirm.
The *win* is real and unchanged: the cost of being **wrong** moved from the agent
(silent) to the validator (caught); locality helps the writer, the dataflow pass
protects the reader.

## 12. Derived truth (what the validator computes)

From A-facts alone, per instruction `I` with its row looked up by `op` in
`optable.tsv`:

- `def(I)`  = registers written  (table `defines` × actual operand fields)
- `use(I)`  = registers read      (table `uses` × actual operand fields)
- `eff(I)`  = set of effects      (table `effect`)
- `succ(I)` = control successors  (table `control` + `target`/fallthrough)

These are the ground truth. Examples (left column is `operation`; mnemonic shown
for orientation only):

```
Add               (add)   → def={destination} use={firstSource,secondSource} eff={}          succ=fallthrough
StoreDoubleword   (sd)    → def={}             use={secondSource,base}        eff={memory.write} succ=fallthrough
LoadDoubleword    (ld)    → def={destination}  use={base}                     eff={memory.read}  succ=fallthrough
BranchEqual       (beq)   → def={}             use={firstSource,secondSource} eff={}          succ={fallthrough, target}
Call              (call)  → def={returnAddress, caller-saved} use={a0..aN}    eff={call}      succ=fallthrough
EnvironmentCall   (ecall) → def=ABI-syscall-clobber          use=syscall-args eff={syscall}
Return            (ret)   → def={}             use={returnAddress, out-reg}   eff={control.return} succ={}
```

`zero` (`x0`) is never a real def or use (writes discarded, reads are constant 0).

**`Call` is conservative by default, narrowable at the call site.** Without
call-site facts, a `Call` is modelled as clobbering the *whole* ABI caller-saved
set and using *all* argument registers — safe but noisy (it can make `W-CLOBBER`
over-fire). When the callee signature is known, narrow it with call-site facts:
`arg <value> <reg>` (the actual arguments) and `clobbers <reg>...` (the actual
clobber set, default `callerSaved`). v0 ships the conservative model; call-site
ABI facts are how you quiet it. (LANGUAGE §3.)

## 13. CFG & liveness (the real dataflow)

v0 ships intra-procedural backward liveness over the explicit CFG — not the
single-block approximation. Algorithm per function:

1. **Build blocks.** Members via `insn.in == block`, ordered by source order.
   Block order via `block.in == function`, entry block first.
2. **Build edges.** `succ(B)` = successors of B's terminator instruction, taken
   from **declared facts** — never inferred from physical layout (per §11.1,
   layout is *validated against* the CFG, not used as an edge source):
   - branch: `{ target-block, declared fallthrough successor }` (the `fallthrough`
     fact on the branch, or the block's non-target `successor`)
   - jump: `{ target-block }`;  `ret`: `{}`
   - fallthrough terminator: `{ declared fallthrough successor }`
   The declared `successor` set must **exactly equal** the terminator-derived
   edge set — both directions. A branch target missing from `successor` is
   `E-CFG-EDGE` (enforced); a declared successor the terminator *cannot take* is
   equally an error (a stale edge silently widens every liveness/value-flow
   merge, masking real diagnostics — *specified; enforcement TODOS A3*). When
   `predecessor` rows are present they must be the exact inverse of the
   `successor` relation (same code, same status). No edge is ever inferred from
   "the next block in the file."
3. **Seed.** `live-out(exit via ret)` = function `out` registers ∪ callee-saved
   (they must reach the caller intact). `live-in(entry)` available set = `in`
   registers ∪ {sp, gp, tp, ra}.
4. **Fixpoint** (standard):
   ```
   live-in(B)  = use(B) ∪ (live-out(B) − def(B))
   live-out(B) = ⋃ live-in(S) for S in succ(B)
   ```
   iterate to fixpoint over reverse-postorder.
5. **Checks** (turn truth into diagnostics):
   - **use-before-def**: a register in `use(I)` that is not in the available set
     at `I` (forward pass: available = seed ∪ defs so far along all paths) →
     `error E-LIVE-UNDEF`.
   - **clobber-across-call**: register live across a `call` that is caller-saved
     and not re-defined after → `warning W-CLOBBER`.
   - **dead store**: `def(I)` never in any subsequent `live-in` → `warning W-DEAD`.
   - **asserted liveIn/liveOut mismatch**: declared set ≠ computed → `error`.
   - **return value undefined**: `out` reg ∉ available set at the `ret` → `error`.

v0 may start with the forward available-set checks (use-before-def, return
defined) and add the full backward fixpoint (dead store, clobber) incrementally;
the CFG construction is shared by both.

## 14. Diagnostic catalog (stable codes)

Codes are part of the contract so agents can target them programmatically.
Status: **✓** enforced today · **◌** specified, enforcement pending (TODOS A3) —
a ◌ code is still the contract; until its check lands, the facts it would guard
must be treated as intent (LANGUAGE, enforcement table).

```
✓ E-PARSE-*     malformed fact / missing required field / unterminated string /
                empty pipe clause   (unterminated-string case: ◌)
✓ E-ISA-OPCODE  unknown opcode
✓ E-ISA-REG     not a valid register name
✓ E-ISA-FIELD   opcode missing a required field (e.g. addi without imm)
✓ E-REF         `in`/`target`/`offset`/value reference points at an undeclared
                entity; `memory region` / effect-qualifier names must resolve
                to declared memoryRegions
✓ E-EFFECT      asserted effect set ≠ computed effect set (e.g. `effect none` + ecall)
✓ E-ABI-ALIGN   stack frame not 16-byte aligned
✓ E-ABI-PRESERVE callee-saved reg written but not saved/restored/declared
                (set-wise; per-return-path completeness and slot pairing: ◌)
✓ E-LIVE-UNDEF  register used before defined on some path
✓ E-LIVE-RET    result register undefined at return
✓ E-LEAF        `leaf yes` but a call/ecall is present
✓ E-CFG-EDGE    branch target not a declared successor; declared `terminates`
                ≠ the block's actual terminator (incl. noreturn-syscall kind)
                (successor-exactness + predecessor inverse, §13: ◌)
✓ E-VALUE-FLOW  `reads/writes <value>` not satisfied by reaching-defs
                (may-form; must-form needs phi values, §11/§17)
✓ E-ORDER-MIXED a block mixes ordinaled and bare insns (§11.1)
✓ E-LIVE-ASSERT a declared `liveOut` register is not actually live there (§13)
✓ W-UNREACHABLE a block has no path from the function entry
✓ E-TYPE        value Type unknown, or width inconsistent with its accesses
✓ E-DERIVABLE   an S-fact restates A-facts + tables (register-name slice;
                the general linter: ◌, TODOS A1)
✓ W-CLOBBER     value live across a caller-saved boundary
✓ W-DEAD        value defined but never used
✓ E-SLOT-RANGE  stack slot offset outside the declared frame — an ERROR, not a
                warning: the access lands in the caller's frame and can pass
                behavioral tests when the victim slot is unused (upgraded from
                W-SLOT by the mutation tier's first finding, §19)
                (slot *extent* and pairwise overlap: ◌)
✓ E-CFG-LAYOUT  fall-through edge not physically adjacent; instruction after the
                terminator; function runs off its last block; targeted entry
                block until §15.1's label rule lands (§11.1). A noreturn syscall
                (`syscall` name with `return -` in syscalls.tsv) counts as a
                terminator of kind `syscall`
✓ E-RESERVED    a row writes a register the platform ABI reserves (abi.tsv
                `reserved`: gp/tp) — previously the only decorative table row
✓ E-STACK-OP    sp is an explicit surface: a stackPointer write must declare
                `effect stack.allocate`/`stack.free`
✓ E-STACK-BALANCE constant-only sp adjustments; per-path frame balance at every
                return; consistent depth at merges; allocation must equal the
                declared `stack bytes` (the A3 prologue cross-check, now
                static); a moved sp with no declared frame is an error.
                E-ABI-ALIGN additionally fires at any call reached at a
                misaligned depth
✓ W-LINT        legal-but-never-intended shapes: self-moves, results discarded
                into `zero`, branches whose target equals their fall-through
◌ E-DUP         duplicate single-valued fact; entity re-`is`-declaration; block
                handles colliding case-insensitively; function/data/symbol label
                collisions (LANGUAGE, grammar rules)
◌ E-ORDER-KEY   `ordinal` not a decimal integer, or duplicated within a block
◌ E-DATA        data contract: bss requires `size` and forbids `value`;
                data/rodata require `value`; Bytes `size` = literal byte length;
                unknown data `type`
◌ E-EXT-UNAVAILABLE  op's extension not in `program target` (LANGUAGE §17)
```

Runtime contract codes (`R-*`) are a separate, design-only catalog in §18.3 —
same diagnostic shape, trace-scoped semantics (§18.1), never substitutes for a
◌ static check above.

Diagnostic shape (per §5.1 — diagnostics are the loop's feedback signal, so they
must be a usable gradient): `severity code handle: message (fix-site)`. The
**handle** is the entity at fault (`I12`, `Add2`, `SlotReturnAddress`) — *not* a
line number, because handles survive edits and line numbers do not. The message
names the **candidate fix site** where one exists (the row to change or the
nearest conflicting fact). Example:
`E-LIVE-UNDEF loadElement: t0 used before definition on path Prologue→Body; nearest def is computeByteOffset`.
`check` exits non-zero if any `E-*` present; `build` refuses to emit on `E-*`
(override `--force`).

## 15. Emission (Layer 2 → Layer 3)

The emitter is the projection `π` made concrete: it reads *only* A-facts,
templates them, and discards all context. It is intentionally dumb — no analysis,
no rewriting. (Any cleverness belongs in a separate optimization pass over the
`.sasm`, never in `π`.)

- **Sections:** group `data` by `section` → `.section .rodata` etc. emit
  `<name>:` then `.ascii "..."` (Bytes) / `.dword`/`.word` (Int64/Int32).
- **Functions:** in source order. `visibility global` → `.global <symbol>`. Emit
  `<symbol>:` then blocks. A block gets a local label `.L<block>` only if it is a
  branch/jump target (keeps `add2` clean).
- **Instructions:** `emit` template from `optable.tsv` (keyed by `op`), fields resolved from
  A-facts. `offset` resolves through a `stackSlot` name to its numeric `offset`.
  `target` resolves to the block's label.
- **Determinism:** identical input → byte-identical `.s`. No timestamps, no
  reordering. This makes diffs reviewable (an agent edit = a minimal `.s` diff).

### 15.1 Pinned emission rules (IMPLEMENTED — `sasm/emit.py`)

These were reverse-engineered from the golden examples and are now exact (the
snapshots are byte-identical across all examples). A second implementer must
follow them:

- **File order:** data sections first (`.rodata`, `.data`, `.bss` order), then a
  single `\t.text`, then functions in source order. (Function-only files begin
  with `\t.text`.)
- **Function:** `visibility global` → `\t.globl\t<symbol>`; then `<symbol>:`. The
  symbol comes from `symbol` (not the handle).
- **Blocks:** entry block first, then source order. The **entry block emits no
  label** (the function symbol serves). A non-entry block emits
  `.L<lowercased-handle>:` **iff** some instruction's `target` names it. (So
  fallthrough-only blocks like `Body`/`Recurse` get no label.)
- **Instruction line:** fill the op's `emit` template, then prefix a tab and
  replace the template's first space with a tab → `\t<mnemonic>\t<operands>`;
  operand-less ops emit just `\t<mnemonic>`. Operands keep the template's `, `.
- **Field resolution:** register fields (`destination`/`firstSource`/
  `secondSource`/`thirdSource`/`base`) map through `regs.tsv` `asm`
  (`returnAddress`→`ra`); `offset` naming a `stackSlot` → that slot's numeric
  `offset`; `target` → the block's `.L` label; `immediate`/`symbol` verbatim.
- **Whitespace:** lines joined by `\n`, exactly one trailing `\n`, no blank lines.
  Emit raw LF even on Windows (text-mode stdout would inject CRs).

Pinned edge rules (added after the v0 snapshot; the first two are specified but
not yet implemented — TODOS A3):

- **Targeted entry block:** if any instruction's `target` names the entry block,
  the emitter must emit `.L<lowercased-entry-handle>:` immediately after the
  function symbol label (two labels, one address). Today the emitter suppresses
  it, so the emitted `.s` references an undefined label — the assembler rejects
  it loudly (not silent corruption), and `E-CFG-LAYOUT` will reject it at
  validation until the label rule lands.
- **Data contract (`E-DATA`):** `bss` data requires `size` and forbids `value`
  (today a sizeless bss entity emits `.zero None`); `data`/`rodata` require
  `value`; for `Bytes` the declared `size` must equal the literal's byte length
  (the emitter trusts `size` for `.size`); an unknown data `type` is an error
  (today it silently falls back to `.dword`).
- **Label namespace:** block labels are `.L<lowercased handle>` and the
  assembler's label namespace is file-scoped — hence the file-wide,
  case-insensitive handle-uniqueness rules in LANGUAGE (grammar rules), checked
  as `E-DUP`.
- **`emit` does not validate — by design.** `π` is dumb: an invalid program
  emits deterministic nonsense (a missing operand field appears literally as
  `None`). `build` is the guarded path (validate, refuse on `E-*`, then emit);
  `emit` exists for inspecting the projection. Agents should treat `build` as
  the only write path to `.s`.

Round-trip honesty (now real, `testing/`): emitted `.s` (1) byte-matches the
golden via `tests/snapshot.sh`, (2) assembles with `clang --target=riscv64
-march=rva23u64` / cross-gcc, and (3) runs correctly under `qemu-riscv64`
(`add2`=5, `sum_array`=15, `fib(10)`=55).

## 16. Layer-1 lowering (future, sketch only)

SemanticScript op → `.sasm` is a register-allocation + ABI-binding pass:

```
compute is operation          Add2 is function
compute in left  Int64        Add2 in left  Int64 a0      (allocate arg regs)
compute in right Int64    →    Add2 in right Int64 a1
compute out      Int64        Add2 out result Int64 a0    (ABI return reg)
compute do add(left,right)     addLeftAndRight operation Add
                                 destination a0 firstSource a0 secondSource a1
                               returnResult operation Return
```

The interesting, hard parts (register allocation, spilling to stack slots, call
lowering with caller-saved spills) are deferred. v0 hand-writes Layer 2 so we can
validate and emit without solving allocation first. This ordering is deliberate:
**prove the fact model and validator are useful before automating their input.**

## 16.1 Falsifiability — the benchmark the thesis owes

§2.1 makes three claims — agents can *understand*, *edit*, and *manage/trace*
`.sasm` better than `.s` — and each is an empirical hypothesis, not a proof. The
project owes the experiment that could refute each one. The design: **four arms ×
three task families × two protocols.**

### The arms

All arms carry the same *information*; they differ only in where it sits and what
form it takes. That is the variable under test.

- **(a) raw `.s`** — facts absent from the text; must be derived by simulating
  the machine.
- **(c) `.s` + a prose fact block** at the top of the function stating the same
  liveness/ABI/frame/region facts in English — information *present*, but
  non-local to the edit site and unstructured.
- **(d) `.s` + the same facts as inline comments** on the relevant instructions —
  information present *and local*, human-idiomatic, but **unaddressable and
  unchecked**.
- **(b) `.sasm`** — information present, local, addressable, and checked.

Arm (d) is the load-bearing control. **b-over-d is the only comparison that
isolates addressability + checkability from mere locality** — it tests what the
format adds beyond good comments. b-over-c conflates locality with structure;
c-over-a only confirms that information helps (true and uninteresting). A
two-arm a-vs-b result, however large, proves nothing about the design.

### Task family 1 — comprehension (the *understand* claim)

Questions whose ground truth is long-range or implicit, asked over each arm with
no tools: *which value is in `a1` at `<insn>`? what does this call clobber? which
slot holds the saved `s0`? is the frame still 16-aligned if I add an 8-byte
slot?* Metric: accuracy. This family also discriminates the two §2.1 mechanisms:
if (d) ≈ (a), locality/retrieval was never the bottleneck; if (c) ≈ (b), distance
doesn't matter and mere *presence* does (the derivation hypothesis). Either
result reshapes the format's priorities, which is why the family exists.

### Task family 2 — edits (the *edit* claim)

The mutation set, each requiring a long-range dependency to get right: resize a
stack frame (offsets must follow), swap an operand register (liveness must stay
consistent), add a spill (slot + save/restore + frame size), reorder two blocks
(CFG edges must hold), retarget a branch. Apply each as an instruction to an
agent over every arm; the oracle is lower + assemble + run under qemu against a
known-correct result. Two protocols, run separately, because they test
**different claims**:

- **Protocol 1 — one shot (the format claim).** No feedback of any kind. Metric:
  fraction of edits that assemble *and* preserve behavior, first try. This tests
  the representation alone. Prediction: **b ≥ d > c > a**, gap widening with
  function size.
- **Protocol 2 — closed loop (the system claim).** Every arm gets a feedback
  channel with the **same iteration and token budget**: arms a/c/d get assembler
  errors plus behavioral test output; arm b gets the same *plus* `sasm check`
  diagnostics. Metrics: success within N rounds, rounds-to-success,
  tokens-to-success. This tests §5.1's claim that diagnostics are a usable
  gradient — without budget parity it would measure tooling, not representation.
  Prediction: **b's gap over d widens from Protocol 1 to Protocol 2** —
  checkability only pays when the loop closes.

If b ≈ d under Protocol 2, the structure and the validator buy nothing over good
local comments and the project is overbuilt — a result worth knowing, and the
reason arm (d) must be designed in now rather than after the format has an
ecosystem to defend.

### Task family 3 — trust under staleness (the *manage/trace* claim)

The §2.1 invariant is *no fact is silently believed*. Test it directly: prepare
arm (d) and arm (b) variants in which exactly one local fact is **wrong** — a
stale comment, or a stale S-check row, as a careless previous edit would leave.
Prediction: in (d) the lie propagates into the agent's edit silently; in (b)
`sasm check` flags the stale row (`E-LIVE-ASSERT`, `E-VALUE-FLOW`, `E-EFFECT`,
…) before it can do harm. This is where unchecked-but-local formats are
predicted to be *actively worse than no facts at all* — the strongest version of
the trust argument, and the easiest to falsify.

A second traceability probe: give the agent a file plus a sequence of row edits
and ask *which edit broke a named contract*, answerable from stable handles +
diagnostics alone. Metric: identification accuracy and tokens spent. This is the
"manageable" pillar made measurable.

### What the results calibrate

The benchmark is also the empirical arbiter the inclusion test (§2.1) cannot be
by itself: a fact class whose presence never moves family-1 or family-2 scores
is noise by this measure — drop it from the vocabulary even though tokens are
cheap. And the size sweep matters everywhere: every gap is predicted to **widen
with function size**, because that is where implicit state outgrows what a model
can reliably derive.

The bet, stated so it can lose: **(b) wins on exactly the tasks whose
correctness lives at a distance or in unchecked state, and the gap widens with
size and with loop closure.** If it does not, the explicitness argument is wrong
and the format is ceremony.

## 17. Open questions (filtered through the inclusion test)

The §2.1 criterion resolves some of these directly. A construct earns first-class
status **iff it pins a checkable contract** — typically by converting a long-range
or implicit dependency into a local fact the validator can fail — otherwise it
stays marked intent or is dropped. Token cost never decides; checkability does.

- **Symbolic values vs registers — *resolved in principle*; phi merges now have
  a working subset.** `reads left` (value) vs `firstSource a0` (register). The
  taint interpreter (§19.2) forced the phi question and landed the minimal
  answer: **`mergesFrom`** (LANGUAGE §4) declares that a value is legitimately
  another on some path (`result mergesFrom number` — fib's base case), checked
  by both the static union and the runtime taint. Full SSA-style value identity
  ("the value in `a1` here is the one produced at `I7`") remains open; promote
  it only if D1 shows the residual gap matters.
- **Multi-valued returns / structs** beyond a0/a1 — *not* resolved by the
  attention lens; this is an expressiveness/scope question (see LANGUAGE §13).
- **Pseudo expansion visibility.** Record `LoadImmediate`'s expansion as child
  facts, or leave it to the assembler? Inclusion test says: only record it if an
  agent ever needs to edit *at* the expanded level; otherwise it is derivable.
  v0: leave to assembler.
- **Cross-function (interprocedural) effect/clobber summaries** for `call` —
  scope question, not resolved by the lens; deferred.
- **How much of the ABI/register/CSR data is pure tables vs code.** Leaning: pure
  data (`abi.tsv`/`regs.tsv`/`csr.tsv`), code only for the dataflow.

## 18. Runtime debugging — the dynamic half of the trust invariant (design only)

**Status: the R-contract catalog (§18.3) is LIVE in-process** — the §19.2 taint
interpreter implements it (`sasm exec`) without any qemu/gdb plumbing. What
remains gated below is the *real-binary* debugger (breakpoints on the emitted
code under qemu); the design was adversarially reviewed by three independent
critiques (2026-06-09; their blockers are folded in below).
**Sequencing gate:** §18 stays design-only until (i) D1's Protocol-2 result exists
— if `.sasm` ≈ inline-comments there, a semantic debugger is more overbuild, not
a rescue — and (ii) the A3 static codes whose contracts the R-checks would
backstop have landed. This follows §16's discipline: prove the fact model and
validator are useful before extending their consumers.

Nothing in this section adds a stored fact or predicate. The debugger is a
*reader* of the existing fact base, like `sasm facts`; the format is unchanged.

### 18.1 Rationale, and what a passing run proves

The validator checks what is statically decidable; the §11 may/must gap and parts
of the §10.5 ◌ table are **path-dependent** — undecidable statically, observable
on a concrete execution. Runtime contract checks (`R-*`) close them *on the
executed path*, with the same diagnostic discipline as §5.1.

The split is governed by a rule, because it is easy to abuse:

> **Each R-code names its static counterpart and checks only the dynamic
> residue.** A contract that is statically decidable belongs to `E-*`/`W-*`; an
> R-check never substitutes for a pending ◌ static check, and landing one closes
> no A3 item. The genuine runtime payload is what no static pass can decide:
> value identity on the actual path (`R-VALUE-FLOW`), preservation across an
> actual call (`R-LIVE-OUT`), and the first enforcement of facts that are ◌
> statically (`R-EFFECT` for `syscall <name>`).

And trace-scope honesty, mirroring §7.3's no-silent-gaps rule:

> **An R-check result is trace-scoped.** A passing run proves each asserted
> contract held on the executed path under this input — nothing more. It never
> changes a fact's §10.5 status: a ◌ fact remains intent after any number of
> clean runs. Every session therefore ends with a **coverage report** naming the
> declared contracts the run did *not* exercise (blocks not entered, calls not
> taken, time spent in un-fact'd code), so the absence of an R-diagnostic can
> never be read as verification.

### 18.2 Handle→address: the sidecar map

The 1:1 invariant is row ↔ assembler *statement*, not row ↔ machine instruction
(pseudos expand; RVC compresses). So the mapping composes two deterministic
tables:

1. `sasm build --map` emits a sidecar: insn handle → emitted `.s` line (π already
   knows it; derived from A-facts only). The sidecar embeds a **content hash of
   the `.sasm` and of the emitted `.s`**; a session refuses a map whose hashes do
   not match its artifacts — stale derived data is an error, not a warning. (The
   §11 ban governs facts stored in `.sasm`; on-demand tool output is kept honest
   by the hash, not by the ban.)
2. The assembler's own DWARF line table (`-Wa,--gdwarf-4`; reader:
   `objdump --dwarf=decodedline`, filtered to the `.s` filename) maps line →
   address set. A multi-expansion pseudo row owns all its addresses; a
   breakpoint on it is its first address; a pc anywhere in the set is attributed
   to the row, and `step` never stops mid-row.

Pins that make this exact: emitted `.s` carries no `.file`/`.loc` directives
(true of `emit.py` today — now an invariant; hand-inserted `.loc` would suppress
the assembler's table); assemble with `-mno-relax` (suppresses `R_RISCV_RELAX`,
freezing our TU's internal layout; other objects' relaxation only shifts our base
address, which the link-time-finalized line table already absorbs); static
non-PIE (the existing `testing/` target), so stub addresses equal ELF vaddrs;
RVC means instructions are 2 or 4 bytes — no adapter logic may ever compute
"next = pc+4".

**Multi-TU** (the `linked` example breaks anything less): a session takes N
(fact-base, sidecar) pairs. Handles are TU-qualified (`main:Entry`); unqualified
handles are accepted iff globally unique, else an ambiguity error — the repo's
own `linked/` declares `Entry` in both TUs. `state`/`position` select the fact
base by which TU's address range contains pc.

### 18.3 The runtime contract catalog (R-*)

Codes reuse the static catalog's family segments so an agent routing on
`*-ABI-*` or `*-LIVE-*` sees both halves of one contract. Shape (extends §5.1
with the two dimensions runtime adds):
`severity code handle@activation: observed X, declared Y (declaring row R;
observed at row I, stop N)` — the fix is either row R (stale fact) or the path
into I (wrong code); **the diagnostic names both and adjudicates neither**.

- **`R-VALUE-FLOW`** *(static counterpart: E-VALUE-FLOW may-form; residue: value
  identity on the actual path — the must-check)*. At a `reads v` row, the bound
  register's runtime value must equal v's last observation in the same
  activation. **Observation points for v are:** `writes v` rows (read the
  destination *after* execution: breakpoint + one single-step), the function's
  `in v <reg>` binding at activation entry, and `restores` rows whose slot
  `stores` v. The value→register binding per row is resolved by re-running the
  static value-flow pass; rows where it is empty/ambiguous are reported
  **unwatchable**, never guessed. Because annotations are partial by default
  (LANGUAGE §3) and the static semantics deliberately treat unannotated defs as
  fresh, **R-VALUE-FLOW is a warning by default** — a validator-clean file with
  legitimate unannotated re-derivations must not fail at runtime. It is promoted
  to an error for v only when every def of v on the executed path carries a
  binding. `writes` on a `zero`-destination row is skipped (the grammar rules
  already make it a static error).
- **`R-LIVE-OUT`** *(static counterpart: E-LIVE-ASSERT liveness; residue:
  preservation across an actual call)*. Applies **only to rows whose op control
  is `call`**: read the register at the call row, compare at the matching
  activation-filtered return. On non-call rows (loop back-edges like
  `sum_array`'s `loopBackEdge liveOut t0:sum`) a `liveOut reg:v` gets the
  R-VALUE-FLOW binding check only — preservation across a jump is vacuous, and
  the spec says so rather than silently redefining the fact.
- **`R-ABI-PRESERVE`** *(static counterpart: E-ABI-PRESERVE set-wise + its A3
  per-path refinement; residue: the saved slot being clobbered between save and
  restore — aliasing no static pass here can see)*. Callee-saved registers plus
  `returnAddress` compared between activation entry and each exit event,
  observed at the `Return` row *before* it executes. Redundant-backstop portion
  is marked as such in output.
- **`R-CFG-EDGE`** *(static counterpart: E-CFG-EDGE / E-CFG-LAYOUT ◌; residue:
  indirect transfers and runtime divergence)*. Mechanism: consecutive
  covered-block-head pairs **per activation** must be declared edges; `Return`
  transfers are checked against the shadow activation's recorded return target
  (the static edge set for `ret` is empty). One-sided by construction: a
  transfer landing mid-block hits no head breakpoint and is undetectable except
  under an optional strict mode that single-steps terminator rows
  (order-of-magnitude slowdown; off by default).
- **`R-ABI-ALIGN`** *(static counterpart: E-ABI-ALIGN + the A3 prologue
  cross-check; residue: non-constant sp adjustment)*. sp % 16 at call rows.
- **`R-ABI-FRAME`** *(static counterpart: the ◌ `stack bytes`-vs-prologue
  check)*. The activation's first sp adjustment must equal the declared
  `stack bytes`.
- **`R-EFFECT`** *(static counterpart: E-EFFECT, and the ◌ `syscall <name>`
  table check — this is that fact's first enforcement anywhere)*. At each
  covered `EnvironmentCall` row, the runtime `a7` must match the row's `syscall`
  fact via `syscalls.tsv`, and the observed syscall set must be ⊆ the declared
  effects (may-effects: declared-but-not-executed never flags). **One-sided:**
  only ecalls at covered rows are observed; a syscall inside un-fact'd code
  (libc) is invisible. Whole-process audit (`qemu -strace`) is out of scope v0.
  (qemu's gdbstub has no syscall catchpoints; this design does not need them.)

### 18.4 Activations — the part recursion and tail calls make hard

Value names are function-scoped; runtime instances are **activation**-scoped
(recursive `fib` has one `number` per frame). The adapter keeps a shadow
activation stack: entry events push (sp at entry, return target from the
activation record — never from the live `ra`, which inner calls overwrite);
return events pop.

- **Every temporary breakpoint is activation-filtered.** `stepOver`, `stepOut`,
  and the R-LIVE-OUT after-call observation stop only when the shadow stack
  matches the depth recorded at arm time; otherwise the adapter auto-continues.
  (A naive "break after the call row" stops in the innermost recursive frame —
  the flagship example breaks the naive design.)
- **`TailCall` is an exit event**: run R-ABI-PRESERVE at the tail row, then pop
  the current activation and push the callee's, inheriting the popped frame's
  return target. (Control `jump`, no link — a function exiting via `tail` never
  executes its own `Return`.)
- **Process exit closes all open activations** and resolves pending
  `stepOut`/`continue` with an exit event. Entry-point functions
  (`prog entry`, `_start`-style: `hello_world`, `linked/main`) are activation
  roots: exempt from R-ABI-PRESERVE and return checks — they exit via
  `EnvironmentCall exit`, and their `Return`-shaped contracts are vacuous.
- **Un-fact'd code is opaque, not invisible.** Sessions start in libc/`_start`,
  not covered code: the session implicitly runs to the first covered breakpoint.
  Entering an uncovered frame suspends per-row checks and resumes them on
  return; boundary checks (R-LIVE-OUT, R-ABI-PRESERVE) still apply *across* the
  opaque call. `position` outside coverage returns `{coverage: none, pc,
  nearest-symbol}` — an answer, not an error. The coverage report (§18.1) counts
  opaque time so "no diagnostics" is never read as "harness verified".

Slot locations are read by memory read at (activation frame sp + slot offset)
and are well-defined only between the frame-allocate and frame-free rows.

### 18.5 The API — batch first, session later

**v0 is batch-shaped**, because the §16.1 agent loop is batch-shaped (run,
collect diagnostics, edit, repeat):

```
sasm run <file.sasm>… [--harness h.c] --break <handle>… --assert-contracts
         [--dump-state] [--trace-blocks] --json
```

Run to each break, dump the requested observations, stream R-diagnostics, exit;
"rewind" is a deterministic re-run to an earlier stop, identified by a monotone
stop counter. Determinism pins: same binary, same breakpoint set,
`qemu-riscv64 -seed 0`, fixed argv/env (`env -i`) — sp values are comparable
only within one run unless pinned. The fact base gates its own tooling: rewind
is refused when the declared/observed effects include an input syscall.

Named-value answers carry an honesty label: **`observed`** (the binding was
runtime-confirmed in this activation — watched from an observation point) or
**`declared`** (asserted by a `reads`/`writes` fact this run has not confirmed).
`state` never prints a bare value for a `declared` binding. `valueBindings
complete` is honored for gap-free watching only once its static check lands
(§10.5); until then it is intent, and blind spots are reported.

**v2 (sketch, gated on the D1 result):** an interactive JSON-over-stdio session
adding `step` (advance until pc leaves the row's address set; on a `Call` row
enters the callee iff covered, else auto-stepOver), `stepOver`/`stepOut`
(activation-filtered), `watch <value>` (**activation-scoped by default** — a
global watch in recursive code compares different activations' instances and
reports spurious changes on every stop; `--global` streams
(activation, row, value) tuples and makes no change-detection claim), `trace
blocks`, `position`. Verbs are full words per the casing rules — `stepOut` and
`position`, not gdb's `finish`/`where`.

Plumbing for both: `qemu-riscv64 -g <port>` GDB remote stub. The adapter runs on
the **host** and connects over TCP into the existing `testing/` container (the
image has no Python and mounts the repo read-only — in-container adapters are
ruled out as drafted); the line-table read happens via the container's
cross-objdump. Stub facts the design relies on: Z0 software breakpoints,
`vCont;s`, register/memory reads all work under qemu linux-user; **watchpoints
(Z2–Z4) do not exist in linux-user mode** — the software-breakpoint-only design
is forced, not stylistic; a single-step over a blocking `ecall` blocks the stub
until the syscall returns. Breakpoints at shared addresses (function symbol =
entry block = first row; §15.1's targeted-entry case) dedupe to one Z0 that
dispatches all attached semantics exactly once.

### 18.6 Non-goals and cost honesty

No TUI, no gdb interop for humans, no expression evaluator, no pretty-printers,
no multi-arch, no privileged/kernel debugging. The consumer is an agent; the
output is facts. Contract mode costs O(dynamic hits) gdbstub round-trips —
fine at test scale (`fib(10)`), pathological at `fib(30)`; the spec targets
test-scale inputs and says so.

### 18.7 Benchmark interaction (honesty)

Parity in §16.1 Protocol 2 applies to the **raw substrate** (run / break /
registers / exit status — every arm can have gdb-on-`.s` at equal budget). The
R-contract checks consume facts the other arms do not have, so parity for them
is impossible by construction: they are part of **arm b's declared diagnostic
channel**, exactly like `sasm check` — never smuggled in as neutral tooling.
Family 3's stale-fact prediction is about `sasm check` alone; the debugger is
excluded from family 3 or reported as a separate condition. And the claim
underlying this whole section — that handle/value-level observation beats
gdb-on-`.s` for agents — is itself an empirical hypothesis: if §18 is built,
the benchmark gains a debugging task family with an arm-d-style control (gdb
plus the comment-annotated `.s`) before that claim may appear in any headline.

## 19. Verification strategy — how the verifier earns trust (IMPLEMENTED, growing)

The validator is this project's trusted computing base, and hand-written
dataflow analysis is a hard thing to trust. §19 is the answer to the honest
objections (verifier complexity, false confidence, facts-can-lie, two-layer
debugging): **don't make the analyzer smarter — change where truth comes
from.** Three principles, each with a live implementation.

### 19.1 Borrow truth, don't author it

The cheapest correct oracle is one someone else built and millions test daily:

- **The C reference is a standing differential oracle.** Every example ships a
  `.c`; the behavioral tier runs the `.sasm`-emitted code against real inputs
  under qemu (and the `.c` is the spec of what those runs must produce). The
  verifier's job shrinks from *establishing* correctness to *explaining*
  failures and catching them earlier and cheaper.
- **Tables are borrowed, not authored** — `riscv-opcodes` for encodings and
  def/use shapes (§7.2), the psABI for `abi.tsv`. A new architecture is a data
  project (tables + overrides), not a verifier rewrite: the kernel (CFG,
  liveness, value-flow, layout) is architecture-independent.
- **The assembler and linker stay in the loop** (Tier 1): every emitted `.s`
  must assemble as real RISC-V before anything else is believed.

### 19.2 Executable semantics beat analytical semantics — the taint interpreter

**`sasm exec` (`sasm/interp.py`, ~600 lines, pure Python, zero deps)** executes
the fact rows directly on a tiny RV64IM machine where every register and every
8-byte memory cell carries a shadow **value tag** beside its concrete bits. The
dangerous S-check facts stop being derived and become **observed**:

| fact | how it is observed |
|------|--------------------|
| `reads v` / `writes v` / `returns v` | the tag either is `v` (or a declared merge of it) or it isn't, at this row, on this trace → `R-VALUE-FLOW` |
| `liveOut r:v` | snapshot `r` at the call row, compare at the resume row → `R-LIVE-OUT` |
| `effect …` | the activation either touched non-stack memory / called / trapped or it didn't (internal-effect rule applied; observed ⊆ declared) → `R-EFFECT` |
| `preserves r` / frame freed | callee-saved bits and `sp` at entry vs return, per activation → `R-ABI-PRESERVE` |
| `stack bytes N` | the first `sp` adjustment either is `-N` or it isn't → `R-ABI-FRAME` |
| `successor …` | every *executed* control transfer is checked against the CFG → `R-CFG-EDGE` |
| sp alignment at calls | `R-ABI-ALIGN` |

Two design points make it honest and sharp:

- **The return address is a single-use token**, not a fake integer: `Call`
  mints one, `Return` consumes it. Clobber `ra` and the machine halts with
  `R-ABI-PRESERVE` naming the row — a diagnosis where real silicon gives a
  hexdump.
- **Tag policy mirrors the static may-form** (§18.3): an unannotated def sets
  the tag to *unknown*; a `reads v` errors only when a source holds a
  *different* tag; all-unknown passes and is counted *unconfirmed* in
  coverage. A validator-clean file with legitimate unannotated re-derivations
  never fails at runtime — and every run ends with the §18.1 coverage report
  (blocks not executed, reads unconfirmed), so trace-passing is never mistaken
  for verification.

This closes, *on executed paths*, the very gaps §11 documents: the
path-dependent clobber that union-merge provably misses is caught concretely
(`fib`'s naive variant computes −510 and `R-VALUE-FLOW` names the row), and the
`stack bytes`-vs-prologue cross-check that is still ◌ statically is enforced
dynamically. The interpreter is also the in-process realization of §18.3's
R-catalog — the qemu/gdb adapter remains gated (§18 header), but the contract
checks it was designed to run are live today.

**It forced a language refinement on day one.** Running `fib(10)` flagged the
epilogue 89 times (= F(11), one per base-case activation): on the base path
`a0` holds `number`, which *is* the result — the documented phi that static
union-merge silently absorbed. Dynamic semantics don't let you defer the phi
question, so the minimal §17 design landed: **`mergesFrom`** (LANGUAGE §4), a
declared, checkable phi — `result mergesFrom number` — accepted by both the
static union and the runtime taint check, while any *undeclared* tag still
errors. The general SSA design stays open; the working subset is no longer.

### 19.3 Fuzz the verifier, not just the program — the mutation tier

**`tests/test_mutation.py`** generates mutations of known-good examples
(immediate/offset perturbations, operand swaps on non-commutative ops, branch
retargeting, save/restore deletion) and enforces the invariant:

> Every behavior-changing mutant is caught by `validate` (static) or by the
> taint interpreter's vectors (dynamic), or it emitted byte-identical `.s`
> (provably equivalent). Anything else is a **HOLE**, and holes fail the build
> unless allow-listed *with a written reason* — the verifier's known
> blind-spot ledger.

First run, 75 mutants: 32 caught statically, 30 dynamically, 13 equivalent —
after the tier's **first real finding**: moving a stack slot outside the frame
only *warned* (`W-SLOT`) while the access corrupted the caller's frame and
passed behavioral tests (the victim slot happened to be unused). That is the
false-confidence scenario made concrete, found by machine, and fixed:
out-of-frame slots are now the error `E-SLOT-RANGE`. The verifier stopped
being something you trust and became something you measure.

### 19.4 The anti-compiler ratchet (locked)

The "drift toward C/Rust/Zig" risk has a structural answer, now a governing
rule:

> **`π` may never change emitted bytes based on analysis.** Register
> allocation, instruction selection, layout optimization, type-driven codegen
> — any feature that makes emission *smarter* — is a compiler feature and is
> rejected. Types, regions, effects, and every other S-fact can **fail** a
> build; they can never **shape** one.

A compiler makes decisions; this layer checks claims. The projection invariant
(§11: stripping all S-facts leaves byte-identical `.s`) is mechanically
testable, so the ratchet cannot loosen silently. Vocabulary creep is policed by
the D1 calibration rule: a fact class that never moves edit accuracy is dropped.

### 19.5 What is deliberately not done

SMT / formal per-block equivalence (translation validation): π is 1:1
templating, so there is no translation to validate — the thing needing
verification is *facts vs. behavior*, and the taint interpreter gets most of
that for a fraction of the effort, with failure modes a human can read.
Likewise full symbolic execution: trace-scoped concrete checking plus the
coverage report is the honest, cheap point on the curve. Both remain options
if the D1 benchmark ever shows the residual gap matters.

Remaining §19 work is tracked in TODOS H: `check --coverage`/`--strict`
(per-fact verification labeling as CLI output), differential exec-vs-qemu
state comparison, and a broader mutation-operator corpus.
