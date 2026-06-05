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
`secondSource`, and no mnemonic appears. Those are **S-derivable** — attention
dilution, forbidden by §11. But `reads left`/`writes result` *are* present: they
name **values**, not registers, so they assert the long-range register↔value
binding (§11.2) that earns its place.

The agent no longer patches opaque text — it patches `addLeftAndRight.secondSource`,
`Add2.stack bytes`, an `effect`, a `value` type, a stack slot. Each is a
**semantic handle**: an addressable row the agent edits and the validator
re-checks (§5.1). And the fact raw assembly hides hardest — *which value is in
`a1` here* — is now the local, checkable row `addLeftAndRight reads right`, not
something to reconstruct across the function.

## 2.1 Stance: an attention-conditioning format

This is a **thin** layer over assembly — roughly 1:1 with *assembler statements*,
never a new IR that reorganizes computation. In the default mode
(`program emission assemblerStatements`) every `insn` row emits exactly one
assembler-level statement; pseudos like `LoadImmediate`/`LoadAddress`/`Call`/
`Return` are allowed even though the assembler may expand them. A stricter
`encodedInstructionsOnly` mode requires every row to be one encodable machine
instruction, rejecting pseudos unless explicitly expanded. (Saying "one real
machine instruction" would be a lie about `li`/`la`/`call`.) But the reason the
layer exists is mechanistic, not aesthetic.

**The claim is not "agents understand it better."** It is that the format changes
what an LLM's attention can do *reliably*. When an agent edits raw `.s`, getting
the second operand right on an `add` means reconstructing register liveness across
the whole function — which value sits in `a1` *here* depends on every prior
instruction. That dependency is long-range, implicit, and stateful: exactly the
regime where attention degrades. In `.sasm`, `addLeftAndRight secondSource a1` is
a **local, token-adjacent fact**.
We are not making the model smarter; we are moving the information it needs from
*must-be-inferred-over-distance* to *present-locally*. The validator then exists
to catch the cases where attention failed anyway.

That reframes verbosity. It is **load-bearing, but not free** — every fact is
tokens, and the real scarce resource is not token count but *attention over
distance*. So the optimization target is precise:

> **Minimize the number of facts the model must integrate across distance or
> control flow.** Not "minimize tokens," not "maximize facts."

Which gives an **inclusion test** for any fact, replacing "when in doubt, store
more." A fact earns its place iff it is one of:

1. **Long-range / cross-control-flow** — reconstructing it would require attending
   far away or across branches (liveness, who-owns-`a1`-here, frame offsets,
   what region a pointer touches). *Promote it: it converts inference to lookup.*
2. **Irreducible intent** — the *why*, which exists nowhere in the code and cannot
   be derived or checked (`purpose "save n across the calls"`). *Keep it, but mark
   it as intent so the model never conditions on it as ground truth.*

Anything else is **derivable** — inferable from authoritative facts plus the
tables (`Add` uses `secondSource`; `secondSource a1` is right there). Derivable
facts are **not neutral context — they are attention dilution.** Drop them;
generate them on demand from a tool if a reader wants them. Restating `reads a1`
next to an `Add` whose table already says so is the anti-pattern.

Two structural consequences, unchanged by the reframe:

- **Lowering is a lossy projection** `π : .sasm → .s` that discards all context,
  keeping only the minimal facts forming real instructions/operands/labels/data.
  Context costs source bytes, not code.
- **The handle, not the prose, is the point.** `addLeftAndRight secondSource a1`
  beats a comment because it is an *addressable, editable unit*: an agent emits a
  structured edit to one row, and the validator catches if that edit broke a
  contract. The edit → validate → diagnostic → re-edit loop (§5.1) is the product.

This is why the two-tier fact model (§11) exists: the "tier" of a fact is which
side of `π` it sits on — but the *inclusion* decision above is sharper than the
tier, and it is what keeps the format from drowning its own signal.

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
  `qemu-riscv64` to execute. Neither installed yet → v0 verifies `.s` by snapshot.

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
  research/            ← the design / research docs
    DESIGN.md          ← this file (framework + deep design)
    LANGUAGE.md        ← canonical fact vocabulary (refined, complete)
    OPCODES.md         ← rendered semantic op reference
    TODOS.md           ← implicit-state → explicit-fact backlog
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
  knows). These are attention dilution, not context. They must not be stored;
  a tool can synthesize them on demand.

