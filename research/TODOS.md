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

> **Status (current):** the toolchain runs. `parser.py` + `isa.py` + `emit.py`
> (the projection π) + `validate.py` (the full §14 catalog, 19 codes) + `cli.py`
> are implemented and tested; 5 examples emit byte-identical `.s` and execute
> correctly under qemu. What remains is breadth (the rest of RVA23), one hard
> check (general `E-DERIVABLE`), some convenience features, and the empirical
> study. Those are enumerated in **"Not yet implemented"** immediately below.

Vocabulary lives in `LANGUAGE.md`; ops in `OPCODES.md`/`optable.tsv`; data in
`regs.tsv`, `abi.tsv`, `formats.tsv`, `extmap.tsv`, `syscalls.tsv`, `csr.tsv`.
Guiding principle (DESIGN §2.1): verbosity is free — when in doubt, make it a
fact. Authoritative facts must still lower away cleanly (§11 invariant).

---

# Not yet implemented — detailed backlog

Everything outstanding, grouped, with: **what**, **why**, **where** (file/section),
and **done-when** (acceptance). Difficulty: 🟢 small · 🟡 medium · 🔴 large/research.

## A. Validator — the one unfinished check

### A1. General `E-DERIVABLE` reachability linter 🔴 ⚠ load-bearing
- **What:** flag *any* S-fact reconstructable from A-facts + the tables — not just
  the register-name case in `reads`/`writes` (which is done). Examples to catch:
  an `effect memory.read` that merely restates the op-table effect with no region;
  a `terminates`/`control` value the op table already implies; a `liveOut` equal to
  the computed liveness; a `purpose`-free assertion that adds nothing.
- **Why:** DESIGN §11 clause 2 ("no dead weight / no attention dilution") is the
  load-bearing guarantee of the whole thesis; today it is enforced only by author
  discipline. This is the single most important missing validator.
- **Where:** `sasm/validate.py`; DESIGN §11 (clause 2), §11.2.
- **Hard part:** it's a *reachability* question, not syntactic — "could a tool
  reproduce this fact from A-facts + op/abi/regs tables + the §13 dataflow?" Needs
  a derivation oracle per predicate, reusing the CFG/liveness/value-flow machinery.
- **Done-when:** a derivable fact in any example is flagged `E-DERIVABLE`; the 5
  golden examples stay clean; no false positives on intent (`purpose`/`meaning`).

### A2. Validator refinements 🟡
- [ ] **`requires <value> in <reg>`** is parsed/checked by value-flow (today only
  `reads`/`writes`/`returns` feed `E-VALUE-FLOW`). — `validate.py` `_check_value_flow`.
- [ ] **Value-level `W-CLOBBER`** — today's `W-CLOBBER` is register-level; the
  value-level clobber (a *named value* destroyed across a call) is caught only by
  `E-VALUE-FLOW`. Decide whether to merge/clarify the two. — DESIGN §13/§11.2.
