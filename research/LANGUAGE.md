# Semantic Assembly — Language Reference

This is the canonical vocabulary. It refines the schema sketched in `DESIGN.md §6`
to make RISC-V's implicit state (see `TODOS.md`) explicit, while keeping the
project's shape:

- **One fact per line**: `<subject> <predicate> <arg>...` or `<subject> is <type>`.
- **Two tiers** (DESIGN §11): every predicate is **A** (authoritative — survives
  lowering `π`) or **S** (stripped by `π`). S splits into **S-check** (validator
  verifies it) and **S-intent** (the irreducible *why*, marked as intent).
  Stripping all S-facts must leave byte-identical `.s`.
- **Tokens are the price; trust is the constraint** (DESIGN §2.1). The format
  converts implicit machine state into explicit local rows, and the token cost of
  that is accepted up front. Inclusion test: every stored fact must be consumed
  by the emitter (A), a checkable contract (S-check), or marked intent
  (S-intent) — **no fact is silently believed**. Anything **derivable** from
  A-facts + tables is an unchecked copy that can drift stale — leave it out.
  (`reads a1` beside an `Add` whose table already says `rs2` is the
  anti-pattern.)
- **Intent predicates** — `purpose`, `meaning`, `condition` — are the only
  S-facts allowed to go unchecked, *because* they are syntactically intent.
  Everything else in S must be checkable — and §10.5 (the enforcement table)
  tracks which checks exist *today*; an S-check predicate whose check hasn't
  landed yet must be read as intent until it does.
- **Data lives in TSV tables**, not the grammar:
  `optable.tsv` (ops), `regs.tsv` (registers), `abi.tsv` (calling conventions),
  `formats.tsv` (encoding formats + immediate ranges), `extmap.tsv` (op-class →
  extension), `syscalls.tsv` (syscall numbers/registers), `csr.tsv` (control &
  status registers).

## 0.5 The inclusion rule (what to surface) — governing

> **The goal is not "make assembly explicit." It is: make *dangerous* implicit
> state explicit, checkable, and locally editable.**

Surface an implicit fact **iff at least one is true**:

1. It affects correctness across **more than one instruction**.
2. It crosses a **control-flow edge**.
3. It crosses a **call / syscall / ABI boundary**.
4. It names a **memory region, stack slot, or aliasing assumption**.
5. It is required to **prove a function contract**: effect, leaf, stack, return,
   preserve.
6. It is **irreducible human/agent intent** that cannot be derived.

Otherwise **do not store it** — derive it from the tables or display it on demand.
Surfacing derivable trivia stores unchecked copies the reader will wrongly trust
(DESIGN §2.1/§11). This rule is
the operational form of the inclusion test and it governs every predicate below:
a predicate exists so that *some* fact can satisfy 1–6, and any individual use
that satisfies none of 1–6 is S-derivable and rejected (`E-DERIVABLE`).

**v0 surface priority** (highest danger first):

| # | Implicit thing | Why it matters |
|---|----------------|----------------|
| 1 | Register value identity | wrong-operand / clobber edits |
| 2 | Stack slots / frame size | broken offsets, ABI misalignment |
| 3 | Caller/callee-saved rules | call-boundary corruption |
| 4 | CFG edges / fallthrough | broken branches |
| 5 | Return definedness | invalid function outputs |
| 6 | Memory region / type | unsafe loads/stores/reorders |
| 7 | Effects / syscalls | false `effect none` / `leaf yes` |
| 8 | Width / sign extension | subtle 32/64-bit bugs |

## Casing rules (locked)

| Kind | Case | Examples |
|------|------|----------|
| entity types | lowercase camelCase | `function` `block` `insn` `stackSlot` `value` `program` |
| predicates | lowercase camelCase, **full words, no acronyms** | `operation` `destination` `firstSource` `immediate` `preserves` |
| entity handles (subjects) | descriptive full words — **never** cryptic labels like `I1`/`R1`; functions/blocks/slots/regions PascalCase, instructions camelCase verbs | `Fib` `Recurse` `SlotReturnAddress` `callFibNumberMinusOne` |
| value names | camelCase, full words (no single letters) | `number` `loopIndex` `firstResult` `result` |
| op values | PascalCase, full words | `Add` `LoadDoubleword` `BranchEqual` |
| data type names | PascalCase, full words | `Int64` `Address` `Boolean` `Int64Pointer` |
| register names | **hybrid** — special registers spelled out, numbered registers kept | `returnAddress` `stackPointer` `globalPointer` `threadPointer` `zero`; `a0` `s0` `t0` `fa0` |
| effects / enums | lowercase, dotted if scoped | `memory.read` `stack.allocate` `heap` `acquire` |