So "adding context" is **not** unconditionally safe. It cannot alter the `.s`
(the projection invariant below), but a derivable S-fact still costs attention
and can drift stale. The rule is therefore stronger than "S-facts don't change
`.s`":

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
  "no dead weight / no attention dilution" guarantee rests on it. The
  register-restatement slice is live (`E-DERIVABLE`); the general analysis remains
  the one genuinely unbuilt validator.

**Update:** the value-binding side of §11.2 is now implemented — `E-VALUE-FLOW`
runs a may-analysis (set of possible values per register, unioned at merges) so a
benign phi (fib's epilogue, `a0 ∈ {number, result}`) passes while a clobbered
value is caught. The phi question is thus resolved *in practice* for checking
(merge = union), even though first-class phi *values* remain a §17 design item.

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
- **Across blocks**, order is **never** positional. Control flow is the explicit
  CFG (`successor`/`target`/`terminates`). The emitter derives a block *layout*
  from the CFG — placing a `fallthrough` successor physically next, or emitting an
  explicit jump if it cannot. So the file order of blocks is cosmetic; only
  intra-block sequence is load-bearing.

Because intra-block order is positional, it must be **protected** so an edit or a
reformat cannot silently corrupt it:

1. **Stable handles, not line numbers.** Entities are addressed by descriptive
   handle (`saveReturnAddress`), and handles do *not* imply order — never sort
   them. Order is insertion order of `insn` rows within their block, nothing else.
2. **The formatter (`sasm fmt`) defines the one canonical layout** — entities
   grouped by container, `insn` rows in execution order, deterministic spacing —
   and is **idempotent and order-preserving** (it never reorders rows, only
   normalizes them). Canonical layout means a re-serialized file diffs minimally.
3. **Round-trip determinism catches accidents.** Since `π` is deterministic, any
   reorder shows up as a `.s` diff — an accidental shuffle cannot pass silently.

An agent that wants to reorder instructions does so by reordering rows (a
structured edit the formatter preserves); an agent that wants to change control
flow edits `successor`/`target`, not file position. The two are never confused.

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
  last written to that register on every incoming path. Promoting it converts a
  long-range inference into a local, checkable row — exactly what earns inclusion.

So the discriminator is simply **value-names yes, register-names no**, and every
referenced value must resolve to a declared `value` entity (else `E-REF`) — that
resolution is what makes the binding checkable rather than decorative. A
`reads`/`writes` naming something that is neither a declared value nor checkable
is not S-intent (it is not marked intent) — it is just wrong, and the linter
rejects it.

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
   from **declared facts**, never physical block layout (§11.1 says layout is
   cosmetic — the emitter derives it from the CFG, not the reverse):
   - branch: `{ target-block, declared fallthrough successor }` (the `fallthrough`
     fact on the branch, or the block's non-target `successor`)
   - jump: `{ target-block }`;  `ret`: `{}`
   - fallthrough terminator: `{ declared fallthrough successor }`
   Cross-check the two declared sources (`successor`/`predecessor` on blocks vs
   `target`/`fallthrough` on the terminator) against each other → `E-CFG-EDGE` on
   mismatch. No edge is ever inferred from "the next block in the file."
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

```
E-PARSE-*     malformed fact / missing required field
E-ISA-OPCODE  unknown opcode
E-ISA-REG     not a valid register name
E-ISA-FIELD   opcode missing a required field (e.g. addi without imm)
E-REF         `in`/`target`/`symbol` points at an undeclared entity
E-EFFECT      asserted effect set ≠ computed effect set (e.g. `effect none` + ecall)
E-ABI-ALIGN   stack frame not 16-byte aligned
E-ABI-PRESERVE callee-saved reg written but not in `preserves` / no save slot
E-LIVE-UNDEF  register used before defined on some path
E-LIVE-RET    result register undefined at return
E-LEAF        `leaf yes` but a call/ecall is present
E-CFG-EDGE    branch target not reachable / not a declared successor
E-VALUE-FLOW  `reads/writes <value>` not satisfied by reaching-defs (§11.2 dataflow)
E-ORDER-MIXED a block mixes ordinaled and bare insns (§11.1)
E-TYPE        `in`/`value` Type unknown, or width inconsistent with its accesses
E-DERIVABLE   an S-fact is reconstructable from A-facts + tables (§11 clause 2)
W-CLOBBER     value live across a caller-saved boundary
W-DEAD        value defined but never used
W-SLOT        stack slot offset outside declared frame
```

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
three snapshots are byte-identical). A second implementer must follow them:

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

Known edge (not hit by examples): a branch targeting the *entry* block would need
a label the emitter currently suppresses — revisit if it arises.

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

## 16.1 Falsifiability — the headline is a bet

The §2.1 claim (the format makes agent edits *more reliable* by converting
long-range inference into local lookup) is an empirical hypothesis, not a proof.
If it is the headline, the project owes the experiment that could refute it:

> **Edit-accuracy benchmark.** Fix a set of mutations that each require a
> long-range dependency to get right — resize a stack frame (offsets must follow),
> swap an operand register (liveness must stay consistent), add a spill (slot +
> save/restore + frame size), reorder two blocks (CFG edges must hold). Apply each
> as an instruction to an agent over (a) the raw `.s` and (b) the `.sasm`, lower
> both, and compare against a known-correct result. Metric: fraction of edits that
> assemble *and* preserve behavior, first try.

The bet is that (b) wins on exactly the mutations whose correctness lives at a
distance, and that the gap widens with function size. If `.sasm` does *not* beat
`.s` on these, the attention argument is wrong and the format is just ceremony —
so this benchmark is the thing that earns (or sinks) the whole premise. It also
calibrates the inclusion test: a fact that never changes edit accuracy is, by
this measure, S-derivable noise.

**The two-arm version is a confound; the real experiment needs three.** A skeptic
rightly says: of course the format with liveness/ABI written into it wins — you
leaked the answer into the prompt. The trivial claim "more facts help" is not what
we are testing. The actual claim is "the *same* facts, made **local and
addressable**, help more than when they must be inferred." So add a control arm:

- **(a) raw `.s`** — facts must be inferred.
- **(c) raw `.s` + a prose comment block** stating the same liveness/ABI/region
  facts in English at the top of the function — same *information*, but not local
  to the edit site and not addressable as structured rows.
- **(b) `.sasm`** — same information, local and addressable.

The discriminating prediction is **b > c > a**. b-over-c isolates
locality+addressability from mere information content (the thing actually being
claimed); c-over-a just confirms information helps (uninteresting). If b ≈ c, the
structured format buys nothing over a comment and the project is overbuilt — which
is a result worth knowing. Designing arm (c) now, while the benchmark is a sketch,
keeps it from quietly proving the trivial thing later.

## 17. Open questions (filtered through the inclusion test)

The §2.1 criterion resolves some of these directly. A construct earns first-class
status **iff it converts a long-range dependency into a local fact *and* can be
checked** — otherwise it stays documentation or is dropped.

- **Symbolic values vs registers — *resolved in principle*.** `reads left`
  (value) vs `firstSource a0` (register). Make values first-class **iff** doing so
  turns a long-range dep into a local, checkable fact (e.g. "the value in `a1`
  here is the same one produced at `I7`" — a real long-range link worth a typed,
  checkable SSA name). Where a value name is *only* a gloss on a register that is
  already local, it stays S-intent or is dropped — not promoted as unchecked docs.
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
