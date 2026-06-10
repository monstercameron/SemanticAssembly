"""Mutation tier (DESIGN §19): fuzz the VERIFIER, not the program.

For every generated mutation of a known-good example, the safety stack must
hold the invariant:

    a behavior-changing mutation is caught by `validate` (static), or by the
    taint interpreter's vectors (dynamic), or it emitted byte-identical `.s`
    (provably equivalent). A mutant that passes everything while changing the
    emitted code is a HOLE — a measured gap in the verifier.

Holes are not hidden: they go into ALLOWED_HOLES with a written reason, and the
test fails on any hole not in that list. The allowlist is the verifier's known
blind-spot ledger; shrinking it is verifier work (TODOS H).
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.emit import EmitError, emit            # noqa: E402
from sasm.interp import ExecError, Machine       # noqa: E402
from sasm.parser import ParseError, parse        # noqa: E402
from sasm.validate import validate               # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- vectors

_STEPS = 100_000   # generous (fib(10) needs ~2.7k); runaway mutants hit it fast


def _vectors_fib(m: Machine) -> bool:
    return m.call("fib", [10], max_steps=_STEPS) == 55 \
        and m.call("fib", [1], max_steps=_STEPS) == 1 \
        and m.call("fib", [0], max_steps=_STEPS) == 0


def _vectors_sum(m: Machine) -> bool:
    base = m.alloc_int64_array([1, 2, 3, 4, 5])
    return m.call("sum_array", [base, 5], max_steps=_STEPS) == 15 \
        and m.call("sum_array", [base, 0], max_steps=_STEPS) == 0


def _vectors_ack(m: Machine) -> bool:
    return m.call("ack", [2, 3], max_steps=_STEPS) == 9 \
        and m.call("ack", [1, 0], max_steps=_STEPS) == 2


TARGETS = [
    ("examples/brainworms_fib/fib.sasm", _vectors_fib),
    ("examples/challenging_sum_array/sum_array.sasm", _vectors_sum),
    ("examples/gauntlet_ackermann/ackermann.sasm", _vectors_ack),
]

# (file, operator, detail) -> reason the hole is tolerated, for now
ALLOWED_HOLES: dict[tuple, str] = {
}


# ---------------------------------------------------------------- operators

def _mutations(src: str):
    """Yield (operator, detail, mutated_text)."""
    lines = src.splitlines()

    for i, l in enumerate(lines):
        m = re.match(r"^(\w+) immediate (-?\d+)$", l)
        if m:
            new = lines.copy()
            new[i] = f"{m.group(1)} immediate {int(m.group(2)) + 8}"
            yield ("imm+8", m.group(1), "\n".join(new) + "\n")

        m = re.match(r"^(\w+) offset (\d+)$", l)
        if m:
            new = lines.copy()
            new[i] = f"{m.group(1)} offset {int(m.group(2)) + 8}"
            yield ("offset+8", m.group(1), "\n".join(new) + "\n")

        m = re.match(r"^(\w+) target (\w+)$", l)
        if m:
            blocks = {b for b in re.findall(r"^(\w+) is block$", src, re.M)}
            for other in sorted(blocks - {m.group(2)}):
                new = lines.copy()
                new[i] = f"{m.group(1)} target {other}"
                yield ("retarget", f"{m.group(1)}->{other}", "\n".join(new) + "\n")

    # swap firstSource/secondSource on every insn that has both — except on
    # commutative ops, where the swap is semantically equivalent (not a bug,
    # just different bytes; uninteresting as a mutant)
    commutative = {"Add", "And", "Or", "ExclusiveOr", "Multiply", "AddWord",
                   "MultiplyWord", "BranchEqual", "BranchNotEqual"}
    op_of = dict(re.findall(r"^(\w+) operation (\w+)$", src, re.M))
    subjects = {}
    for l in lines:
        m = re.match(r"^(\w+) (firstSource|secondSource) (\S+)$", l)
        if m:
            subjects.setdefault(m.group(1), {})[m.group(2)] = m.group(3)
    for subj, fields in subjects.items():
        if op_of.get(subj) in commutative:
            continue
        if len(fields) == 2 and fields["firstSource"] != fields["secondSource"]:
            new = []
            for l in lines:
                if l == f"{subj} firstSource {fields['firstSource']}":
                    new.append(f"{subj} firstSource {fields['secondSource']}")
                elif l == f"{subj} secondSource {fields['secondSource']}":
                    new.append(f"{subj} secondSource {fields['firstSource']}")
                else:
                    new.append(l)
            yield ("swap-operands", subj, "\n".join(new) + "\n")

    # delete every save/restore instruction wholesale (all its rows)
    for subj in re.findall(r"^(\w+) (?:saves|restores) ", src, re.M):
        new = [l for l in lines if not l.startswith(subj + " ")]
        yield ("delete-insn", subj, "\n".join(new) + "\n")


# ---------------------------------------------------------------- the tier

def _classify(rel: str, vectors, text: str, golden_s: str) -> str:
    try:
        prog = parse(text)
    except ParseError:
        return "caught-parse"
    if any(d.severity == "error" for d in validate(prog)):
        return "caught-static"
    try:
        mutated_s = emit(prog)
    except EmitError:
        return "caught-emit"
    if mutated_s == golden_s:
        return "equivalent"
    try:
        m = Machine(prog)
        ok = vectors(m)
    except (ExecError, KeyError, RecursionError):
        return "caught-dynamic"
    if not ok or any(d.severity == "error" for d in m.diags):
        return "caught-dynamic"
    return "HOLE"


def test_mutation_tier():
    holes, stats = [], {}
    for rel, vectors in TARGETS:
        src = (ROOT / rel).read_text(encoding="utf-8")
        golden_s = emit(parse(src))
        for op, detail, text in _mutations(src):
            verdict = _classify(rel, vectors, text, golden_s)
            stats[verdict] = stats.get(verdict, 0) + 1
            if verdict == "HOLE" and (rel, op, detail) not in ALLOWED_HOLES:
                holes.append((rel, op, detail))
    print("mutation tier:", stats)
    assert not holes, f"verifier holes found (catch them or allowlist with a reason): {holes}"


if __name__ == "__main__":
    test_mutation_tier()
    print("mutation tier: PASS")
