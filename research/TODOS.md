# TODOs — making RISC-V's implicit state explicit

The goal of semantic assembly is to promote every hidden assumption in RISC-V into
an explicit, checkable fact. This file is the backlog of *implicit things* and the
language work to make each one explicit. It is an exploration map, not a
committed schedule — items will split, merge, and spawn design questions.

**Two different goals, tracked honestly:**
- **Expressible** — is there a fact/table to *state* the thing? (the language work)
- **Enforced** — does a validator *check* it? (the runtime work)

Status reflects **expressibility**: `[x]` a construct/table exists · `[~]`
partial or design-only · `[ ]` no construct yet.

> ⚠️ **Expressibility ≠ enforcement.** As of now *nothing is enforced* — there is
> no running `isa.py`/`validate.py`/`emit.py`. Every `[x]` below means "you can
> write the fact," not "a tool checks it." All enforcement is pending and tracked
> in the **Cross-cutting** section, which is almost entirely `[ ]`.

Vocabulary lives in `LANGUAGE.md`; ops in `OPCODES.md`/`optable.tsv`; data in
`regs.tsv`, `abi.tsv`, `formats.tsv`, `extmap.tsv`, `syscalls.tsv`, `csr.tsv`.
Guiding principle (DESIGN §2.1): verbosity is free — when in doubt, make it a
fact. Authoritative facts must still lower away cleanly (§11 invariant).

---

## 1. Register roles & ABI identity
- [x] `x0`/`zero` hardwired to 0 — special-cased in def/use
- [x] `ra` is the link register — `stores ra`, `preserves ra`
- [x] `sp` is the stack pointer, 16-byte aligned at calls — `stack align`, `effect stack.allocate`
- [x] `gp`/`tp` must not be clobbered — `abi.tsv reserved gp tp`
- [x] `fp`/`s0` frame-pointer dual role — `function framePointer s0`
- [x] ABI name ↔ numeric mapping (`a0`==`x10`) — `regs.tsv` number column
- [x] which registers a function clobbers — derivable from def-set
- [x] register liveness/ownership at each point — forward (`E-LIVE-UNDEF`/`E-LIVE-RET`) + backward (`W-DEAD`/`W-CLOBBER`) fixpoints LIVE (DESIGN §13)
- [x] explicit per-register "contains <value>" at boundaries — `insn reads/writes <value>` *is* this fact (value names only, §11.2); validator checks the register↔value binding by value-flow

## 2. Calling convention (psABI)
- [x] integer arg/return registers — `in` / `out`
- [x] FP args in `fa0–fa7` — `regs.tsv` fp regs, `abi.tsv argFloat/returnFloat`, `parameter class float`
- [x] struct-by-value: split across regs/stack, by-reference — `parameter class aggregate` + `location split`
- [x] variadic arguments — `function variadic yes`
- [x] stack-passed args (9th+) — `parameter location stackSlot` + `stackSlot role outgoingArg`
- [x] no-red-zone assumption — `abi.tsv redZone 0`
- [x] stack grows down / callee restores sp — `abi.tsv stackGrows down`

## 3. Per-instruction implicit reads/writes
- [x] `call` writes `ra` — table `defs`
- [x] `ret` reads `ra` — table `uses`
- [x] `ecall` reads `a7`+args, writes `a0` — `syscall` fact + `syscalls.tsv`
- [x] signed/unsigned distinction — separate semantic ops
- [x] branches/`auipc` read PC — *resolved as a table property, not a per-insn fact* (§11.2): a PC read is derivable from `op`, so writing it would be S-derivable; the op table carries it
- [~] full caller-saved clobber set on `call` — data exists (`abi.tsv callerSaved`); def-set expansion is validator logic
- [x] syscall arg/return register sets per syscall — `syscalls.tsv`

## 4. Control flow
- [x] fallthrough successor — `terminates fallthrough` + `successor`
- [x] not-taken branch path — `successor`
- [x] block / loop-header / function boundaries — entity types
- [x] call vs branch vs data label — entity type + `control` kind
- [x] tail-call vs call intent — `TailCall` vs `Call`
- [x] indirect jumps / jump tables (`jalr`) — `insn targets/via/dispatch` (LANGUAGE §14)
- [~] loop metadata — `block loop`/`backEdgeTo` exist; trip count not modeled
- [ ] unreachable-block detection — a validator pass, not a fact