- [ ] **Asserted `liveIn`/`liveOut` mismatch** — validate declared liveness facts
  against the computed fixpoint (today they're documentation, never checked). New
  code, e.g. `E-LIVE-ASSERT`. — `validate.py`, DESIGN §13 step 5.
- [ ] **Unreachable-block detection** — CFG nodes with no path from entry. New
  warning `W-UNREACHABLE`. — `validate.py`.
- [ ] **`E-CFG-EDGE` "not reachable" half** — currently only the
  declared-successor cross-check is wired; the reachability half is not.
- [ ] **Diagnostics fix-site** — handle + stable code are emitted; the *candidate
  fix site* ("nearest def is X") is only in some messages. Make it uniform. —
  DESIGN §5.1/§14.

## B. ISA breadth — beyond Tier A (the big one)

### B1. Generator from `riscv/riscv-opcodes` 🔴
- **What:** a `gen/` script that pulls the official machine-readable opcode repo
  and emits `optable.tsv` rows (sem name via the naming rules, mnemonic, fmt,
  defines/uses, emit template) for every RVA23 instruction.
- **Why:** hand-curating hundreds of ops is the wrong move; coverage should ride
  on data (DESIGN §7.2). Unlocks Tiers B/V/P at once.
- **Where:** new `gen/`; DESIGN §7.2; feeds `sasm/optable.tsv`.
- **Sub-tasks:**
  - [ ] vendor/parse `riscv-opcodes` (operand fields → emit template, encoding).
  - [ ] apply the PascalCase full-word naming rules (OPCODES.md conventions).
  - [ ] curated **overrides** layer for what encodings don't say: effects, control
    kind, ABI-implicit regs (`Call`/`ecall`), pseudo expansions, op width.
  - [ ] add a per-op `ext` column (replace the class→ext `extmap.tsv` heuristic)
    and an `op-width` column (replace the derived `_op_width` in `validate.py`).
  - [ ] checked-in generated table + a regen check in CI.

### B2. Tier B — scalar extensions (structural + def/use) 🟡 each
- [ ] **F / D** floating point — fp registers (`fa*`/`fs*`/`ft*` already in
  `regs.tsv`), `rounding` mode facts, `float.flags` effect, NaN-boxing notes.
- [ ] **C** compressed — encodings + `program compressed yes` gating.
- [ ] **B** bitmanip (Zba/Zbb/Zbs), **Zfa**, **Zcb**, **Zfhmin**, cache ops
  (Zicbom/p/z), **Zawrs**, hint ops.
- **Done-when:** each emits + round-trips; effects coarse; scalar-reg liveness
  works; fp regs tracked structurally (DESIGN §7.3 Tier B).

### B3. Tier V — RVV vector (dynamic state) 🔴
- **What:** model the `vtype`/`vl`/`LMUL`/`SEW` state set by `vsetvli` and carried
  by following vector instructions; the `v0` mask; LMUL register grouping.
- **Where:** LANGUAGE §9 (`vectorConfig` scaffold exists), DESIGN §7.3 Tier V.
- **Sub-tasks:** [ ] `vsetvli` as a state-setting op · [ ] `insn vtype <config>`
  carried/validated · [ ] `masked v0` · [ ] `group <regs>` for LMUL · [ ] a
  vector-aware validator pass. **Hardest area; defer until B lands.**

### B4. Tier P — privileged / CSR 🟡
- [ ] CSR ops + `csr.tsv` side-effects (read-clears etc.), `csr`/`csrAccess` facts.
- [ ] `function privilege`, `effect trap` + `traps to`, interrupt state (scope TBD).

## C. Compiler & format features

### C1. Compact pipe sugar 🟢
- **What:** `subj op X | rd a0 | base t3 | …` parses to identical one-fact-per-row.
- **Where:** `sasm/parser.py` (`tokenize`/`parse`); spec in LANGUAGE §20.
- **Done-when:** the LANGUAGE §20 equivalence holds (sugar and expanded forms
  produce the same `Program`); a test asserts it; emitter/validator unaffected.

### C2. `ordinal` ordering 🟢
- **What:** when a block's insns carry `ordinal`, sort emission by it (today source
  order only); enforce all-or-nothing per block.
- **Where:** `sasm/emit.py` (block insn ordering), `validate.py` already has
  `E-ORDER-MIXED`. DESIGN §11.1.
- **Done-when:** an ordinaled example emits in ordinal order, byte-stable.

### C3. `sasm fmt` — canonical formatter 🟡
- **What:** idempotent, order-preserving re-serializer (one deterministic layout,
  grouped by container, stable spacing). Protects positional intra-block order.
- **Where:** new `sasm/format.py` + CLI `sasm fmt`. DESIGN §11.1.
- **Done-when:** `fmt(fmt(x)) == fmt(x)`; never reorders rows; round-trips the 5
  examples with a stable diff.

### C4. Data-section completeness 🟡
- **What:** today only `.rodata` + `.ascii` (Bytes) is exercised. Add `.bss`/`.zero`
  reservation, `Int64`/`Int32` (`.dword`/`.word`) emission, `data align` (`.align`)
  and `data size` (`.size`) directives.
- **Where:** `sasm/emit.py` `_emit_data`; LANGUAGE §6. **Untested today.**
- **Done-when:** an example uses each and assembles/runs.

### C5. Symbols / linking 🟡
- [ ] `symbol` entity emission — `.globl`/`.weak`/`.type`, external refs.
- [ ] relocations (`%hi`/`%lo`/`%pcrel`/GOT) via `symbol reloc`; `program pic`.
- [ ] multiple translation units / linker scripts (out of scope for v0, note it).

## D. Validating the premise (the actual experiment) 🔴

### D1. Edit-accuracy benchmark — DESIGN §16.1
- **What:** measure agent edit-accuracy across three arms — (a) raw `.s`, (c) raw
  `.s` + prose fact comment, (b) `.sasm` — on a fixed mutation set.
- **Why:** this is what *earns or sinks* the attention-conditioning thesis; until
  it runs, the headline is a hypothesis.
