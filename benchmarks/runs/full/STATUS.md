# D1 full study — PAUSED mid-run (2026-06-10)

Round-1 state when paused (session-limit economics; resumed later by design):

| family | cells | filled | notes |
|---|---|---|---|
| F1 comprehension | 280 | **280 — COMPLETE** | 280/280 correct, ALL arms (incl. raw `.s`) |
| F2 edits | 320 | 117 | fib complete (n=8–10/cell); quicksort q1–q5 partial |
| F3 stale-fact probes | 40 | 40 — COMPLETE (r1) | P2 rounds not yet run |
| F3T traces | 40 | 0 | not started |

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

## To resume

1. `python benchmarks/study.py missing` → 243 round-1 cells listed in
   `missing.json` (203 F2 quicksort edits + 40 F3T traces).
2. Re-launch the sequential filler workflow (one agent at a time) over
   `missing.json` — editor cells write `candidates/<name><ext>`, answer cells
   write `answers/<name>.txt`; prompts in `prompts/<cell>.txt`.
3. `python benchmarks/study.py score` after each wave.
4. Protocol 2: `python benchmarks/study.py rounds 2` → sequential editor wave
   over `prompts/r2/*` → score → repeat for rounds 3, 4.
5. `python benchmarks/study.py score-answers`, then `report`, then write
   `results.md` and update TODOS D1 / DESIGN §16.1 / README.

A validator hole found while building the probes (saves/restores row
consistency) is already fixed + regression-tested (`tests/test_spillrow.py`).