**Operand fields are full words, never the RISC-V acronyms:** `operation` (not
`op`), `destination` (not `rd`), `firstSource`/`secondSource`/`thirdSource` (not
`rs1`/`rs2`/`rs3`), `immediate` (not `imm`). `base` and `offset` are already words
and stay. **Register names are hybrid** (your choice): the four special-purpose
registers read as their role — `returnAddress` (`x1`/`ra`), `stackPointer`
(`x2`/`sp`), `globalPointer` (`x3`/`gp`), `threadPointer` (`x4`/`tp`), plus `zero`
(`x0`) — while the numbered files `a0–a7`, `s0–s11`, `t0–t6` (and float `fa*`,
`fs*`, `ft*`) keep their ABI names. `regs.tsv` maps each to its assembler mnemonic
for emission, so the `.s` still uses `ra`/`sp`. (Hybrid was chosen deliberately
over ABI-only spellings; the cost is the `regs.tsv` alias mapping, the benefit is
that the dangerous registers read as their role at the edit site.)

**Instruction-handle naming.** Handles are descriptive **verb-object / action-result**
names — `addLeftAndRight`, `saveReturnAddress`, `loadCurrentElement`,
`branchIfDone`, `returnResult`. They must be unique within their function and
should be a few words at most: not `I1` (cryptic) and not
`addTheTwoInputsAndStoreInTheReturnRegister` (prose essay). The handle is a patch
target and a diagnostic anchor, so it earns being readable but not verbose.

**`operation` is the opcode-table key, not a SemanticScript operation.** It names a
row in `optable.tsv` (a machine instruction), *not* a high-level Layer-1
`operation`. The ecosystem now has two senses of the word; in `.sasm`, `operation`
is always the machine-level opcode key.

## Grammar & namespace rules (locked)

These pin the edge cases an agent edit can hit. Rules marked *(◌ A3)* are
specified but their check is pending (TODOS A3) — until it lands, the listed
behavior is what actually happens today.

- **One namespace, file-global, across all entity kinds.** Handles live in a
  single namespace per translation unit: a `value` and a `block` cannot share a
  name. An entity has **exactly one `is` declaration**; a second `is` (same or
  different type) is `E-DUP` *(◌ A3 — today it silently re-types the entity and
  merges its facts)*.
- **Single- vs multi-valued predicates.** Predicates carrying one authoritative
  slot — `is`, `operation`, the register fields, `immediate`, `offset`, `symbol`,
  `target`, `in` (membership), `entry`, `ordinal`, `visibility`, `binding`,
  `section`, `type`, `value` (data), `size`, `align`, `leaf`, `terminates` — may
  appear **at most once per entity**; a duplicate is `E-DUP` *(◌ A3 — today the
  **first** row silently wins, so an agent that "edits" by appending a new row
  produces dead text: exactly the silent failure this format exists to prevent;
  edit the existing row, never append a duplicate)*. Predicates that are
  genuinely sets — `successor`, `predecessor`, `effect`, `reads`, `writes`,
  `requires`, `returns`, `liveOut`, `liveIn`, `saves`, `restores`, `preserves`,
  `usesCalleeSaved`, `in`/`out` (function), `arg`, `calls`, `targets`, `memory`,
  `stack` — may repeat.
- **Strings are verbatim bytes.** Double quotes delimit; there is **no escape
  processing** (`"Hello\n"` keeps the literal backslash-n for the assembler).
  Consequences: a literal `"` is not representable in v0 (it would also corrupt
  the emitted `.ascii "…"`), and an **unterminated string is `E-PARSE`**
  *(◌ A3 — today it silently consumes to end of line)*.
- **Reserved characters.** Outside strings, `#` starts a comment and `|`
  separates pipe-sugar clauses (§20); neither can appear in a bare token.
- **Label namespaces are file-scoped in the assembler.** Block labels emit as
  `.L<lowercased handle>`, so block handles must be unique **file-wide and
  case-insensitively** (`Done` vs `done` collide after lowering) — `E-DUP`
  *(◌ A3)*. Function `symbol`s, `data` entity names, and `symbol` entities share
  the assembler's global label namespace and must be pairwise distinct —
  `E-DUP` *(◌ A3)*.
- **`ordinal` is a decimal integer.** A non-integer ordinal or a duplicate
  ordinal within a block is `E-ORDER-KEY` *(◌ A3 — today a non-integer ordinal
  crashes emission with a Python traceback instead of a diagnostic)*.
- **`writes` to a discarded destination.** A `writes <value>` on an instruction
  whose only destination register is `zero` binds nothing (the write is
  discarded by hardware); it is an error — the fact asserts a binding that
  cannot exist *(◌ A3; today it is silently inert)*.

---

## 0. `program` — translation-unit context (NEW)

