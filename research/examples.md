# Examples

Each demo is a triptych — the same program in three representations:

| file | layer | audience |
|------|-------|----------|
| `*.c`    | source            | what a human wrote |
| `*.sasm` | semantic assembly (Layer 2) | what an agent reads/edits — verbose, fact-rich |
| `*.s`    | raw RISC-V (Layer 3) | what the assembler consumes — the projection `π(*.sasm)` |

The `.sasm` is intentionally many times longer than the `.s`. That verbosity is
the point (DESIGN §2.1): it stores intent, dataflow, effects, ABI contracts, and
named stack slots that the `.s` throws away. Lowering strips all of it.

## The three demos

### 1. `simple_add2/` — leaf function
`add2(a, b) = a + b`. No memory, no stack, no calls. The smallest thing that
still has an ABI contract (args in `a0`/`a1`, result in `a0`). Shows the bare
function / block / insn fact model.

### 2. `challenging_sum_array/` — loop + memory
`sum_array(data, n)` sums an array. Introduces a real CFG (prologue → condition →
body → done), a backward edge (the loop), memory loads with a region annotation,
and values that stay live across the loop (`sum`, `i`). Still a leaf, still no
stack frame.

### 3. `brainworms_fib/` — recursion + **clobber handling**
`fib(n)` computed recursively — the showcase for how the language handles
register clobbering across calls. A `Call` clobbers every caller-saved register
(set *derived* from `abi.tsv`, never hand-listed). So values that must outlive a
call are moved to callee-saved registers and the callee-saved contract is honored:
- `n` → `s0`, `fib(n-1)` → `s1` (survive the calls), `ra` → a stack slot.
- the live-across-call bindings are explicit: `R3 liveOut s0:n`,
  `R6 liveOut s1:firstResult` — the facts the validator checks, and what an agent
  edits against instead of silently breaking the recursion.
- `saves`/`restores` tie each prologue store to its epilogue load via named slots.
- the file's header block shows the **naive bug** (leaving `n` in `a0`) and the
  `W-CLOBBER` diagnostic that would catch it.

It also demonstrates the **internal-effect rule** (stack traffic is `region
stackFrame` → not an observable effect, so the function declares only `effect
call`) and notes the base-case/recurse **phi merge** at the epilogue.

## The gauntlet (e2e shakedown examples, 2026-06)

Three programs chosen because their *raw-asm* difficulty is high — each stresses
a different class of silent failure, and writing them is what earned the
`E-CFG-LAYOUT` check, the noreturn-syscall terminator kind, and the call-result
rule (DESIGN §11.2):

### 4. `gauntlet_ackermann/` — nested recursion
`ack(level, count)` with the brutal case `ack(level-1, ack(level, count-1))`:
the inner call's result becomes the outer call's argument while `level` rides
out the inner call in `s0`. Three-way dispatch CFG where two case blocks sit
*after* the shared epilogue and rejoin it by explicit `Jump` — the layout shape
that exercises fall-through adjacency. `callOuter writes result` shows the
call-result rule making "a0 now holds the callee's result" a checkable fact.
`ack(3,3)` walks 2432 frames in the harness.

### 5. `gauntlet_quicksort/` — two recursions + a mutating loop
In-place Lomuto quicksort: an 8-block CFG (guard → init → loop head → body →
swap → advance → done → epilogue) where **every fall-through edge is
load-bearing**; three values (`array`/`high`/`pivotIndex`) ride the first
recursive call in `s0`/`s1`/`s2` while `low` sits untouched in `a1` through the
whole partition; data-dependent swaps through rotating scratch registers. The
hardest file in the repo by fact count.

### 6. `gauntlet_revlist/` — pointer rotation, two functions, one TU
In-place linked-list reversal: the strict 4-step rotation (read link → flip
link → save prev → advance) where any reorder silently produces a cycle — each
step's `reads`/`writes` chain pins the order. Plus a position-weighted checksum
function in the same file: two functions sharing the file-global namespace
(values named `cursor`/`walker`, not twice `cursor` — the multi-function naming
rule in practice).

## Design principles these examples follow

- **Inclusion rule (LANGUAGE §0.5)** — surface only state that crosses an
  instruction, block, call, slot, or memory boundary. `sum_array` declares the
  loop-carried `sum`/`i` and the live-across `data`/`count`, but **drops** the
  adjacent scratch (`byteOffset`, `elementAddress`, `element`) — those bindings
  are purely local, so naming them would store unchecked copies that pin no
  contract (DESIGN §2.1).
- **Value-binding rule (DESIGN §11.2)** — `reads`/`writes` name declared `value`
  entities, never registers (a register use is derivable from the op table).
- **`add2` is the exception** — being a tutorial, it surfaces local bindings the
  inclusion rule would otherwise omit, and says so.

## Reading order

Open the `.c` first for intent, then the `.sasm` to see that intent promoted into
facts, then the `.s` to see what survives lowering. The diff in length between the
last two *is* the context the semantic layer adds.