- **Sub-tasks:**
  - [ ] mutation generator (resize frame, swap operand, add spill, reorder blocks).
  - [ ] a known-correct oracle per mutation (lower + assemble + run under qemu).
  - [ ] harness that prompts an agent on each arm and scores first-try
    correct-and-assembles.
  - [ ] report: prediction **b > c > a**; b≈c ⇒ format overbuilt (worth knowing).
- **Done-when:** a reproducible script produces the three-arm scores.

## E. Layer-1 lowering (SemanticScript → `.sasm`) 🔴

- **What:** the pass that turns arch-free source IR into `.sasm`: register
  allocation, stack-slot spilling, call lowering with caller-saved spills.
- **Why:** today Layer 2 is hand-written; this automates its input (DESIGN §16).
- **Done-when:** a small SemanticScript op lowers to validating, running `.sasm`.
- **Note:** deliberately last — prove the fact model + validator are useful first.

## F. Tooling / DX / CI 🟢

- [ ] **CI workflow** — run the `sasm-eval` image (snapshots + validator + qemu)
  on every push; fail on any diagnostic/snapshot drift.
- [ ] **Packaging** — `pyproject.toml` so `pip install -e .` gives a `sasm` entry
  point (today it's `python -m sasm`).
- [ ] **`LICENSE`** — pick one (MIT?) before publishing.
- [ ] **Repo URL** in the webpage hero/footer (`docs/index.html` placeholder).
- [ ] More example coverage for the untested paths above (pipe sugar, ordinal,
  data section, fp).

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
- [~] Compact multi-fact-per-line sugar — designed (LANGUAGE §20); parser support not built → **details: C1**
- [ ] **`sasm fmt`** — canonical formatter → **details: C3**
- [x] `facts <entity>` query command — agent-facing introspection (`sasm facts`)
- [ ] Generator from `riscv/riscv-opcodes` → Tier B/V/P table rows (§7.2) → **details: B1**
- [x] **`isa.py`** — loads optable/regs TSVs (extend to abi/formats/etc. for the validator)
- [x] **`emit.py`** — the projection `π`; **byte-identical** on all three examples (DESIGN §15.1); CLI `sasm emit|build|facts`
- [x] **`validate.py`** — **entire §14 catalog wired (19 codes)**: `E-ISA-OPCODE/REG/FIELD`, `E-REF`, `E-ABI-ALIGN`, `E-ABI-PRESERVE`, `E-LEAF`, `E-EFFECT` (internal-effect rule), `E-CFG-EDGE`, `E-ORDER-MIXED`, `E-IMM-RANGE`, `E-TYPE`, `W-SLOT`, forward liveness `E-LIVE-UNDEF`/`E-LIVE-RET`, backward liveness `W-DEAD`/`W-CLOBBER`, value-flow `E-VALUE-FLOW` (may-analysis over named values — handles fib's phi merge, catches the naive value-clobber), `E-DERIVABLE` (register-restatement case). CLI `sasm check`; `build` refuses on errors; all examples clean, every code's mutation caught. Remaining: full reachability `E-DERIVABLE` (beyond register-restatement) is still research-grade; `E-PARSE-*` lives in the parser.
- [~] Diagnostics carry **stable code + entity handle + fix site** (DESIGN §5.1/§14) — code+handle done; fix-site uniformity pending (see A2).
- [x] **Value-flow pass** (`E-VALUE-FLOW`) — may-analysis (reaching-defs over named values), handles fib's phi merge, catches the value-clobber.
- [~] **Derivable-fact linter** (`E-DERIVABLE`) — register-restatement case done; **general reachability linter pending (see A1, ⚠ load-bearing).**
- [x] **`in`/`value` Type check** (`E-TYPE`) — op-width vs value `type` (width derived from op).
- [x] `E-ORDER-MIXED` — rejects blocks mixing ordinaled and bare insns (§11.1).
- [x] Round-trip test on the three examples — `tests/snapshot.sh` (byte-match) + `testing/` (assemble + run under qemu); all green

> The §13 CFG/fixpoint is shared by **four** consumers: liveness, value-flow
> (§11.2), the derivable-fact linter, and return-definedness. Build it once, well.

## Validating the premise (DESIGN §16.1)
- [ ] **Edit-accuracy benchmark** (three arms: `.s`, `.s`+comment, `.sasm`; predict b > c > a) → **details: D1**

## Open design questions to explore (from DESIGN §17)
- [ ] Symbolic values vs registers — do values become first-class SSA names?
- [ ] Multi-valued returns / structs beyond a0/a1
- [ ] Pseudo expansion visibility (record vs defer)
- [ ] Interprocedural effect/clobber summaries for `call`
- [ ] How much of the ABI/register/CSR data is pure tables vs code