Makes the ISA/target assumptions explicit instead of living in `-march` flags.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is program` | — | | declares the unit |
| `target` | A | `<profile>` | e.g. `rva23u64` → assembler `-march` |
| `xlen` | A | `32`\|`64` | register width; gates `ld`/`*Word` ops |
| `abi` | A | `<name>` | default ABI key into `abi.tsv` |
| `pic` | A | `yes`\|`no` | position-independent → relocation strategy |
| `compressed` | A | `yes`\|`no` | allow C-extension encodings |
| `emission` | A | `assemblerStatements`\|`encodedInstructionsOnly` | `assemblerStatements` (default): every `insn` row emits exactly one assembler statement (pseudos like `LoadImmediate`/`Call` allowed). `encodedInstructionsOnly`: every row must be one encodable machine instruction; pseudos are rejected unless expanded. Resolves the "1 row = 1 instruction" tension |
| `endian` | S | `little`\|`big` | little assumed |
| `entry` | A | `<symbol>` | program entry point |
| `purpose` | S-intent | `"..."` | |

---

## 1. `function`

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is function` | — | | |
| `symbol` | A | `<name>` | emitted label |
| `visibility` | A | `global`\|`local` | `.globl` or not |
| `binding` | A | `global`\|`local`\|`weak` | symbol binding (`.weak`) |
| `abi` | S | `<name>` | calling convention (key into `abi.tsv`) |
| `in` | A+S | `<value> <Type> <reg>` | parameter — **reg is A**, value/Type are S |
| `out` | A+S | `<value> <Type> <reg>` | result — reg A, value/Type S |
| `effect` | S-check | `<effect> [<region>\|<name>]` | declared observable effect, union-checked vs instruction-derived truth — `effect none`, `effect memory.read inputBuffer`, `effect memory.write outputBuffer`, `effect syscall.write`, `effect call` |
| `leaf` | S-check | `yes`\|`no` | asserts: makes no calls |
| `calls` | S | `<symbol>` | callee (may repeat) |
| `usesCalleeSaved` | S-check | `<reg>` | a callee-saved register this function reuses (and therefore must save/restore) |
| `preserves` | S-check | `<reg>` | promise: this callee-saved register holds its caller value on every return path |
| `stack` | S | `bytes <n>` / `align <n>` | frame size / alignment |
| `framePointer` | S | `<reg>` | frame pointer in use (e.g. `s0`) |
| `variadic` | S | `yes`\|`no` | takes variable args |
| `privilege` | S | `machine`\|`supervisor`\|`user` | execution level |
| `unwind` | S | `yes`\|`no` | request `.cfi_*` emission |
| `purpose` | S-intent | `"..."` | |

**`preserves` is per-touched-register, not exhaustive.** A function need only name
the callee-saved registers it actually *uses* (`usesCalleeSaved`) and *preserves* —
never the whole `s0–s11` file. The validator's contract is purely about what the
body touches: **if the function writes a callee-saved register and does not restore
the caller's value on every return path → `E-ABI-PRESERVE`.** A register the
function never writes needs no facts. (So `preserves` documents+checks an obligation
the body incurred; it is not a blanket ABI restatement, which would be derivable.)

---

## 2. `block` — basic block / CFG node

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is block` | — | | |
| `in` | A | `<function>` | membership (drives layout) |
| `entry` | A | `yes` | function entry block → gets the symbol label |
| `terminates` | S-check | `return`\|`branch`\|`jump`\|`fallthrough`\|`call`\|`syscall` | pins the terminator kind; cross-checked against the block's actual last instruction (a contract against future edits, not a description). `syscall` = a noreturn syscall (`exit`/`exit_group` — `return -` in `syscalls.tsv`) |
| `successor` | S-check | `<block>` | CFG edge (may repeat). The declared set must **exactly equal** the terminator-derived edges — a stale successor silently widens every dataflow merge (DESIGN §13) |
| `predecessor` | S-check | `<block>` | optional; when present, must be the exact inverse of the `successor` relation (a redundant-but-checked contract from the receiving side) |
| `loop` | S | `header`\|`body`\|`none` | loop role |
| `backEdgeTo` | S | `<block>` | marks the loop back-edge |
| `purpose` | S-intent | `"..."` | |

**Layout is positional and checked (DESIGN §11.1).** Blocks emit in source order,
entry first; `π` never inserts a jump. Every implicit fall-through edge must
therefore land on the physically next block (`E-CFG-LAYOUT`), the terminator must
be the block's last row, and a non-entry block without a terminator must declare
exactly one successor — its fall-through. Reordering block declarations is a
legal edit only when fall-through adjacency is preserved.

---

## 3. `insn` — one machine instruction

The authoritative identity is `operation` (a semantic name from `optable.tsv`);
the table supplies mnemonic, emit template, def/use roles, effect, control kind,
tier.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is insn` | — | | |
| `in` | A | `<block>` | membership (drives order) |
| `operation` | A | `<Semantic>` | the operation |
| `destination` `firstSource` `secondSource` `thirdSource` `base` | A | `<reg>` | register operands |
| `immediate` | A | `<int>` | immediate value |
| `offset` | A | `<int>`\|`<stackSlot>` | load/store displacement (slot name resolves to its offset) |
| `symbol` | A | `<symbol>`\|`<data>` | symbolic operand |
| `target` | A | `<block>` | branch/jump destination |
| `reads` | S-check | `<value>` | a declared `value` the op's source register holds **here** (may repeat). **Value names only — never a register** (see below) |
| `writes` | S-check | `<value>` | a declared `value` the op's result register now holds (may repeat). Value names only |
| `effect` | S-check | `<effect> [<region>\|<name>]` | asserted effect (checked vs table); may carry a qualifier — `effect memory.read inputBuffer`, `effect syscall.write`, `effect call` |
| `memory` | S-check | `region <region>` / `type <Type>` / `align <n>` / `volatile yes` | memory-access facts (region + type, not just the bare effect) |
| `requires` | S-check | `<value> in <reg>` | the value must occupy that register **here** (cross-distance binding) |
| `valueBindings` | S-check | `complete` | asserts the `reads`/`writes` on this insn list *every* symbolic binding (opt-in exhaustiveness; see below) |
| `clobbers` | S-check | `callerSaved` \| `<reg>`... | call-site clobber set (default `callerSaved`, narrowable for a known callee) |
| `liveIn` | S-check | `<reg>:<value>` | value live entering this instruction |
| `liveOut` | S-check | `<reg>:<value>` | value live leaving this instruction |
| `liveAcross` | S-check | `call` \| `<block>` | value(s) that must survive this boundary |
| `clobberRisk` | S-check | `<reg>:<value>` | a live value sitting in a register a call/op may clobber |
| `kills` | S-check | `<reg>` | last use of whatever was in `<reg>` |
| `saves` | S-check | `<reg> <stackSlot>` | spills a register to a slot (prologue) |
| `restores` | S-check | `<reg> <stackSlot>` | reloads a register from a slot (epilogue) |
| `fallthrough` | S-check | `<block>` | the not-taken successor of a branch (the implicit path) |
| `arg` | S-check | `<role> <reg>` | a syscall/call argument binding — `arg fd a0` |
| `masked` | S | `<vreg>` | vector mask register (RVV) |
| `rounding` | S | `<mode>` | FP rounding mode |
| `ordering` | S→A | `relaxed`\|`acquire`\|`release`\|`acqrel` | atomic ordering (A when it changes the `.aq`/`.rl` mnemonic) |
| `syscall` | S-check | `<name>` | the syscall this `EnvironmentCall` performs (keys `syscalls.tsv`) |
| `ordinal` | A | `<int>` | explicit order key (optional; see ordering below) |
| `emitKind` | A | `pseudo`\|`real` | only when not derivable from the op table |
| `condition` | S-intent | `"..."` | human-readable branch/predicate condition |
| `returns` | S-check | `<value>` | value handed back (on `Return`) |
| `purpose` | S-intent | `"..."` | |