## 5. Memory
- [x] memory region (stack/heap/global/readonly/device) — `memoryRegion` + `memory region`
- [x] read vs write effect — `effect mem.read|mem.write`
- [~] RVWMO ordering between accesses — `ordering` + `Fence`; explicit fence pred/succ sets partial
- [x] pointer aliasing / non-overlap — `memoryRegion aliases`
- [x] access alignment — `memory align <bytes>`
- [x] endianness — `program endian little`
- [x] volatile / device memory — `memory volatile yes` / region `kind device`
- [x] data type/width at the access — `memory type`

## 6. Stack frame
- [x] frame layout — `stackSlot` entities (named offsets)
- [x] frame size — `stack bytes`
- [x] frame-pointer present or not — `function framePointer`
- [x] slot purpose (spill / saved-reg / local / outgoing-arg) — `stackSlot role`
- [x] prologue/epilogue pairing — block roles + `stack.allocate`/`stack.free`
- [x] CFI / unwind info — `function unwind` (emit `.cfi_*` is downstream)
- [x] validate: callee-saved regs reused without save+restore+declare — `E-ABI-PRESERVE` (LIVE)

## 7. Immediates & encoding constraints
- [x] immediate ranges per format — `formats.tsv` (I/S/B/U/J)
- [x] shift-amount 0–63 bound — `formats.tsv shamt6`
- [x] immediate sign-extension semantics — `formats.tsv signed` + op `meaning`
- [ ] `li` expansion length (1–8 insns) by constant — left to assembler (decision); not recorded
- [x] address materialization strategy — `symbol reloc <kind>`

## 8. Pseudo-instruction expansion
- [x] pseudos as first-class semantic ops — `Move`, `LoadImmediate`, `Return`, …
- [~] `call` = 1 or 2 real instructions by range — deferred to assembler (documented decision)
- [ ] optional: record canonical expansion as child facts — `expandsTo` fact (visibility toggle)

## 9. ISA / extension context
- [x] which extensions are assumed — `extmap.tsv` + `program target`
- [x] XLEN (32 vs 64) — `program xlen`
- [x] compressed encodings in use — `program compressed`
- [~] per-instruction extension requirement — class→ext mapping done; per-op column deferred to generator

## 10. Vector (RVV) — dynamic state frontier
- [~] `vtype` (SEW / LMUL / tail / mask policy) — `vectorConfig` entity (scaffold); dataflow deferred
- [~] `vl` active length — `vectorConfig vl` (scaffold)
- [~] `v0` implicit mask register — `insn masked v0` (expressible; not reasoned about)
- [ ] LMUL register grouping (v2 part of a group) — `group <regs>` fact not added
- [ ] validate vector op against current `vtype`/`vl` — Tier V validator (big)

## 11. Floating-point dynamic state
- [x] `fcsr` rounding mode (`frm`) — `insn rounding <mode>` (LANGUAGE §19)
- [x] `fflags` exception-flag side effects — `effect fp.flags`
- [x] NaN-boxing of narrow floats in wide f-regs — `value nanBoxed yes`

## 12. Atomics & ordering
- [x] `aq`/`rl` acquire/release bits — `insn ordering` + atomic ops in `optable.tsv`
- [x] LR/SC reservation & pairing — `reservation`/`pairsWith` + `LoadReserved`/`StoreConditional`
- [~] fence pred/succ ordering sets — `ordering` exists; explicit `fence predecessor/successor` partial

## 13. CSRs / privilege / traps
- [x] CSR access side effects — `csr.tsv` + `insn csr/csrAccess`
- [x] privilege level (M/S/U) context — `function privilege`
- [~] which instructions can trap, and the trap target — `effect trap` exists; `traps to` not added
- [x] `ecall` meaning by privilege/ABI — `abi.tsv` has the `.syscall` variant
- [ ] interrupt-enable state assumptions — out of scope until needed

## 14. Symbols / linker
- [x] symbol binding/visibility/type — `symbol binding/symbolType` + `function/data binding`
- [x] section placement — `data section`
- [x] relocations — `symbol reloc <kind>`
- [x] GOT/PLT for PIC — `program pic` + `symbol reloc got`
- [x] alignment / size directives — `data align` / `data size`
- [x] linker-defined symbols — `symbol external linkerDefined`

## 15. Value semantics (most fundamental)
- [x] what a register *means* (pointer/int/bool) — `value` entity + `reads/writes`
- [~] promote values to first-class SSA-ish entities — `value` exists; per-point register binding (SSA) deeper
- [x] signedness of a value — `value signed`
- [x] meaningful bit-width — `value bits`
- [x] units / domain — `value unit`

