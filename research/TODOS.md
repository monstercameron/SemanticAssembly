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
> (the projection π) + `validate.py` (the ENTIRE §14 catalog — 32 codes, no
> pending entries left) + `cli.py` are implemented and
> tested; **thirteen** examples (incl. the gauntlet set: ackermann / quicksort /
> revlist) emit byte-identical `.s` and execute correctly under qemu. What
> remains is breadth (the rest of RVA23), the general `E-DERIVABLE` oracle
> (the one open research item — its register and effect-restatement slices
> are live), the empirical study (D1), and the gated real-binary debug
> adapter (§18 / section G). Enumerated below.

Vocabulary lives in `LANGUAGE.md`; ops in `OPCODES.md`/`optable.tsv`; data in
`regs.tsv`, `abi.tsv`, `formats.tsv`, `extmap.tsv`, `syscalls.tsv`, `csr.tsv`.
Guiding principle (DESIGN §2.1): token cost is accepted — but every fact must be
consumed (A), a checkable contract (S-check), or marked intent (S-intent). **No
fact is silently believed.** Authoritative facts must still lower away cleanly
(§11 invariant).

---

# Not yet implemented — detailed backlog

Everything outstanding, grouped, with: **what**, **why**, **where** (file/section),
and **done-when** (acceptance). Difficulty: 🟢 small · 🟡 medium · 🔴 large/research.

## A. Validator — the one unfinished check

### A1. General `E-DERIVABLE` reachability linter 🔴 — scope BOUNDED (2026-06-10)
The trust reframe (DESIGN §2.1) collapsed most of A1's original targets:
S-check facts that restate *derived truth* are now pinned CONTRACTS (a
`liveOut` equal to computed liveness is a regression guard, by design — not
dilution). What remains banned is the **zero-information copy**: a fact whose
check is vacuous because it can never fail independently of the rows/tables it
copies. All *enumerable* copies are now checked: register-named
`reads`/`writes`, effect restatement (no qualifier, no memory facts), and
`emitKind` restatement. The still-open research part is the general oracle —
"could a tool re-derive this fact from A-facts + tables + dataflow, such that
no future edit can make it fail?" — needed only for copies we have NOT
enumerated. New predicates enter through the §10.5 gate (name your failure
mode or be intent), which prevents new unenumerated copies by construction.
- **What:** flag *any* S-fact reconstructable from A-facts + the tables — not just
  the register-name case in `reads`/`writes` (which is done). Examples to catch:
  an `effect memory.read` that merely restates the op-table effect with no region;
  a `terminates`/`control` value the op table already implies; a `liveOut` equal to
  the computed liveness; a `purpose`-free assertion that adds nothing.