**`writes <value>` on a `Call` binds the callee's result** — the ABI's first
return register (`a0`), not the link register the op table lists as the call's
def (DESIGN §11.2, the call-result rule). This is how "a0 now holds f's result"
becomes a checkable fact instead of a comment.

**`reads`/`writes`/`requires` take value names, never registers (DESIGN §11.2),
and are surfaced *selectively*.** A register-level use/def (`reads a1`) is
derivable from `op` + the register fields → S-derivable, rejected
(`E-DERIVABLE`). A *value* name asserts the register↔value binding at this point —
checkable by value-flow, and each value must resolve to a declared `value`
(`E-REF` otherwise). Surface the binding **only when the same logical value
crosses instructions, blocks, calls, stack slots, or memory** (inclusion rule
§0.5). Restating it on adjacent one-liners is dilution — `add2`'s `reads left` is
acceptable *only* because it is a tutorial example.

**`reads`/`writes` are partial by default — exhaustive only on opt-in.** Each
`reads`/`writes` fact is checked *individually* (the named value must satisfy the
binding), but an instruction is **not** required to annotate every symbolic value
it touches. This keeps authoring light: surface the bindings that matter, ignore
the rest. An instruction that wants the stronger guarantee declares
`valueBindings complete`, which asserts its `reads`/`writes` list *all* symbolic
bindings — then the validator also flags any *missing* one. Requiring exhaustive
bindings everywhere would make `.sasm` heavy fast, so it is opt-in.

**Call clobbers default to the ABI's caller-saved set.** A `Call`'s clobber and
argument registers are conservative by default (all caller-saved clobbered; args =
the ABI argument registers). For a *known* callee you may narrow them with
`arg <value> <reg>` and `clobbers <reg>...` at the call site; otherwise the
conservative model stands, which can make `W-CLOBBER` over-fire (acceptable for
v0). Call-site ABI facts are how you quiet it when the signature is known.
*Enforcement honesty:* today the analyses honor `arg` (backward liveness uses
declared args) but **not `clobbers`** — liveness and value-flow still model the
full caller-saved set. Until that lands (TODOS A3), treat `clobbers` as intent:
writing it will not change any diagnostic.

**Liveness / save-restore facts (`liveOut`, `liveAcross`, `clobberRisk`, `saves`,
`restores`)** are the highest-value surfaced state: they are exactly what agents
get wrong around calls, branches, and loops. They are S-check (verified against
the derived CFG liveness, DESIGN §13) and should appear **only at the boundaries
that matter** — across a `call`, a loop back-edge, or a spill/reload — never on
every instruction. The clobber set of a `call` is *derived from the ABI table*,
not written by hand; store only the checkable assertion that a specific live value
is preserved (`I9 clobberRisk a0:sum` / `preserved via SlotSavedSum`).

