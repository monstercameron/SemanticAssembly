"""D1 full study driver (DESIGN §16.1) — generation, scoring, aggregation.

Builds every cell of the full benchmark from the two study functions
(fib, quicksort), using d1.py's mechanical arm generation, and scores
candidates with the one behavioral oracle. The agent invocation layer is
external (subagent waves); this script owns everything deterministic:

  python benchmarks/study.py gen     # arms, corruptions, traces, prompts, manifest
  python benchmarks/study.py score   # score every file in runs/full/candidates
  python benchmarks/study.py report  # aggregate scores into result tables

Families (§16.1): F2 = long-range edits (Protocols 1+2; Protocol 2 reuses the
round-1 attempt and feeds failures their toolchain output for up to 3 more
rounds). F1 = comprehension questions (string-matched ground truth). F3 =
stale-fact probes (one corrupted S-fact; arm d's comment lies silently, arm
b's row is validator-visible). F3T = which-edit-broke-the-contract traces.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from d1 import build_arms, IMAGE                  # noqa: E402
from sasm.emit import emit                        # noqa: E402
from sasm.parser import parse                     # noqa: E402
from sasm.validate import validate                # noqa: E402

STUDY = ROOT / "benchmarks" / "study"
RUN = ROOT / "benchmarks" / "runs" / "full"

EXAMPLES = {
    "fib": ("examples/brainworms_fib/fib.sasm", "testing/harness/fib.c"),
    "quicksort": ("examples/gauntlet_quicksort/quicksort.sasm",
                  "testing/harness/quicksort.c"),
}

BEHAVIOR = {
    "fib": "fib(n) must compute the nth Fibonacci number recursively; "
           "the test harness checks fib(10) = 55.",
    "quicksort": "qsort64(long *a, long lo, long hi) must sort a[lo..hi] in "
                 "place (inclusive bounds); the test harness checks arrays "
                 "with duplicates, already-sorted, reverse-sorted, and "
                 "single-element inputs.",
}

# Fixed documentation budget per arm (a study control — see results write-up).
_COMMON = (
    "This is RISC-V RV64 assembly (GNU assembler syntax). Registers: a0-a7 "
    "arguments/results and caller-saved; t0-t6 caller-saved temporaries; "
    "s0-s11 callee-saved; ra the return address; sp the stack pointer, which "
    "must be 16-byte aligned at every call. A `call` clobbers ra and every "
    "a*/t* register. The file is assembled with riscv64-linux-gnu-gcc and "
    "must assemble cleanly and behave correctly."
)
PRIMERS = {
    "a": _COMMON,
    "c": _COMMON + " A block of '#' comments at the top of the file states "
         "facts about the function (ABI, frame layout, liveness). They are "
         "informative comments only.",
    "d": _COMMON + " Inline '#' comments on individual instructions state "
         "facts about them (reads/writes of named logical values, liveOut "
         "across calls, purposes). They are informative comments only.",
    "b": (
        "This is semantic assembly (.sasm): one fact per row, in the form "
        "`subject predicate arguments...`. Entities are declared with `is` "
        "(program/function/block/insn/value/stackSlot/memoryRegion); each "
        "insn maps 1:1 to one assembly statement. Instruction fields: "
        "`operation` (a semantic op such as Add, AddImmediate, Move, Call, "
        "LoadDoubleword, StoreDoubleword, BranchLessThan, "
        "BranchGreaterOrEqual, Jump, Return, ShiftLeftLogicalImmediate, "
        "LoadImmediate), `destination`/`firstSource`/`secondSource`, and "
        "`base` + `offset` (a stackSlot handle or an integer) for memory "
        "ops. Semantic facts: `reads <value>`/`writes <value>` bind the "
        "row's registers to named values; `liveOut reg:value` asserts a "
        "value survives a call in that register; `saves reg slot` / "
        "`restores reg slot` pair a spill through a named stackSlot. A "
        "store to a slot does not `write` a value — the value binding stays "
        "on the producing instruction; stores and loads carry it through "
        "memory. Blocks declare `successor` edges and `terminates`; source "
        "order is layout, so every fall-through edge must be adjacent. The "
        "file is compiled with `sasm build`, which VALIDATES every fact "
        "(facts and code must agree) before emitting assembly that is then "
        "assembled and run."
    ),
}

EDIT_INSTRUCTIONS = (
    "Edit the file below to accomplish the task. {behavior}\n"
    "Return the COMPLETE edited file content (the whole file, top to "
    "bottom). Do not wrap it in markdown fences. Do not add explanations."
)

QUESTION_INSTRUCTIONS = (
    "Answer the question about the file below. Reply with ONLY the short "
    "answer: a register name, a decimal number, yes or no, a single word, "
    "or (only if the question asks for an instruction) the instruction "
    "text. No explanations."
)


def _read(p): return pathlib.Path(p).read_text(encoding="utf-8")


def _write(p, text):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def _check_errors(src_text):
    """Validator errors (not warnings) for a .sasm text."""
    try:
        prog = parse(src_text)
    except SyntaxError as e:
        return [f"parse error: {e}"], None
    diags = validate(prog)
    return [str(d) for d in diags if d.severity == "error"], prog


def _all_diags(src_text):
    try:
        prog = parse(src_text)
    except SyntaxError as e:
        return [f"parse error: {e}"]
    return [str(d) for d in validate(prog)]


def _apply(text, old, new, where):
    n = text.count(old)
    assert n == 1, f"{where}: pattern occurs {n} times (need exactly 1): {old!r}"
    return text.replace(old, new)


# ----------------------------------------------------------------------- gen

def gen():
    tasks = json.loads(_read(STUDY / "tasks_edit.json"))
    questions = json.loads(_read(STUDY / "questions.json"))
    corruptions = json.loads(_read(STUDY / "corruptions.json"))
    traces = json.loads(_read(STUDY / "traces.json"))
    manifest = {}

    arms_by_fn = {}
    for fn, (sasm_rel, harness) in EXAMPLES.items():
        arms = build_arms(ROOT / sasm_rel)
        arms_by_fn[fn] = arms
        for arm, text in arms.items():
            ext = ".sasm" if arm == "b" else ".s"
            _write(RUN / "arms" / fn / f"arm_{arm}{ext}", text)
        # sanity: the clean arm b must validate with zero errors
        errs, _ = _check_errors(arms["b"])
        assert not errs, f"{fn}: clean source has validator errors: {errs}"

    # --- F2: edit cells -----------------------------------------------------
    for fn, fn_tasks in tasks.items():
        harness = EXAMPLES[fn][1]
        for tid, instruction in fn_tasks.items():
            for arm in "acdb":
                cell = f"F2-{fn}-{tid}-{arm}"
                ext = ".sasm" if arm == "b" else ".s"
                prompt = (
                    f"{PRIMERS[arm]}\n\nTASK: {instruction}\n\n"
                    + EDIT_INSTRUCTIONS.format(behavior=BEHAVIOR[fn])
                    + "\n\nFILE:\n" + arms_by_fn[fn][arm]
                )
                _write(RUN / "prompts" / f"{cell}.txt", prompt)
                manifest[cell] = {"family": "F2", "function": fn, "task": tid,
                                  "arm": arm, "harness": harness, "ext": ext}

    # --- F1: comprehension cells ---------------------------------------------
    for fn, qs in questions.items():
        for qid, q in qs.items():
            for arm in "acdb":
                cell = f"F1-{fn}-{qid}-{arm}"
                prompt = (
                    f"{PRIMERS[arm]}\n\n{QUESTION_INSTRUCTIONS}\n\n"
                    f"QUESTION: {q['question']}\n\nFILE:\n"
                    + arms_by_fn[fn][arm]
                )
                _write(RUN / "prompts" / f"{cell}.txt", prompt)
                manifest[cell] = {"family": "F1", "function": fn,
                                  "question": qid, "arm": arm,
                                  "accept": q["accept"]}

    # --- F3: stale-fact probes (arms b and d over a corrupted source) --------
    for cid, c in corruptions.items():
        fn = c["function"]
        harness = EXAMPLES[fn][1]
        clean_src = _read(ROOT / EXAMPLES[fn][0])
        bad_src = _apply(clean_src, c["lie"][0], c["lie"][1], cid)
        # invariants that make this a *staleness* probe:
        # 1. the lie changes no code — emitted .s is byte-identical
        assert emit(parse(bad_src)) == emit(parse(clean_src)), \
            f"{cid}: corruption changed emitted code (must be S-fact only)"
        # 2. the corrupted .sasm is validator-visible (arm b is told loudly)
        errs, _ = _check_errors(bad_src)
        assert errs, f"{cid}: corrupted source passes validation (bad probe)"
        bad_arms = build_arms_from_text(bad_src)
        # 3. arm d's lying comment differs from the clean one
        assert bad_arms["d"] != arms_by_fn[fn]["d"], f"{cid}: d-arm unchanged"
        for arm in "db":
            ext = ".sasm" if arm == "b" else ".s"
            _write(RUN / "arms" / f"{fn}-{cid}" / f"arm_{arm}{ext}",
                   bad_arms[arm])
            cell = f"F3-{cid}-{arm}"
            prompt = (
                f"{PRIMERS[arm]}\n\nTASK: {c['task']}\n\n"
                + EDIT_INSTRUCTIONS.format(behavior=BEHAVIOR[fn])
                + "\n\nFILE:\n" + bad_arms[arm]
            )
            _write(RUN / "prompts" / f"{cell}.txt", prompt)
            manifest[cell] = {"family": "F3", "function": fn,
                              "corruption": cid, "arm": arm,
                              "harness": harness, "ext": ext,
                              "truth_register": c["truth_register"],
                              "lie_register": c["lie_register"]}

    # --- F3T: which-edit-broke-the-contract traces ----------------------------
    for tid, t in traces.items():
        fn = t["function"]
        for arm in "db":
            text = arms_by_fn[fn][arm]
            shown = []
            for i, edit in enumerate(t["edits"], 1):
                lines = []
                for old, new in edit[arm]:
                    text = _apply(text, old, new, f"{tid}/{arm}/edit{i}")
                    lines.append(f"    - `{old}`  ->  `{new}`")
                shown.append(f"  Edit {i}:\n" + "\n".join(lines))
            if arm == "b":
                diags = _all_diags(text)
                tool_out = ("Diagnostics from `sasm check` on the file AFTER "
                            "all four edits:\n" +
                            ("\n".join(diags) if diags else "(clean)"))
            else:
                tool_out = ("The file AFTER all four edits assembles without "
                            "errors (the assembler reports nothing).")
            prompt = (
                f"{PRIMERS[arm]}\n\nA previous engineer applied the four "
                f"edits below to the file, in order. Exactly one of them "
                f"broke this contract: {t['contract']}.\n\n"
                + "\n".join(shown) + f"\n\n{tool_out}\n\n"
                "QUESTION: Which numbered edit (1-4) broke the contract? "
                "Reply with ONLY the number.\n\nORIGINAL FILE (before the "
                "edits):\n" + arms_by_fn[fn][arm]
            )
            cell = f"F3T-{tid}-{arm}"
            _write(RUN / "prompts" / f"{cell}.txt", prompt)
            edited_name = f"arm_{arm}_edited" + (".sasm" if arm == "b" else ".s")
            _write(RUN / "arms" / f"{fn}-{tid}" / edited_name, text)
            manifest[cell] = {"family": "F3T", "function": fn, "trace": tid,
                              "arm": arm, "accept": [t["answer"]]}

    _write(RUN / "manifest.json", json.dumps(manifest, indent=1))
    print(f"gen: {len(manifest)} cells "
          f"({sum(1 for m in manifest.values() if m['family'] == 'F2')} F2, "
          f"{sum(1 for m in manifest.values() if m['family'] == 'F1')} F1, "
          f"{sum(1 for m in manifest.values() if m['family'] == 'F3')} F3, "
          f"{sum(1 for m in manifest.values() if m['family'] == 'F3T')} F3T)")


def build_arms_from_text(src_text):
    tmp = RUN / "_tmp.sasm"
    _write(tmp, src_text)
    try:
        return build_arms(tmp)
    finally:
        tmp.unlink()


# --------------------------------------------------------------------- score

def score():
    """Score every candidate in runs/full/candidates/.

    Candidate filename: <cell>__<tag>.(s|sasm), e.g. F2-fib-t1-b__r1s3.sasm.
    Writes runs/full/scores.json {name: {"pass": bool}} and per-candidate
    feedback text (the Protocol-2 channel) to runs/full/feedback/<name>.txt.
    Arms a/c/d get assembler + qemu output; arm b additionally gets the
    validator's diagnostics (its native build bar, same as the pilot).
    """
    cand_dir = RUN / "candidates"
    fb_dir = RUN / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(_read(RUN / "manifest.json"))
    scores_path = RUN / "scores.json"
    scores = json.loads(_read(scores_path)) if scores_path.exists() else {}

    batch = []   # (name, rel_src, harness) for the docker pass
    for f in sorted(cand_dir.iterdir()):
        name = f.stem
        if name.endswith(".out") or name in scores:
            continue
        cell = name.split("__")[0]
        meta = manifest[cell]
        if meta["arm"] == "b":
            text = _read(f)
            errs, prog = _check_errors(text)
            warns = [d for d in _all_diags(text) if d.startswith("warning")] \
                if prog else []
            if errs:
                _write(fb_dir / f"{name}.txt",
                       "sasm build refused the file:\n" + "\n".join(errs))
                scores[name] = {"pass": False, "stage": "validate"}
                continue
            out_s = cand_dir / f"{name}.out.s"
            _write(out_s, emit(prog))
            note = ("sasm check warnings (not fatal):\n" + "\n".join(warns)
                    + "\n") if warns else ""
            _write(fb_dir / f"{name}.txt", note)  # docker pass appends
            batch.append((name, out_s, meta["harness"]))
        else:
            _write(fb_dir / f"{name}.txt", "")
            batch.append((name, f, meta["harness"]))

    if batch:
        lines = ["set -u"]
        for name, src, harness in batch:
            rel = src.resolve().relative_to(ROOT).as_posix()
            fb = f"/work/benchmarks/runs/full/feedback/{name}.txt"
            lines.append(
                f"if riscv64-linux-gnu-gcc -static -O0 /work/{harness} "
                f"/work/{rel} -o /tmp/cand >>{fb} 2>&1; then "
                f"if timeout 20 qemu-riscv64-static /tmp/cand >>{fb} 2>&1; "
                f"then echo \"{name} PASS\"; else "
                f"echo \"run failed (exit $?)\" >>{fb}; "
                f"echo \"{name} FAIL run\"; fi; else "
                f"echo \"assembler/linker rejected the file\" >>{fb}; "
                f"echo \"{name} FAIL build\"; fi")
        _write(RUN / "batch.sh", "\n".join(lines) + "\n")
        p = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{ROOT.as_posix()}:/work", IMAGE,
             "bash", "/work/benchmarks/runs/full/batch.sh"],
            capture_output=True, text=True, timeout=3600)
        for line in p.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("PASS", "FAIL"):
                scores[parts[0]] = {
                    "pass": parts[1] == "PASS",
                    "stage": parts[2] if len(parts) > 2 else "ok"}
        if p.returncode != 0 and not p.stdout:
            print("docker error:", p.stderr[-2000:])
            sys.exit(1)

    _write(scores_path, json.dumps(scores, indent=1))
    done = [n for n in scores]
    print(f"score: {len(done)} candidates scored, "
          f"{sum(1 for n in done if scores[n]['pass'])} pass")


def missing():
    """List every round-1 (cell, sample) with no candidate/answer on disk —
    the fill list after an interrupted wave."""
    manifest = json.loads(_read(RUN / "manifest.json"))
    out = []
    for cell, m in sorted(manifest.items()):
        if m["family"] in ("F2", "F3"):
            n = 10
            for s in range(1, n + 1):
                if not (RUN / "candidates" / f"{cell}__r1s{s}{m['ext']}").exists():
                    out.append(f"{cell}__r1s{s}")
        else:
            n = 5 if m["family"] == "F1" else 10
            for s in range(1, n + 1):
                if not (RUN / "answers" / f"{cell}__r1s{s}.txt").exists():
                    out.append(f"{cell}__r1s{s}")
    _write(RUN / "missing.json", json.dumps(out, indent=1))
    print(f"missing: {len(out)} round-1 cells unfilled")


def rounds():
    """Generate round-k prompts for every (cell, sample) that failed round
    k-1 (Protocol 2's closed loop). Usage: study.py rounds <k>.

    The feedback channel is each arm's native toolchain output, captured by
    `score` into runs/full/feedback/ — assembler + qemu for arms a/c/d, the
    validator's diagnostics first for arm b. Budget parity: every arm gets
    the same number of rounds and the same prompt shape.
    """
    k = int(sys.argv[2])
    scores = json.loads(_read(RUN / "scores.json"))
    manifest = json.loads(_read(RUN / "manifest.json"))
    made = 0
    for name, sc in scores.items():
        cell, tag = name.split("__")
        if manifest[cell]["family"] not in ("F2", "F3"):
            continue
        rnd, smp = tag[1:].split("s")
        if int(rnd) != k - 1 or sc["pass"]:
            continue
        # already won in an earlier round? (samples stop when they pass)
        prev_won = any(
            scores.get(f"{cell}__r{r}s{smp}", {}).get("pass")
            for r in range(1, k))
        if prev_won:
            continue
        ext = manifest[cell]["ext"]
        attempt = _read(RUN / "candidates" / f"{name}{ext}")
        feedback = _read(RUN / "feedback" / f"{name}.txt").strip() \
            or "(no output captured)"
        base = _read(RUN / "prompts" / f"{cell}.txt")
        prompt = (
            base + f"\n\n--- ATTEMPT {k - 1} FAILED ---\n"
            f"Your previous attempt was:\n{attempt}\n"
            f"Toolchain output for that attempt:\n{feedback}\n\n"
            "Produce a corrected COMPLETE file. Same rules: return the whole "
            "file, no markdown fences, no explanations."
        )
        _write(RUN / "prompts" / f"r{k}" / f"{cell}__r{k}s{smp}.txt", prompt)
        made += 1
    print(f"rounds: {made} round-{k} prompts written")


# ------------------------------------------------------------------- answers

def _norm(s):
    return " ".join(str(s).strip().lower().rstrip(".").split())


def score_answers():
    """Collect runs/full/answers/*.txt and match against ground truth."""
    manifest = json.loads(_read(RUN / "manifest.json"))
    answers = {f.stem: _read(f).strip()
               for f in sorted((RUN / "answers").glob("*.txt"))}
    _write(RUN / "answers.json", json.dumps(answers, indent=1))
    graded = {}
    for name, raw in answers.items():
        cell = name.split("__")[0]
        accept = [_norm(x) for x in manifest[cell]["accept"]]
        got = _norm(raw).replace(",", ", ").replace("  ", " ")
        graded[name] = {"answer": raw,
                        "correct": _norm(got) in accept or _norm(raw) in accept}
    _write(RUN / "graded.json", json.dumps(graded, indent=1))
    ok = sum(1 for g in graded.values() if g["correct"])
    print(f"score-answers: {ok}/{len(graded)} correct")


# -------------------------------------------------------------------- report

def report():
    manifest = json.loads(_read(RUN / "manifest.json"))
    scores = json.loads(_read(RUN / "scores.json")) \
        if (RUN / "scores.json").exists() else {}
    graded = json.loads(_read(RUN / "graded.json")) \
        if (RUN / "graded.json").exists() else {}

    def cellmeta(name): return manifest[name.split("__")[0]]

    # F2/F3: per (function-task, arm): round-1 pass rate (P1) and
    # final pass-by-round (P2), keyed from candidate tags r<k>s<i>.
    from collections import defaultdict
    edits = defaultdict(lambda: defaultdict(dict))  # task -> arm -> sample -> rounds
    for name, sc in scores.items():
        cell = name.split("__")[0]
        m = manifest[cell]
        if m["family"] not in ("F2", "F3"):
            continue
        tag = name.split("__")[1]                  # r<k>s<i>
        rnd, smp = tag[1:].split("s")
        key = f"{m['family']}:{m['function']}:{m.get('task', m.get('corruption'))}"
        edits[key][m["arm"]].setdefault(smp, {})[int(rnd)] = sc["pass"]

    lines = ["# F2/F3 edit results (raw)", "",
             "| cell | arm | n | P1 pass (r1) | P2 pass (<=4 rounds) | "
             "mean rounds-to-success |", "|---|---|---|---|---|---|"]
    for key in sorted(edits):
        for arm in "acdb":
            if arm not in edits[key]:
                continue
            samples = edits[key][arm]
            n = len(samples)
            p1 = sum(1 for s in samples.values() if s.get(1))
            p2ok, rds = 0, []
            for s in samples.values():
                won = [r for r, ok in sorted(s.items()) if ok]
                if won:
                    p2ok += 1
                    rds.append(won[0])
            mean_r = f"{sum(rds)/len(rds):.2f}" if rds else "-"
            lines.append(f"| {key} | {arm} | {n} | {p1}/{n} | {p2ok}/{n} | "
                         f"{mean_r} |")

    qs = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for name, g in graded.items():
        m = cellmeta(name)
        key = f"{m['family']}:{m['function']}:{m.get('question', m.get('trace'))}"
        qs[key][m["arm"]][0] += g["correct"]
        qs[key][m["arm"]][1] += 1
    lines += ["", "# F1/F3T answer accuracy (raw)", "",
              "| cell | " + " | ".join("acdb") + " |", "|---|---|---|---|---|"]
    for key in sorted(qs):
        row = [f"| {key} "]
        for arm in "acdb":
            c, t = qs[key][arm]
            row.append(f"| {c}/{t} " if t else "| - ")
        lines.append("".join(row) + "|")

    _write(RUN / "raw_tables.md", "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    {"gen": gen, "score": score, "score-answers": score_answers,
     "rounds": rounds, "missing": missing, "report": report}[sys.argv[1]]()
