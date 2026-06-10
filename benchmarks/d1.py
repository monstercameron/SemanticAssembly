"""D1 — the premise benchmark harness (DESIGN §16.1).

Generates the four arms from one source of truth and scores candidate edits
with one behavioral oracle, so every arm carries the SAME information and
faces the SAME bar:

  arm a: raw .s
  arm c: .s + a prose fact block at the top (same facts, non-local, unstructured)
  arm d: .s + per-instruction fact comments (same facts, LOCAL, unstructured,
         unaddressable, unchecked) — the critical control
  arm b: the .sasm itself (local, addressable, checked)

Arms c and d are DERIVED MECHANICALLY from the .sasm so the same-information
claim is provable, not asserted. The oracle: the edited artifact must reach
its native build bar (assemble for a/c/d; `sasm build` — which validates — for
b), then run green under qemu against the example's harness.

Usage:
  python benchmarks/d1.py arms <example.sasm> <outdir>   # write a/c/d/b files
  python benchmarks/d1.py score <arm> <file> <harness.c> # oracle; exit 0=pass
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sasm.emit import emit                    # noqa: E402
from sasm.parser import parse                 # noqa: E402
from sasm.validate import validate            # noqa: E402

IMAGE = "sasm-riscv-test"


# ------------------------------------------------------------ arm generation

def _insn_lines(prog):
    """(handle -> facts) in exactly the emitter's line order, so per-line
    comments can be attached mechanically (π is 1:1 with statements)."""
    out = []
    for fn in prog.of_type("function"):
        blocks = prog.members_of(fn.name, "block")
        blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
        for b in blocks:
            for i in prog.members_of(b.name, "insn"):
                out.append(i)
    return out

def _facts_comment(i):
    bits = []
    for pred in ("reads", "writes", "returns"):
        for r in i.all(pred):
            if r:
                bits.append(f"{pred} {r[0]}")
    for r in i.all("liveOut"):
        if r:
            bits.append(f"liveOut {r[0]}")
    for r in i.all("saves"):
        bits.append(f"saves {' '.join(r)}")
    for r in i.all("restores"):
        bits.append(f"restores {' '.join(r)}")
    p = i.scalar("purpose") or i.scalar("condition")
    if p:
        bits.append(p)
    return "; ".join(bits)

def _prose_block(prog):
    """The same facts as English at the top of the file (arm c)."""
    lines = ["# FACTS (same information as the semantic source, in prose):"]
    for fn in prog.of_type("function"):
        lines.append(f"# function {fn.scalar('symbol')}:")
        for row in fn.all("in"):
            lines.append(f"#   argument {row[0]} ({row[1]}) arrives in {row[2]}")
        for row in fn.all("out"):
            lines.append(f"#   result {row[0]} ({row[1]}) leaves in {row[2]}")
        st = next((r[1] for r in fn.all("stack") if r and r[0] == "bytes"), None)
        if st:
            lines.append(f"#   stack frame: {st} bytes, 16-byte aligned")
        for r in fn.all("preserves"):
            lines.append(f"#   callee-saved {r[0]} must be restored on return")
    for s in prog.of_type("stackSlot"):
        lines.append(f"#   slot {s.name}: offset {s.scalar('offset')} from sp, "
                     f"holds saved {s.scalar('stores')}")
    for v in prog.of_type("value"):
        m = v.scalar("meaning")
        if m:
            lines.append(f"#   value {v.name}: {m}")
    for fn in prog.of_type("function"):
        for b in prog.members_of(fn.name, "block"):
            for i in prog.members_of(b.name, "insn"):
                for r in i.all("liveOut"):
                    if r and ":" in r[0]:
                        reg, val = r[0].split(":", 1)
                        lines.append(f"#   across the call at `{i.scalar('symbol') or i.name}`: "
                                     f"{val} must survive in {reg}")
    lines.append("#")
    return "\n".join(lines)

def build_arms(sasm_path: pathlib.Path) -> dict[str, str]:
    src = sasm_path.read_text(encoding="utf-8")
    prog = parse(src)
    s_text = emit(prog)
    arms = {"a": s_text, "b": src}
    arms["c"] = _prose_block(prog) + "\n" + s_text
    # arm d: attach each insn's facts to its emitted line, in order
    insns = _insn_lines(parse(src))
    out, k = [], 0
    for line in s_text.splitlines():
        bare = line.strip()
        is_stmt = line.startswith("\t") and not bare.startswith(".")
        if is_stmt and k < len(insns):
            c = _facts_comment(insns[k])
            out.append(f"{line}\t# {c}" if c else line)
            k += 1
        else:
            out.append(line)
    arms["d"] = "\n".join(out) + "\n"
    return arms


# ------------------------------------------------------------------- oracle

def _docker_run_s(s_path: pathlib.Path, harness: str) -> tuple[bool, str]:
    rel = s_path.resolve().relative_to(ROOT).as_posix()
    cmd = ["docker", "run", "--rm", "-v", f"{ROOT.as_posix()}:/work", IMAGE,
           "bash", "-c",
           f"riscv64-linux-gnu-gcc -static -O0 /work/{harness} /work/{rel} "
           f"-o /tmp/cand 2>&1 && qemu-riscv64-static /tmp/cand"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)[-800:]

def score(arm: str, path: pathlib.Path, harness: str) -> tuple[bool, str]:
    """Native build bar + behavioral oracle. Returns (passed, detail)."""
    if arm == "b":
        try:
            prog = parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            return False, f"parse error: {e}"
        errs = [d for d in validate(prog) if d.severity == "error"]
        if errs:
            return False, "; ".join(str(d) for d in errs[:4])
        s_path = path.with_suffix(".out.s")
        s_path.write_text(emit(prog), encoding="utf-8", newline="\n")
        return _docker_run_s(s_path, harness)
    return _docker_run_s(path, harness)


if __name__ == "__main__":
    if sys.argv[1] == "arms":
        outdir = pathlib.Path(sys.argv[3]); outdir.mkdir(parents=True, exist_ok=True)
        for arm, text in build_arms(pathlib.Path(sys.argv[2])).items():
            ext = ".sasm" if arm == "b" else ".s"
            (outdir / f"arm_{arm}{ext}").write_text(text, encoding="utf-8",
                                                    newline="\n")
        print("arms written to", outdir)
    elif sys.argv[1] == "score":
        ok, detail = score(sys.argv[2], pathlib.Path(sys.argv[3]), sys.argv[4])
        print("PASS" if ok else "FAIL", "—", detail.strip()[:300])
        sys.exit(0 if ok else 1)
