"""Generator: parse the official riscv/riscv-opcodes extension files into
candidate `optable.tsv` rows, and cross-check coverage against the hand-curated
table (DESIGN §7.2, TODOS B1).

This first step proves the generator parses upstream correctly and aligns with
our ground-truth Tier-A table. It does NOT replace `sasm/optable.tsv` yet —
semantic names, op-specific immediate/`base` mapping, effects, and control kind
are curated overrides that land in later B sub-steps.

Usage:
    python gen/generate.py [path-to-riscv-opcodes]   # default: gen/riscv-opcodes
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Extension files that cover our current Tier-A set.
DEFAULT_EXTS = [
    "rv_i", "rv64_i", "rv_m", "rv64_m", "rv_zicond",
    "rv_a", "rv64_a",            # atomics: rv_a is the .w set, rv64_a adds .d + lr.d/sc.d
    "rv_zacas", "rv64_zacas",    # amocas (compare-and-swap)
]

# riscv-opcodes operand token -> our semantic operand field (best-effort; the
# op-specific base/offset/target remap is a curated override, see notes).
ARG_FIELD = {
    "rd": "destination",
    "rs1": "firstSource",
    "rs2": "secondSource",
    "rs3": "thirdSource",
    "imm12": "immediate", "imm20": "immediate",
    "shamt": "immediate", "shamtw": "immediate",
    "zimm": "immediate",
    "jimm20": "target",
    "bimm12hi": "target", "bimm12lo": "target",
    "imm12hi": "offset", "imm12lo": "offset",
}


def _is_constraint(tok: str) -> bool:
    return "=" in tok


def _major_opcode(toks: list[str]) -> int | None:
    """The RISC-V major opcode, from the `6..2=0xNN` encoding constraint."""
    for t in toks:
        if t.startswith("6..2="):
            return int(t.split("=", 1)[1], 0)
    return None


def parse_extension(path: str) -> list[tuple[str, list[str], int | None]]:
    ops = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("$"):  # skip blanks, comments, $import/$pseudo_op
                continue
            toks = line.split()
            mnemonic = toks[0]
            operands = [t for t in toks[1:] if not _is_constraint(t)]
            ops.append((mnemonic, operands, _major_opcode(toks)))
    return ops


# major opcode (6..2) -> structural class. Drives defines/uses/effect/control,
# faithfully reproducing the hand-curated columns from the upstream encoding.
_OPCODES = {
    0x00: "LOAD", 0x04: "OPIMM", 0x05: "AUIPC", 0x06: "OPIMM",
    0x08: "STORE", 0x0B: "AMO", 0x0C: "OP", 0x0D: "LUI", 0x0E: "OP",
    0x18: "BRANCH", 0x19: "JALR", 0x1B: "JAL", 0x1C: "SYSTEM", 0x03: "MISCMEM",
}


def derive(mnemonic: str, operands: list[str], opcode: int | None) -> dict:
    """Derive (defines, uses, effect, control) from the major opcode + operands."""
    klass = _OPCODES.get(opcode)
    has = lambda x: x in operands
    d, u, eff, ctl = set(), set(), "none", "seq"
    if klass == "LOAD":
        d, u, eff = {"destination"}, {"base"}, "memory.read"
    elif klass == "STORE":
        u, eff = {"secondSource", "base"}, "memory.write"
    elif klass in ("OP",):
        d, u = {"destination"}, {"firstSource", "secondSource"}
    elif klass == "OPIMM":
        d, u = {"destination"}, {"firstSource"}
    elif klass in ("LUI", "AUIPC"):
        d = {"destination"}
    elif klass == "BRANCH":
        u, ctl = {"firstSource", "secondSource"}, "branch"
    elif klass == "JAL":
        d, ctl = {"destination"}, "call"
    elif klass == "JALR":
        d, u, ctl = {"destination"}, {"firstSource"}, "call"
    elif klass == "AMO":
        d = {"destination"}
        u = {"base"} | ({"secondSource"} if has("rs2") else set())
        eff = "memory.read" if mnemonic.startswith("lr") else "memory.write"
    elif klass == "SYSTEM":
        eff, ctl = ("syscall", "syscall") if mnemonic == "ecall" else (
            ("trap", "seq") if mnemonic == "ebreak" else ("csr.write", "seq"))
    elif klass == "MISCMEM":
        eff = "fence"
    return {"defines": d, "uses": u, "effect": eff, "control": ctl}


def fields_of(operands: list[str]) -> set[str]:
    return {ARG_FIELD[o] for o in operands if o in ARG_FIELD}


def load_upstream(base: str, exts=DEFAULT_EXTS) -> dict[str, tuple[list[str], int | None]]:
    out: dict[str, tuple[list[str], int | None]] = {}
    for ext in exts:
        p = os.path.join(base, "extensions", ext)
        if not os.path.exists(p):
            continue
        for mnemonic, operands, opcode in parse_extension(p):
            out[mnemonic] = (operands, opcode)
    return out


def _hand_rows() -> dict[str, dict]:
    """mnemonic -> {defines:set, uses:set, effect, control} from the hand table."""
    lines = open(os.path.join(ROOT, "sasm", "optable.tsv"), encoding="utf-8").read().splitlines()
    cols = lines[0].split("\t")
    out = {}
    for ln in lines[1:]:
        if not ln:
            continue
        r = dict(zip(cols, ln.split("\t")))
        out[r["mnemonic"]] = {
            "defines": {x for x in r["defines"].split(",") if x and x != "-"},
            "uses": {x for x in r["uses"].split(",") if x and x != "-"},
            "effect": r["effect"], "control": r["control"],
        }
    return out


def hand_mnemonics() -> set[str]:
    return set(_hand_rows())


def fidelity(upstream: dict) -> tuple[int, int, list[str]]:
    """Compare derived structural columns to the hand table for overlapping,
    encoding-bearing ops. Returns (matched, total, mismatches)."""
    hand = _hand_rows()
    matched, total, bad = 0, 0, []
    for m, row in hand.items():
        if m not in upstream:
            continue
        operands, opcode = upstream[m]
        if opcode is None:
            continue
        total += 1
        got = derive(m, operands, opcode)
        if (got["defines"], got["uses"], got["effect"], got["control"]) == (
            row["defines"], row["uses"], row["effect"], row["control"]):
            matched += 1
        else:
            bad.append(f"{m}: derived {got} vs hand {row}")
    return matched, total, bad


def main(argv=None):
    argv = argv or sys.argv[1:]
    base = argv[0] if argv else os.path.join(HERE, "riscv-opcodes")
    if not os.path.isdir(base):
        print(f"riscv-opcodes not found at {base}; clone it first "
              f"(git clone --depth 1 https://github.com/riscv/riscv-opcodes {base})",
              file=sys.stderr)
        return 2

    upstream = load_upstream(base)
    print(f"parsed {len(upstream)} instructions from {', '.join(DEFAULT_EXTS)}")

    # write candidate rows (starting point for curation; not authoritative)
    out_path = os.path.join(HERE, "generated_optable.tsv")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("mnemonic\topcode\tdefines\tuses\teffect\tcontrol\toperands\n")
        for m in sorted(upstream):
            ops, opcode = upstream[m]
            der = derive(m, ops, opcode)
            oc = f"0x{opcode:02x}" if opcode is not None else "-"
            f.write(f"{m}\t{oc}\t{','.join(sorted(der['defines'])) or '-'}\t"
                    f"{','.join(sorted(der['uses'])) or '-'}\t{der['effect']}\t"
                    f"{der['control']}\t{' '.join(ops)}\n")
    print(f"wrote candidate rows -> {os.path.relpath(out_path, ROOT)}")

    # fidelity: do the derived structural columns reproduce the hand table?
    matched, total, bad = fidelity(upstream)
    print(f"structural fidelity vs hand table: {matched}/{total} overlapping ops match")
    for b in bad:
        print("  MISMATCH", b)

    # coverage cross-check vs the hand-curated table
    hand = hand_mnemonics()
    PSEUDO = {"li", "la", "mv", "nop", "j", "jr", "call", "tail", "ret",
              "beqz", "bnez"}                       # not in extension files
    real_hand = hand - PSEUDO
    missing = sorted(m for m in real_hand if m not in upstream)
    covered = len(real_hand) - len(missing)
    print(f"hand table: {len(hand)} ops ({len(PSEUDO)} pseudos); "
          f"{covered}/{len(real_hand)} real ops confirmed upstream")
    if missing:
        print("  NOT found upstream (check):", ", ".join(missing))
    not_yet = sorted(m for m in upstream if m not in hand)
    print(f"upstream ops not yet in hand table (future breadth): {len(not_yet)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