**Ordering — source order by default, `ordinal` when robustness matters.**
Within a block, execution order is the source order of `insn` rows; cross-block
order is always the CFG (`successor`/`target`/`fallthrough`), never position. For
agent-edit robustness, an `insn` may instead carry an explicit **`ordinal`** (use
gaps — 10, 20, 30 — so rows insert between without renumbering). When present,
`ordinal` is **authoritative** for order and the formatter (`sasm fmt`) sorts file
layout by it; absent, source order applies. Either way `π` is deterministic, so an
accidental reorder surfaces as a `.s` diff. There is no `next`/`seq` chain — an
ordinal key inserts more cleanly than a linked list.

---

## 4. `value` — value semantics (NEW, all S)

Promotes "what does this register *mean*" into named, typed entities. Values are
pure context — they never lower. `insn reads/writes` and `function in/out` refer
to them by name.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is value` | — | | |
| `in` | S-check | `<function>` | scope |
| `type` | S-check | `<Type>` | e.g. `Int64`, `Int64Pointer`, `Boolean` |
| `signed` | S-check | `yes`\|`no` | signedness |
| `bits` | S-check | `<n>` | meaningful bit-width |
| `unit` | S-check | `bytes`\|`elements`\|`<enum>` | domain/units |
| `definedBy` | S-check | `<insn>` | where this value is produced |
| `storedIn` | S-check | `<stackSlot>` | the slot it is spilled to (when it crosses a call) |
| `restoredBy` | S-check | `<insn>` | where it is reloaded |
| `meaning` | S-intent | `"..."` | |

**Width & signedness live on the `value`, not the instruction.** `lw` vs `lwu`,
`add` vs `addw`, sign- vs zero-extension are all **derivable from `op`** (the op
table encodes the access width and extension), so a per-`insn` `loadWidth`/`extends`
fact is S-derivable and rejected. The *non*-derivable part — that the value is a
32-bit unsigned count vs a 64-bit pointer — belongs to the value's `type`/`bits`/
`signed`. The validator cross-checks: an op's table width must be consistent with
the `type` of the value it reads/writes (`E-TYPE`).

**Provenance (`definedBy`/`storedIn`/`restoredBy`) is surfaced selectively** —
only when a value crosses a call, block, or spill (inclusion rule §0.5). It is
noise on an adjacent producer→consumer pair.

---

## 5. `stackSlot` — named frame location

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is stackSlot` | — | | |
| `in` | A | `<function>` | membership |
| `offset` | A | `<int>` | offset from `sp` (resolves `insn offset`) |
| `type` | S | `<Type>` | stored type |
| `role` | S | `savedRegister`\|`spill`\|`local`\|`outgoingArg` | slot purpose |
| `stores` | S | `<reg>`\|`<value>` | what lives here |
| `size` | S | `<n>` | slot size in bytes |

---

## 6. `data` — static data

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is data` | — | | |
| `section` | A | `rodata`\|`data`\|`bss` | placement |
| `type` | A | `Bytes`\|`Int64`\|`Int32`\|... | encoding |
| `value` | A | `"..."`\|`<int>` | initializer |
| `size` | A | `<n>` | byte size (emits `.size` / reserves bss) |
| `align` | A | `<n>` | alignment (`.align`) |
| `binding` | A | `global`\|`local`\|`weak` | symbol binding |
| `purpose` | S-intent | `"..."` | |

**The data contract (`E-DATA`, ◌ A3).** `section bss` requires `size` and
forbids `value` (uninitialized memory is reserved with `.zero <size>`; today a
sizeless bss entity silently emits `.zero None`). `section data`/`rodata`
require `value`. For `type Bytes` the declared `size` must equal the literal's
byte length — the emitter trusts `size` for the `.size` directive and does not
recount. An unknown `type` is an error (today it silently falls back to
`.dword`). `Float32`/`Float64` initializers are **not supported in v0** — there
is no float directive mapping; declare the bits as `Nat32`/`Nat64` if needed.

---

## 7. `symbol` — external / linker references (NEW)

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is symbol` | — | | |
| `external` | A | `yes` | defined elsewhere (undefined here) |
| `binding` | A | `global`\|`local`\|`weak` | |
| `symbolType` | A | `func`\|`object` | ELF symbol type |
| `reloc` | A | `pcrelHiLo`\|`got`\|`call`\|`absolute` | relocation strategy |
| `linkerDefined` | S | `yes` | provided by the linker (e.g. `__global_pointer$`) |
| `purpose` | S | `"..."` | |

---

## 8. `memoryRegion` — distinguish what memory means (NEW)

Instructions point at a region with `memory region <name>`. Regions make
aliasing, volatility, and the stack-is-internal rule explicit.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is memoryRegion` | — | | |
| `kind` | S | `stack`\|`heap`\|`global`\|`readonly`\|`device` | nature of the region |
| `aliases` | S | `<region>`\|`none` | may-alias relationship |
| `volatile` | S | `yes`\|`no` | side-effecting access |
| `purpose` | S | `"..."` | |

---

## 9. `vectorConfig` / dynamic state — RVV frontier (NEW, Tier V)

Vector behavior depends on `vtype`/`vl` set by a prior `vsetvli`. We make that
state a named entity and link each vector instruction to the config in force.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is vectorConfig` | — | | |
| `sew` | S | `<bits>` | element width (8/16/32/64) |
| `lmul` | S | `<frac>` | register grouping (`m1`,`m2`,`mf2`,...) |
| `tailPolicy` | S | `agnostic`\|`undisturbed` | |
| `maskPolicy` | S | `agnostic`\|`undisturbed` | |
| `vl` | S | `<reg>`\|`<value>` | active length |