- **Why:** DESIGN §11 clause 2 ("no unchecked copies — no fact silently
  believed") is the load-bearing guarantee of the whole thesis; today it is
  enforced only by author discipline. This is the single most important missing
  validator.
- **Where:** `sasm/validate.py`; DESIGN §11 (clause 2), §11.2.
- **Hard part:** it's a *reachability* question, not syntactic — "could a tool
  reproduce this fact from A-facts + op/abi/regs tables + the §13 dataflow?" Needs
  a derivation oracle per predicate, reusing the CFG/liveness/value-flow machinery.
- **Done-when:** a derivable fact in any example is flagged `E-DERIVABLE`; the 5
  golden examples stay clean; no false positives on intent (`purpose`/`meaning`).

### A2. Validator refinements 🟡 — ✅ MOSTLY DONE
- [x] **`requires <value> in <reg>`** checked by value-flow (`_check_value_flow`):
  the value must occupy that register here, else `E-VALUE-FLOW`.
- [x] **Asserted `liveOut` mismatch** — `E-LIVE-ASSERT`: a declared `liveOut`
  register must be live there per the backward fixpoint (`_check_backward`).
- [x] **Unreachable-block detection** — `W-UNREACHABLE` (`_check_reachability`):
  BFS from entry along declared `successor` edges; covers the `E-CFG-EDGE`
  "not reachable" half.
- [x] tests: `tests/refine_test.py` (all three fire); examples stay clean.
- [~] **Value-level `W-CLOBBER`** — *decision:* keep the split. Register-level
  clobber = `W-CLOBBER`; value-level clobber (a named value destroyed across a
  call) = `E-VALUE-FLOW`. No merge; documented here.
- [ ] **Diagnostics fix-site uniformity** — handle + code everywhere; the
  "nearest def is X" hint is only on some messages. Polish later (DESIGN §5.1).

### A3. Close the silent edges — ✅ COMPLETE (2026-06-10)
Every item below is now enforced; the completion pass landed the last ones.
Each was originally an empirically-confirmed silent failure or crash. Kept as
the audit ledger.

- [x] **`E-CFG-LAYOUT`: fall-through adjacency** — ✅ DONE (gauntlet shakedown,
  2026-06-09): `_check_layout` enforces all four clauses (adjacency, rows after
  the terminator, running off the last block, entry-block targets). A noreturn
  syscall (`return -` in syscalls.tsv) counts as a terminator of kind `syscall`
  — which exposed and fixed four stale `terminates return` facts in shipped
  examples. The reorder probe now errors. Regression: `tests/test_gauntlet_shakedown.py`.
- [x] **`E-DUP`** — ✅ DONE (completion pass): duplicate single-valued facts,
  case-insensitive block-label collisions, assembler symbol collisions;
  re-`is` is a parse error. Regressions: `tests/test_complete.py`.
- [x] **`E-CFG-EDGE` exactness** — ✅ DONE: `terminates` cross-check, stale
  successors (terminator-derived edge sets, both directions), and the
  `predecessor` inverse when present.
- [x] **Targeted entry block** — ✅ DONE both halves: the §15.1 label rule is
  implemented in `emit.py` (`.L<entry>` after the function symbol) and the
  construct is legal — the interim validator rejection is removed.
- [x] **`E-DATA`** — ✅ DONE (edge audit, 2026-06-10): full LANGUAGE §6
  contract enforced — bss size/value rules, Bytes size vs escaped length,
  unknown type/section, `align` power-of-two (a zero align crashed exec).
  Regressions: `tests/test_edges.py`.
- [x] **`E-ORDER-KEY`** — ✅ DONE: integer-ness + per-block uniqueness; emit
  falls back to source order instead of crashing; exec raises ExecError.
- [x] **`E-PARSE` unterminated string** — ✅ DONE: a parse error.
- [x] **`clobbers` narrowing** — ✅ DONE: honored by forward liveness,
  backward liveness (`W-CLOBBER`), and value-flow; tokens `E-ISA-REG`-checked.
- [x] **`saves`/`restores`** — ✅ DONE: SAME-slot pairing plus a per-path
  forward proof (`_check_restore_paths`): every clobbered callee-saved
  register and post-call `returnAddress` restored on EVERY path to a return.
- [x] **`stack bytes` vs actual prologue** — ✅ DONE (lint audit, 2026-06-09):
  `E-STACK-BALANCE` proves per-path frame balance, merge consistency, call
  alignment, and allocation == declared bytes; `E-STACK-OP` makes every sp
  write a declared surface (`effect stack.allocate`/`free` required, constant
  adjustments only). Regressions: `tests/test_lint.py`.
- [x] **Region/effect-qualifier `E-REF`** — ✅ DONE: `memory region <name>` and
  `effect memory.*/device.* <name>` must resolve to declared memoryRegions —
  landing it caught a stale region fact in hello_world.
- [x] **`writes` with `zero` destination** — ✅ DONE: `E-VALUE-FLOW` error
  ("the binding cannot exist"); `W-LINT` additionally flags any discarded
  result. Also new: `E-RESERVED` (gp/tp writes — abi.tsv's `reserved` row was
  the toolchain's only decorative table data).
- [x] Remaining §10.5 rows — ✅ DONE, check-or-demote applied to every one:
  `liveIn`/`kills` checked vs backward liveness; `valueBindings complete`
  checked (reads-side) in value-flow; `syscall` names `E-REF`-checked;
  `E-EXT-UNAVAILABLE` live (extmap.tsv × new profiles.tsv); value provenance
  (`definedBy`/`storedIn`/`restoredBy`/`in`) cross-checked; `liveAcross` and
  `clobberRisk` DEMOTED to S-intent (their checkable forms: `liveOut`,
  `W-CLOBBER`).
- **Done-when:** every probe in the 2026-06-09 audit produces a diagnostic (or
  a documented demotion); `tests/` gains a regression file per probe; the
  §10.5 ◌ table shrinks accordingly.

### A4. Edge audit 2026-06-10 — ✅ ALL 14 FINDINGS FIXED
An adversarial subagent probed parser/emit/validate/interp/fmt/CLI for unknown
edges; all 14 verified findings landed as fixes the same day
(`tests/test_edges.py`, 20 regressions):
- **`E-ENTITY`** (new code): untyped/unknown-typed entities — code that
  VANISHED from check+emit+exec with a clean bill of health — now error.
- **Function-scoped ownership** (`E-REF`): targets/successors/slot-offsets may
  not cross functions; referenced slots need integer offsets; `program entry`
  must resolve. **Exactly one `entry yes` block** (`E-CFG-LAYOUT`).
- **One integer grammar** (`E-ISA-FIELD`): decimal only — `0x…` validated
  clean but crashed exec; `1_000_000` ran clean but emitted GAS-invalid `.s`.
- **One `writes` per row** (`E-VALUE-FLOW`): static set vs runtime tag
  disagreed.
- **fmt integrity**: args containing `#`/`|`/`"` are quoted (a bare `#`
  truncated re-parsed source); subjects/predicates are bare identifiers at
  parse; `is` takes exactly one type.
- **Crash → diagnostic discipline**: emit renders None instead of raising on
  missing targets (§15.1 pinned for real); exec raises ExecError on unknown
  registers / arg overflow / bad offsets / bad align; CLI usage errors exit 2.

## B. ISA breadth — beyond Tier A (the big one)

### B1. Generator from `riscv/riscv-opcodes` 🔴
- **What:** a `gen/` script that pulls the official machine-readable opcode repo
  and emits `optable.tsv` rows (sem name via the naming rules, mnemonic, fmt,
  defines/uses, emit template) for every RVA23 instruction.
- **Why:** hand-curating hundreds of ops is the wrong move; coverage should ride
  on data (DESIGN §7.2). Unlocks Tiers B/V/P at once.
- **Where:** new `gen/`; DESIGN §7.2; feeds `sasm/optable.tsv`.
- **Sub-tasks:**
  - [x] vendor/parse `riscv-opcodes` — `gen/generate.py` parses the extension
    files (operands = tokens without `=`); writes `gen/generated_optable.tsv`.
  - [x] **coverage cross-check** — validates the hand table against ground truth:
    73/73 real (non-pseudo) ops confirmed upstream; reports the breadth gap (~19
    ops not yet curated). Guarded by `tests/gen_test.py` (skips without the clone).
  - [x] **structural derivation from the major opcode** — `derive()` maps the
    `6..2` opcode → defines/uses/effect/control; **reproduces the hand table 73/73**
    (structural fidelity, asserted by `gen_test.py`). Generated candidate table now
    carries opcode/defines/uses/effect/control.
  - [ ] apply the PascalCase full-word naming rules (mnemonic → sem) — needs a
    curated name map (`sub`→`Subtract` isn't derivable from the mnemonic).
  - [ ] remaining overrides: emit-template strings, op-width, pseudo expansions.
  - [ ] add a per-op `ext` column (replace `extmap.tsv` heuristic) and an
    `op-width` column (replace the derived `_op_width` in `validate.py`).
  - [ ] replace the hand table with the generated one + a regen check in CI.

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

### C1. Compact pipe sugar 🟢 — ✅ DONE
- **What:** `subj op X | rd a0 | base t3 | …` parses to identical one-fact-per-row.
- **Where:** `sasm/parser.py` (`tokenize` emits `|` tokens; `parse` splits clauses).
- **Done:** equivalence verified by `tests/sugar_test.py` (same facts *and* same
  emitted `.s`); wired into `eval.sh`; existing goldens unaffected.

### C2. `ordinal` ordering 🟢 — ✅ DONE
- **What:** when a block's insns carry `ordinal`, emit in ordinal order (else
  source order); all-or-nothing per block.
- **Where:** `sasm/emit.py` `_insns_of` (sorts by ordinal when all present);
  `validate.py` already flags `E-ORDER-MIXED`. DESIGN §11.1.
- **Done:** `tests/ordinal_test.py` (scrambled-source-order insns emit in ordinal
  order; mixed block flagged); wired into `eval.sh`.

### C3. `sasm fmt` — canonical formatter 🟡 — ✅ DONE
- **What:** idempotent, semantics-preserving re-serializer (one deterministic
  layout; facts grouped by predicate, order preserved within; args quoted iff
  they contain whitespace).
- **Where:** `sasm/format.py` + CLI `sasm fmt [-i]`. DESIGN §11.1.
- **Done:** `tests/fmt_test.py` proves idempotence and `emit∘parse∘fmt == emit∘parse`
  on all examples; wired into `eval.sh`.

### C4. Data-section completeness 🟡 — ✅ DONE
- **What:** all int widths (`.byte`/`.half`/`.word`/`.dword`), `.bss`/`.zero`
  reservation, `data align` (`.balign`), `data binding` (`.globl`/`.weak`), and
  `data size` (`.size`).
- **Where:** `sasm/emit.py` `_emit_data` (`_DATA_DIRECTIVE`); LANGUAGE §6.
- **Done:** new `examples/data_demo` uses `.data` + `.bss` + `align`; validates
  clean, assembles, and **runs under qemu (exit 42)** via the harness.

### C5. Symbols / linking 🟡 — ✅ MOSTLY DONE
- [x] `symbol` entity emission — `.weak`/`.globl`/`.type`; function `binding weak`
  + `symbolType` (`emit._emit_symbols`; `tests/symbol_test.py`).
- [x] **cross-translation-unit linking** — `examples/linked` (`main.sasm` calls an
  external `triple` defined in `lib.sasm`); linked + **runs under qemu (exit 42)**.
- [ ] relocations (`%hi`/`%lo`/`%pcrel`/GOT) via `symbol reloc`; `program pic`
  (PIC/relocs deferred — the assembler picks the right relocs for `la`/`call`
  automatically in the static non-PIE path we target). Linker scripts: out of scope.

## D. Validating the premise (the actual experiment) 🔴

### D1. The premise benchmark — 🟢 HARNESS LIVE + FIRST PILOT RUN (2026-06-10)
`benchmarks/d1.py` generates all four arms mechanically from one `.sasm`
(provably same information) and scores every arm with one oracle (native
build bar + qemu behavior). First pilot: Protocol 1, fib, 3 tasks x 4 arms,
n=1 — **a/c/d 3/3, b 2/3**; the one failure was behaviorally-correct code
with wrong spill annotations (the validator refused it — arm b's bar is
strictly higher, and Protocol 2's diagnostics would have named the exact
rows). Write-up with caveats: `benchmarks/runs/pilot/results.md`. Also
produced a language finding (the spill idiom, now in LANGUAGE §3).
Remaining for the full study (4 arms × 3 families × 2 protocols):
- **What:** measure the three §2.1 pillars across four arms — (a) raw `.s`,
  (c) `.s` + prose fact block at top, (d) `.s` + same facts as **inline comments**
  (the critical control), (b) `.sasm` — over three task families: comprehension
  questions, the long-range mutation set, and stale-fact / trace probes.
- **Why:** this is what *earns or sinks* the thesis; until it runs, the headline
  is a hypothesis. b-over-d is the only comparison that isolates
  addressability+checkability from mere locality.
- **Sub-tasks:**
  - [ ] mutation generator (resize frame, swap operand, add spill, reorder
    blocks, retarget branch) + a known-correct oracle per mutation (lower +
    assemble + run under qemu — reuse `testing/`).
  - [ ] arm generator: derive (c) and (d) mechanically from the `.sasm` so all
    arms provably carry the same information.
  - [ ] comprehension question set (family 1) with ground truth from the
    validator's derived state.
  - [ ] edit harness, **Protocol 1** (one-shot): score first-try
    correct-and-runs per arm.
  - [ ] edit harness, **Protocol 2** (closed loop, equal budgets): a/c/d get
    assembler + behavioral feedback, b additionally `sasm check`; score success
    within N rounds, rounds- and tokens-to-success.
  - [ ] stale-fact probes (family 3): one corrupted local fact in (d) vs (b);
    plus which-edit-broke-the-contract trace tasks.
  - [ ] report: predictions **b ≥ d > c > a** (P1), b-over-d gap **widens** under
    P2 and with function size; b≈d under P2 ⇒ format overbuilt (worth knowing).
- **Done-when:** a reproducible script produces the per-arm, per-family,
  per-protocol scores.

## E. Layer-1 lowering (SemanticScript → `.sasm`) 🔴

- **What:** the pass that turns arch-free source IR into `.sasm`: register
  allocation, stack-slot spilling, call lowering with caller-saved spills.
- **Why:** today Layer 2 is hand-written; this automates its input (DESIGN §16).
- **Done-when:** a small SemanticScript op lowers to validating, running `.sasm`.
- **Note:** deliberately last — prove the fact model + validator are useful first.

## F. Tooling / DX / CI 🟢 — ✅ MOSTLY DONE

- [x] **CI workflow** — `.github/workflows/ci.yml`: a `quick` job (snapshots +
  validator + property tests, no Docker) and a `full` job (build + run the
  `sasm-eval` image: snapshots + validator + qemu) on every push/PR.
- [x] **Packaging** — `pyproject.toml`; `pip install -e .` gives a `sasm` command
  (`[project.scripts] sasm = sasm.cli:main`); ships the `.tsv` tables as
  package-data. Entry point verified to resolve.
- [x] **`LICENSE`** — MIT.
- [x] **Repo URL** — `docs/index.html` auto-resolves the GitHub link when served
  from a `*.github.io` host; left as a placeholder otherwise.
- [x] More example coverage — pipe sugar (`sugar_test`), ordinal (`ordinal_test`),
  data section (`data_demo`), cross-TU linking (`linked`); fp coverage waits on
  Tier B (B2).

## H. Verification strategy — DESIGN §19 🟢 core landed, growing

- [x] **Taint-tracking interpreter** (`sasm/interp.py`, `sasm exec`) — executes
  the fact rows on a shadow-tagged RV64IM machine; the R-contract catalog
  (§18.3) runs in-process: `R-VALUE-FLOW`/`R-LIVE-OUT`/`R-ABI-PRESERVE`/
  `R-ABI-FRAME`/`R-ABI-ALIGN`/`R-EFFECT`/`R-CFG-EDGE`, single-use return
  tokens, trace-scope coverage report. All 10 runnable examples execute
  correctly in it; the §11 path-dependent clobber is caught concretely.
  Regressions: `tests/test_interp.py`.
- [x] **`mergesFrom` — the minimal declared phi** (LANGUAGE §4) — forced by the
  interpreter's first run (fib's base path flagged F(11) times); accepted by
  static union + runtime taint; `E-REF`-validated.
- [x] **Mutation tier** (`tests/test_mutation.py`) — 75 mutants over
  fib/sum_array/ackermann: every behavior-changing mutant caught statically or
  dynamically, equivalents proven by byte-identity, holes fail the build
  unless allow-listed with a reason. **First finding:** out-of-frame stack
  slots only warned while corrupting the caller's frame → upgraded to
  `E-SLOT-RANGE` (error).
- [ ] **`check --coverage` / `--strict`** — per-fact verified/unverified
  labeling as CLI output; strict = unverifiable facts are errors.
- [ ] **Differential exec-vs-qemu** — same vectors, compare final state; a
  divergence is a table/emitter/interpreter bug (verifies the verifier's
  tables).
- [ ] **More mutation operators** (block reorder via text move, fact staleness
  injection, slot-collision) + run over the full example corpus in CI.
- [ ] **Viewing lenses** (`sasm view <function>`, compact pipe-sugar render,
  per-value slices) — the standing answer to the verbosity-for-humans and
  context-cost critiques (§19 discussion; external review cons #1/#8). The
  file is the database; readers should get queries, not the whole dump.
- [x] **`W-RMW-RACE` + `memoryRegion concurrentWriters`** — ✅ DONE
  (2026-06-10, from an external review's one novel finding): non-atomic
  load-modify-store on a concurrent region is flagged; AMOs are the
  sanctioned form; absence of the fact = explicit single-writer assumption.
  Regressions: `tests/test_lint.py`.

## G. Runtime debug API — DESIGN §18 🔴 (real-binary half; gated)

- **What:** the *real-binary* half: handle→address sidecar map and an
  activation-aware qemu-gdbstub adapter (`sasm run --break …`). The R-contract
  checks themselves are LIVE in-process via the §19.2 interpreter (section H);
  this section is only about running them against the emitted binary under
  qemu.
- **Gate (DESIGN §18 header):** do not build until (i) D1's Protocol-2 result
  exists and (ii) the A3 statics the R-checks would backstop have landed.
  Design was adversarially reviewed by three independent critiques (2026-06-09);
  their blockers are folded into §18 (activation-filtered temp breakpoints,
  TailCall-as-exit-event, R-VALUE-FLOW warning-by-default under partial
  annotations, multi-TU handle qualification, observed/declared labeling,
  coverage report, static-counterpart discipline).
- **Build order when ungated:**
  - [ ] `sasm build --map` sidecar (handle → `.s` line + content hashes) +
    `-Wa,--gdwarf-4` / `-mno-relax` pins in the testing image.
  - [ ] host-side stub adapter: connect/break/continue/registers/memory over TCP
    to in-container `qemu-riscv64 -g`; shared-address breakpoint dedup.
  - [ ] activation shadow stack (entry/return/TailCall/process-exit events;
    entry-point roots exempt; opaque-frame suspension).
  - [ ] batch contract checks, cheap first: `R-ABI-ALIGN`, `R-CFG-EDGE`
    (head-pair form), `R-ABI-PRESERVE`, `R-EFFECT` (syscalls at covered rows);
    then `R-LIVE-OUT` and `R-VALUE-FLOW` exactly as scoped in §18.3.
  - [ ] coverage report + `observed`/`declared` value labeling.
  - [ ] v2 interactive session (step/stepOver/stepOut/watch/trace) — separate
    gate: only if the D1 debugging task family shows the channel pays.
- **Done-when (the demo that earns the section):** the §11 path-dependent
  clobber — statically passed by the may-analysis — is caught at runtime as
  `R-VALUE-FLOW`/`R-LIVE-OUT` on the executed path, with a diagnostic naming
  both the declaring row and the observation row.

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
- [x] Compact multi-fact-per-line sugar — implemented in `parser.py`; equivalence test `tests/sugar_test.py` (C1)
- [x] **`sasm fmt`** — canonical formatter (`sasm/format.py`, `sasm fmt`); idempotent + semantics-preserving (C3)
- [x] `facts <entity>` query command — agent-facing introspection (`sasm facts`)
- [ ] Generator from `riscv/riscv-opcodes` → Tier B/V/P table rows (§7.2) → **details: B1**
- [x] **`isa.py`** — loads optable/regs TSVs (extend to abi/formats/etc. for the validator)
- [x] **`emit.py`** — the projection `π`; **byte-identical** on all three examples (DESIGN §15.1); CLI `sasm emit|build|facts`
- [x] **`validate.py`** — **the ENTIRE §14 catalog wired (32 codes)**, incl.
  `E-CFG-LAYOUT` (layout/terminator clauses, noreturn-syscall terminators), the
  `terminates` cross-check, the call-result `writes` binding (gauntlet
  shakedown, 2026-06-09), and the every-surface set (`E-RESERVED`,
  `E-STACK-OP`/`E-STACK-BALANCE`, `W-LINT`, region-name `E-REF`; lint audit
  2026-06-09, `tests/test_lint.py`). Original catalog: `E-ISA-OPCODE/REG/FIELD`, `E-REF`, `E-ABI-ALIGN`, `E-ABI-PRESERVE`, `E-LEAF`, `E-EFFECT` (internal-effect rule), `E-CFG-EDGE`, `E-ORDER-MIXED`, `E-IMM-RANGE`, `E-TYPE`, `E-SLOT-RANGE` (upgraded from W-SLOT by the §19 mutation tier), forward liveness `E-LIVE-UNDEF`/`E-LIVE-RET`, backward liveness `W-DEAD`/`W-CLOBBER`, value-flow `E-VALUE-FLOW` (may-analysis over named values — handles fib's phi merge, catches the naive value-clobber), `E-DERIVABLE` (register-restatement case). CLI `sasm check`; `build` refuses on errors; all examples clean, every code's mutation caught. Remaining: full reachability `E-DERIVABLE` (beyond register-restatement) is still research-grade; `E-PARSE-*` lives in the parser.
- [~] Diagnostics carry **stable code + entity handle + fix site** (DESIGN §5.1/§14) — code+handle done; fix-site uniformity pending (see A2).
- [x] **Value-flow pass** (`E-VALUE-FLOW`) — may-analysis (reaching-defs over named values), handles fib's phi merge, catches the value-clobber.
- [~] **Derivable-fact linter** (`E-DERIVABLE`) — register-restatement case done; **general reachability linter pending (see A1, ⚠ load-bearing).**
- [x] **`in`/`value` Type check** (`E-TYPE`) — op-width vs value `type` (width derived from op).
- [x] `E-ORDER-MIXED` — rejects blocks mixing ordinaled and bare insns (§11.1).
- [x] Round-trip test on the three examples — `tests/snapshot.sh` (byte-match) + `testing/` (assemble + run under qemu); all green

> The §13 CFG/fixpoint is shared by **four** consumers: liveness, value-flow
> (§11.2), the derivable-fact linter, and return-definedness. Build it once, well.

## Validating the premise (DESIGN §16.1)
- [ ] **Premise benchmark** (4 arms incl. inline-comment control; comprehension /
  edit / staleness families; one-shot + closed-loop protocols) → **details: D1**

## Open design questions to explore (from DESIGN §17)
- [ ] Symbolic values vs registers — do values become first-class SSA names?
- [ ] Multi-valued returns / structs beyond a0/a1
- [ ] Pseudo expansion visibility (record vs defer)
- [ ] Interprocedural effect/clobber summaries for `call`
- [ ] How much of the ABI/register/CSR data is pure tables vs code
