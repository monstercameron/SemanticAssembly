# D1 pilot — first live run (2026-06-10)

**Setup.** Protocol 1 (one-shot, no feedback, no tools beyond reading the
input) on `brainworms_fib`; 3 long-range edit tasks × 4 arms × 1 trial; the
editing agents were Claude subagents (one per cell, fresh context). Arms
generated mechanically by `benchmarks/d1.py` from the `.sasm` (provably same
information). Oracle: the candidate's native build bar (assemble for a/c/d;
`sasm build` — which validates — for b), then `qemu` runs `fib(10)=55`.

| task | a (raw .s) | c (prose block) | d (inline facts) | b (.sasm) |
|------|-----------|------------------|------------------|-----------|
| t1 grow frame 32→48, move slots | PASS | PASS | PASS | PASS |
| t2 swap s0/s1 roles in body | PASS | PASS | PASS | PASS |
| t3 spill firstResult to stack, drop s1 | PASS | PASS | PASS | **FAIL** |
| **total** | **3/3** | **3/3** | **3/3** | **2/3** |

**The t3/b failure is the pilot's most informative datum.** The agent's edit
was *behaviorally correct* — the assembly its file would emit is byte-for-byte
the code that passed in the other three arms. It failed the validator: it put
`writes firstResult` on the StoreDoubleword (stores define no register — the
binding cannot exist; E-VALUE-FLOW), instead of the spill idiom (`writes` on
the producing call; the store/load then carry the value through memory tags).
Three readings, all true:

1. **Arm b's bar is strictly higher**: code AND facts must be right. The other
   arms are never asked whether their annotations (comments) are correct —
   arm d's comments could have been equally wrong and nothing would notice.
   That asymmetry is the format's promise and its authoring cost,
   simultaneously.
2. **Protocol 2 would almost certainly flip this cell**: the three diagnostics
   name the exact rows and the reason; a/c/d receive no comparable signal when
   they ARE wrong. The one-shot framing measures the representation without
   its loop — by design, and this is what that looks like.
3. **A language finding**: the spill-annotation idiom is non-obvious from a
   primer. LANGUAGE §3 now documents it (see "Annotating a spill").

**Honest caveats (do not over-read this table).**
- n = 1 per cell, one model family, one function. Indicative, not conclusive.
- fib is ~20 instructions — the thesis (DESIGN §16.1) predicts arm gaps
  *widen with function size*; at this size every arm is within easy reach,
  and the pilot confirms exactly that: representation didn't matter for
  correctness at toy scale.
- Arm b received a 6-line format primer (the other arms got a 1-line note);
  a full benchmark must fix the format-documentation budget explicitly.
- Comprehension (family 1) and staleness/trace (family 3) tasks not yet run.

**What this run establishes**: the harness end-to-end (mechanical arm
generation with provable same-information, one oracle for all arms, scoring),
a baseline protocol, and the first measured datum: at toy scale, Protocol 1,
all representations succeed on behavior; only `.sasm` is additionally held to
fact-correctness, and that is where it lost its point.

**Next**: scale the corpus (quicksort-sized functions, where the prediction
has teeth), n ≥ 10 per cell, Protocol 2 with equal feedback budgets, and
families 1/3. Tracked in TODOS D1.