An `insn vtype <vectorConfig>` fact (S) names which config governs it; the
`vsetvli`-class op establishes it. Full validation is Tier V — designed, deferred.

---

## 10. Closed vocabularies

### Effects (full words — no `mem`/`fp` abbreviations)
```
none  memory.read  memory.write  stack.allocate  stack.free
call  syscall  syscall.<name>  trap  fence  float.flags  csr.read  csr.write
device.read  device.write
```
Coarse forms (`memory.read`, `syscall`) and refined forms (`memory.write` with a
`region`, `syscall.write`) are both legal; the refined form just carries more for
the validator. Keep them **machine-facing** — do not borrow Layer-1 / SemanticScript
effects like `write console.stdout` here; a syscall is `syscall.write`, optionally
plus a `memory`/`device` region.

**Internal-effect rule:** an effect whose access targets `memory region <r>` with
`kind stack` is *internal* and excluded from a function's observable `effect`
summary. (This is why `fib` declares `effect call` but not `memory.write`, despite
its prologue stores.)

### Control kinds (insn `control`, from `optable.tsv`)
```
seq  branch  jump  call  return  syscall
```

### Core types
```
Int8 Int16 Int32 Int64  (signed)
Nat8 Nat16 Nat32 Nat64  (unsigned)
Float32 Float64
Boolean  Address  Bytes
<T>Pointer   e.g. Int64Pointer
```

---

## 10.5 Enforcement status — the honesty table (governing)

The §2.1 invariant is *no fact silently believed*. That cuts both ways: a
**predicate whose check is not yet implemented must not masquerade as checked.**
This table is the contract; the rule for readers and agents is:

> **Until a predicate's check lands, treat its facts as S-intent — context, not
> ground truth — no matter what tier the schema assigns it.**

**Checked today** (writing a wrong fact produces a diagnostic):

| facts | guarded by |
|-------|-----------|
| `operation`, operand fields, required fields | `E-ISA-OPCODE` `E-ISA-FIELD` `E-ISA-REG` |
| `in`/`target`/`offset` references; `reads`/`writes`/`returns`/`requires` value resolution | `E-REF` |
| register names in `reads`/`writes`/`returns`/`requires` | `E-DERIVABLE` |
| `reads`/`writes`/`returns`/`requires` bindings | `E-VALUE-FLOW` (may-form, DESIGN §11) |
| function `effect` (with the internal-effect rule), `leaf` | `E-EFFECT` `E-LEAF` |
| `stack bytes` 16-alignment; slot offset vs frame | `E-ABI-ALIGN` `W-SLOT` (start-only) |
| callee-saved reuse vs `saves`/`restores`/`preserves` (set-wise) | `E-ABI-PRESERVE` |
| use-before-def, return definedness, `liveOut` | `E-LIVE-UNDEF` `E-LIVE-RET` `E-LIVE-ASSERT` |
| clobber/dead warnings | `W-CLOBBER` `W-DEAD` |
| branch target ∈ declared successors; reachability | `E-CFG-EDGE` (target side) `W-UNREACHABLE` |
| fall-through adjacency; rows after a terminator; running off the last block; targeted entry block | `E-CFG-LAYOUT` |
| `terminates` vs the block's actual terminator (incl. noreturn syscalls) | `E-CFG-EDGE` |
| `writes <value>` on a `Call` binds the ABI return register (the call-result rule, DESIGN §11.2) | `E-VALUE-FLOW` |
| `writes` width vs op width | `E-TYPE` |
| decimal `immediate` ranges (incl. `shamt6`) | `E-IMM-RANGE` |
| ordinal mixing within a block | `E-ORDER-MIXED` |

**Specified, not yet checked** (◌ — treat as intent until TODOS A3/A1 lands):

| facts | intended guard |
|-------|----------------|
| successor exactness (stale edges); `predecessor` inverse | `E-CFG-EDGE` |
| duplicate single-valued facts; re-`is`; label/symbol collisions | `E-DUP` |
| `ordinal` integer-ness / duplicates | `E-ORDER-KEY` |
| the data contract (§6) | `E-DATA` |
| extension gating vs `program target` | `E-EXT-UNAVAILABLE` |
| `clobbers` narrowing at call sites (analyses still assume full caller-saved) | liveness/value-flow |
| `liveIn`, `liveAcross`, `clobberRisk`, `kills`, `valueBindings complete` | liveness/value-flow extensions |
| `saves`/`restores` slot *pairing* and per-return-path completeness | `E-ABI-PRESERVE` refinement |
| `stack bytes` vs the actual prologue `addi sp, sp, -N` | `E-ABI-ALIGN` refinement |
| `syscall <name>` vs `syscalls.tsv` (number in `a7`, args live) | `E-EFFECT`/liveness |
| `memory region`/`type`/`align`/`volatile` resolution (region names are unvalidated; only `kind stack` feeds the internal-effect rule) | `E-REF`/`E-TYPE` |
| effect *region qualifiers* (`effect memory.write <region>`) | `E-REF` |
| value `in`-scope, `definedBy`/`storedIn`/`restoredBy`, `signed`/`unit` consistency | value-flow extensions |
| whole constructs: `parameter` (§13), indirect control flow (§14), atomics pairing (§15), CSR (§18), FP (§19), `vectorConfig` (§9) | Tier B/V/P validators |
| the general derivable-fact linter | `E-DERIVABLE` (TODOS A1) |

