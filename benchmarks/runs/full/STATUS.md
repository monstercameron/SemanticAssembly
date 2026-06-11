# D1 full study — ROUND 1 COMPLETE; Protocol-2 rounds in flight (2026-06-10/11)

| family | cells | filled | round-1 result |
|---|---|---|---|
| F1 comprehension | 280 | 280 — COMPLETE | 280/280 correct, ALL arms — saturated, no discriminatory power |
| F2 edits | 320 | 320 — COMPLETE | 269/320 pass r1; failures: 33 arm b (32 at the VALIDATE stage), 7 a, 0 c, 1 d, plus q4-a 6 + q5-a 1 + q5-d 1 |
| F3 stale-fact probes | 40 | 40 — COMPLETE | d 20/20 (lie ignored); b 9/19, 11 validator refusals |
| F3T traces | 40 | 40 — COMPLETE | 40/40 correct, BOTH arms — saturated |

**Round-1 headline (one-shot, honest):** arm c (prose block) is the strongest
arm on the quicksort edit set (10/10 everywhere); arm b loses one-shot — but
42 of its 43 failures are `stage=validate` (the fact-consistency bar refused
the file), exactly 1 is an observed behavioral failure. Whether diagnostics
convert those refusals into passes is what the in-flight Protocol-2 rounds
measure. 51 round-2 prompts generated; round-2 wave running (early partial:
15 of the first 23 round-2 attempts pass).

Raw tables: `raw_tables.md` (regenerate with `python benchmarks/study.py report`).

**Model split (cost decision, 2026-06-10):** round-1 cells filled before the
pause (all of fib F2, F1, F3) used Fable 5 subagents; the resumed remainder
(quicksort F2, F3T traces) and all Protocol-2 rounds use Sonnet 4.6. Arm
comparisons are always within a function/task, so the split does not enter
the arm contrast — but cross-function comparisons (fib vs quicksort rates)
now carry a model confound and must be read per-function.

## What the partial data already shows (read with n caveats)

1. **F1 saturates at this function size**: 100% accuracy on every arm,
   including raw `.s`. No comprehension gap at ~20–40 instructions — exactly
   the size-scaling prediction's small end. The gap, if it exists, needs
   bigger functions.
2. **fib t3 (the spill task) replicates the pilot at n=8**: a/c/d 10/10,
   b 2/8 one-shot. The spill-annotation idiom remains arm b's hardest
   authoring burden; Protocol 2 (not yet run for these cells) is predicted
   to close it — the diagnostics name the exact rows.
3. **Stale-fact probes (F3), round 1**: arm d went 10/10 + 10/10 — the lying
   comment did NOT propagate; agents derived the truth from the code and
   ignored the stale comment. Arm b: 1/10 (c1) and 8/9 (c2) — the validator
   refuses the corrupted file loudly (naming the stale row) unless the agent
   repairs the lie as part of the edit. Honest reading: at this scale the
   staleness *harm* prediction for (d) is NOT supported; what IS supported is
   loud-vs-silent (b cannot ship with the stale fact; d ships silently with a
   lie still in the file — invisible to the behavioral oracle, visible in the
   artifact).

## Round-2 result (Protocol 2, first feedback round — 2026-06-11)

One feedback round converted most of arm b's validator refusals:
q3-b 3/10 → 10/10 · q5-b 2/10 → 8/10 · F3-c1-b 1/10 → 9/10 (the diagnostic
names the stale row) · F3-c2-b 8/10 → 10/10 · t3-b 2/10 → 4/10 ·
q4-b 1/10 → 3/10. Arm a's failures also recovered with assembler+qemu
feedback alone (q4-a 4/10 → 10/10). 16 b-cells remain failing after round 2
(t3 6, q4 7, q5 2, c1 1); rounds 3–4 not yet run. PAUSED here at Cam's
request.

## Remaining

1. Protocol-2 rounds: round 2 in flight; then `python benchmarks/study.py
   rounds 3` → sequential wave → score → round 4 likewise.
2. `report`, then `results.md` bounded by `REVIEW-2026-06-10.md`, then
   TODOS D1 / DESIGN §16.1 / README updates.

A validator hole found while building the probes (saves/restores row
consistency) is already fixed + regression-tested (`tests/test_spillrow.py`).