---

## Cross-cutting language / tooling work
- [x] Register table representation — `regs.tsv` (name/number/class/role/saver)
- [x] ABI table as data — `abi.tsv` (arg/ret/caller/callee/reserved/align/grows/redZone)
- [x] Effect taxonomy + internal-effect rule — LANGUAGE §10
- [x] Instruction-ordering decision — *source order canonical, optional `ordinal` key* (DESIGN §11.1); no `next`/`seq` chain; all-or-nothing per block (`E-ORDER-MIXED`); cross-block order is the CFG
- [~] Compact multi-fact-per-line sugar — designed (LANGUAGE §20); parser support not built
- [ ] **`sasm fmt`** — canonical formatter: idempotent, order-preserving, one deterministic layout (protects positional intra-block order, §11.1)
- [ ] `facts <entity>` query command — agent-facing introspection
- [ ] Generator from `riscv/riscv-opcodes` → Tier B/V/P table rows (§7.2)
- [x] **`isa.py`** — loads optable/regs TSVs (extend to abi/formats/etc. for the validator)
- [x] **`emit.py`** — the projection `π`; **byte-identical** on all three examples (DESIGN §15.1); CLI `sasm emit|build|facts`
- [x] **`validate.py`** — **entire §14 catalog wired (19 codes)**: `E-ISA-OPCODE/REG/FIELD`, `E-REF`, `E-ABI-ALIGN`, `E-ABI-PRESERVE`, `E-LEAF`, `E-EFFECT` (internal-effect rule), `E-CFG-EDGE`, `E-ORDER-MIXED`, `E-IMM-RANGE`, `E-TYPE`, `W-SLOT`, forward liveness `E-LIVE-UNDEF`/`E-LIVE-RET`, backward liveness `W-DEAD`/`W-CLOBBER`, value-flow `E-VALUE-FLOW` (may-analysis over named values — handles fib's phi merge, catches the naive value-clobber), `E-DERIVABLE` (register-restatement case). CLI `sasm check`; `build` refuses on errors; all examples clean, every code's mutation caught. Remaining: full reachability `E-DERIVABLE` (beyond register-restatement) is still research-grade; `E-PARSE-*` lives in the parser.
- [ ] Diagnostics carry **stable code + entity handle + fix site** (DESIGN §5.1/§14), not line numbers
- [ ] **Value-flow pass** (`E-VALUE-FLOW`) — reaching-definitions over named values; verifies `reads/writes <value>` bindings (§11.2). **Shares §13's CFG + fixpoint** — it is a real dataflow analysis, not a row comparison.
- [ ] **⚠ HIGH PRIORITY — Derivable-fact linter** (`E-DERIVABLE`) — flag any S-fact reconstructable from A-facts + tables (§11 clause 2). **Load-bearing for the central claim**, not a nicety: until it ships, the "no attention dilution" guarantee is enforced only by author discipline. Note it is a *reachability* analysis (shares §13/value-flow machinery), not syntactic — so non-trivial. Prioritize above its category.
- [ ] **`in`/`value` Type check** (`E-TYPE`) — no unchecked type assertions (§11); cross-check op-width vs value `type`
- [ ] `E-ORDER-MIXED` — reject blocks mixing ordinaled and bare insns (§11.1)
- [x] Round-trip test on the three examples — `tests/snapshot.sh` (byte-match) + `testing/` (assemble + run under qemu); all green

> The §13 CFG/fixpoint is shared by **four** consumers: liveness, value-flow
> (§11.2), the derivable-fact linter, and return-definedness. Build it once, well.

## Validating the premise (DESIGN §16.1)
- [ ] **Edit-accuracy benchmark** — fixed mutation set (resize frame, swap operand, add spill, reorder blocks) applied across **three arms** to defuse the information-leak confound: (a) raw `.s`, (c) raw `.s` + a prose comment block of the same liveness/ABI facts, (b) `.sasm`. Metric: first-try correct-and-assembles rate. Discriminating prediction **b > c > a** — b-over-c isolates *locality+addressability* from mere information; if b ≈ c the format is overbuilt. This earns or sinks the attention-conditioning headline.

## Open design questions to explore (from DESIGN §17)
- [ ] Symbolic values vs registers — do values become first-class SSA names?
- [ ] Multi-valued returns / structs beyond a0/a1
- [ ] Pseudo expansion visibility (record vs defer)
- [ ] Interprocedural effect/clobber summaries for `call`
- [ ] How much of the ABI/register/CSR data is pure tables vs code