The "Everything else in S must be checkable" rule in the intro means checkable
**in principle and in the design**; this table is where *in practice* is tracked.
A predicate may not stay in the ◌ rows indefinitely — each must either gain its
check or be demoted to S-intent / removed (that is a standing design debt, owned
by TODOS A3).

**Runtime clause (DESIGN §18):** a runtime contract check (`R-*`) is
trace-scoped — it proves a fact held on one executed path under one input, and
**never changes a fact's status in this table**. A ◌ fact stays intent after any
number of clean runs; only a landed static check moves a row.

---

## 11. How the vocabulary covers `TODOS.md`

| TODO category | made explicit by |
|---------------|------------------|
| 1 Register roles | `regs.tsv` (role/saver) + `function preserves`/`framePointer` |
| 2 Calling convention | `abi.tsv` + `function in/out/variadic`, `stackSlot role outgoingArg` |
| 3 Implicit reads/writes | `optable.tsv` defs/uses + ABI overrides (`Call`, `EnvironmentCall`) |
| 4 Control flow | `block successor/predecessor/loop/backEdgeTo`, `insn target` |
| 5 Memory | `memoryRegion` + `insn memory region/type/align/volatile` |
| 6 Stack frame | `stackSlot` (offset/role/stores) + `function stack`/`framePointer`/`unwind` |
| 7 Immediates | `optable.tsv` format + range validators (E-IMM-RANGE) |
| 8 Pseudos | semantic ops in `optable.tsv`; expansion is `π`'s job |
| 9 ISA context | `program target/xlen/compressed/pic` + per-op `tier`/`ext` |
| 10 Vector | `vectorConfig` + `insn vtype/masked` |
| 11 Floating point | `insn rounding` + `effect float.flags` |
| 12 Atomics | `insn ordering`; LR/SC pairing validator |
| 13 CSR/privilege/trap | `effect csr.*`, `function privilege`, `effect trap` |
| 14 Symbols/linker | `symbol` entity + `data binding/align` |
| 15 Value semantics | `value` entity (type/signed/bits/unit) |

Anything still implicit after this is either a *validator* to write (turn a fact
into a check) or the Tier V/P dynamic-state frontier.

---

## 12. Minimal example using the refined vocabulary

```
prog is program
prog target rva23u64
prog xlen 64
prog abi linux.riscv64

heapData is memoryRegion
heapData kind heap

n is value
n type Nat64
n signed no
n meaning "number of elements to sum"

sum is value
sum type Int64
sum meaning "running total"

# ... function/block/insn facts reference n, sum, heapData by name ...
```

Every name above is context (S). Strip it all and the emitted `.s` is unchanged —
the invariant that keeps the language honest.

---

# Refined constructs (completing the implicit-state coverage)

These sections add explicit vocabulary for the items that previously had none.

## 13. `parameter` — non-trivial argument passing (NEW)

Simple scalar args stay inline on the function (`in <value> <Type> <reg>`). When
an argument is an aggregate, passed on the stack, split across registers, or
passed by hidden reference, use a `parameter` entity so the *location* is
explicit instead of assumed by the psABI.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `is parameter` | — | | |
| `in` | S | `<function>` | owning function |
| `index` | S | `<n>` | source argument position (0-based) |
| `value` | S | `<value>` | the value it carries |
| `type` | S | `<Type>` | |
| `class` | S | `integer`\|`float`\|`aggregate`\|`reference` | psABI classification |
| `location` | A+S | `register <reg>` / `registers <reg>...` / `stackSlot <slot>` / `split <reg> <slot>` | where it actually arrives — the **register/slot is A** |
| `returnsVia` | S | `register`\|`hiddenPointer` | for results: large aggregates returned via a hidden pointer in `a0` |

Stack-passed args (the 9th integer arg onward) use `location stackSlot <slot>`
with a `stackSlot role outgoingArg` on the caller side.

## 14. Indirect control flow (NEW)

Direct branches/jumps use `insn target <block>`. Indirect transfers (`jalr`
through a register, jump tables) name the *possible* destinations so the CFG is
not a dead end.

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `targets` | S | `<block>`... | the set of blocks an indirect jump may reach |
| `via` | S | `<reg>` | the register holding the computed destination |
| `dispatch` | S | `<data>` | the jump table this indirect jump reads from |

## 15. Atomics & ordering (NEW)

Atomic ops live in `optable.tsv` (class `atomic`: `LoadReserved`,
`StoreConditional`, `AtomicSwap`, `AtomicAdd`, …, `AtomicCompareAndSwap`). Their
address register is `base`, the value is `secondSource`, the result is
`destination` — same field shape as loads/stores. The memory-ordering bits,
invisible in a bare mnemonic,
become facts:

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `ordering` | S→A | `relaxed`\|`acquire`\|`release`\|`acqrel` | maps to the `.aq`/`.rl` suffix at emit (A: changes the mnemonic) |
| `reservation` | S | `set`\|`check` | LR sets a reservation, SC checks it |
| `pairsWith` | S | `<insn>` | links an `LoadReserved` to its `StoreConditional` |

Emit note: `ordering acquire` → `lr.d.aq`, `release` → `sc.d.rl`,
`acqrel` → `.aqrl`. Because it changes the emitted mnemonic, `ordering` is
authoritative when present (it just defaults to `relaxed`).

## 16. Encoding formats & immediate ranges

Each op's `fmt` (from `optable.tsv`) keys into `formats.tsv`, which gives the
immediate's bit-width, signedness, legal range, and instruction alignment. This
makes the implicit "assembler will reject out-of-range immediates" rule a
checkable fact (validator code `E-IMM-RANGE`).

- I/S type: signed 12-bit, −2048..2047
- B type: signed 13-bit, 2-byte aligned, ±4 KiB
- U type: unsigned 20-bit (value is `imm << 12`)
- J type: signed 21-bit, 2-byte aligned, ±1 MiB
- **shift-immediate** ops (`ShiftLeftLogicalImmediate`, …) use the `shamt6`
  range (0..63 on RV64), *not* the I-type range — an override the validator
  applies by op class `shift` + immediate operand.

## 17. Extensions & target gating

`extmap.tsv` maps each op `class` to the RISC-V extension it requires
(`muldiv`→`M`, `cond`→`Zicond`, `atomic`→`A`, everything else→`I`). Combined with
`program target <profile>`, this makes "which extensions are assumed" explicit and
checkable: an op whose extension isn't in the target profile is an error
(`E-EXT-UNAVAILABLE`). `program xlen 64` gates the `*Word` and `LoadDoubleword`
family. When the generator adds Tier B/V/P (DESIGN §7.2), extension becomes a
per-op column instead of a class mapping.

## 18. Syscalls & CSRs

- **`syscalls.tsv`** — name → number, argument registers, return register, kind.
  An `insn op EnvironmentCall` with `syscall write` is checked against the table:
  the syscall number must be in `a7`, and `a0..a2` must be live-in. Makes the
  entirely-conventional syscall contract (§TODO 3/5) explicit.
- **`csr.tsv`** — name → number, access (`readOnly`/`readWrite`), side effect.
  Used when CSR ops land (Tier P): a CSR read with `sideEffect float.flags` or
  `readClears` is flagged so the hidden state change is visible.

CSR access facts on an instruction:

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `csr` | A | `<name>` | the CSR operand |
| `csrAccess` | S | `read`\|`write`\|`readWrite` | derived/checked against `csr.tsv` |

## 19. Floating-point detail

| predicate | tier | args | meaning |
|-----------|------|------|---------|
| `rounding` | S | `nearestEven`\|`towardZero`\|`down`\|`up`\|`nearestMaxMagnitude`\|`dynamic` | rounding mode (`dynamic` reads `frm`) |
| (effect) | S | `effect float.flags` | the op updates accrued `fflags` |
| `nanBoxed` | S | `yes` | a narrow float stored NaN-boxed in a wide f-register |

A `value` of FP type may carry `nanBoxed yes` to record the boxing convention
explicitly instead of leaving it implicit in the register width.

## 20. Compact multi-fact sugar (S-tier ergonomics)

Verbosity is the point, but deeply-annotated `insn` blocks get tall. An optional
pipe form lets several predicates for one subject share a line; it parses to the
*identical* rows (so it is pure surface sugar, never a semantic change):

```
# these two are equivalent
loadElement operation LoadDoubleword | destination t4 | base t3 | offset 0 | effect memory.read | memory region inputArray

loadElement operation LoadDoubleword
loadElement destination t4
loadElement base t3
loadElement offset 0
loadElement effect memory.read
loadElement memory region inputArray
```

Rule: the first clause is `<subject> <predicate> <args>`; each subsequent
`| <predicate> <args>` reuses the same subject. Quoted strings work as elsewhere.
Because it expands to the same fact rows, lowering and validation are unaffected.

---

## 21. Coverage after refinement

With §13–§20, the language has an explicit construct for every category in
`TODOS.md` except the genuinely dynamic Tier V/P semantics (full `vtype`/`vl`
dataflow, interrupt state), which are *named* but not yet *reasoned about*. What
remains is no longer "make it expressible" — it is "write the validator that
turns each fact into a check" (DESIGN §14) and build the runtime (`isa.py`,
`emit.py`). Expressiveness is essentially complete; enforcement is not.
