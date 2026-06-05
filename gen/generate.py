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


def parse_extension(path: str) -> list[tuple[str, list[str]]]:
    ops = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("$"):  # skip blanks, comments, $import/$pseudo_op
                continue
            toks = line.split()
            mnemonic = toks[0]
            operands = [t for t in toks[1:] if not _is_constraint(t)]
            ops.append((mnemonic, operands))
    return ops


def fields_of(operands: list[str]) -> set[str]:
    return {ARG_FIELD[o] for o in operands if o in ARG_FIELD}


def load_upstream(base: str, exts=DEFAULT_EXTS) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ext in exts:
        p = os.path.join(base, "extensions", ext)
        if not os.path.exists(p):
            continue
        for mnemonic, operands in parse_extension(p):
            out[mnemonic] = operands
    return out


def hand_mnemonics() -> set[str]:
    rows = open(os.path.join(ROOT, "sasm", "optable.tsv"), encoding="utf-8").read().splitlines()
    return {ln.split("\t")[1] for ln in rows[1:] if ln}


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
        f.write("mnemonic\toperands\tcandidate_fields\n")
        for m in sorted(upstream):
            ops = upstream[m]
            f.write(f"{m}\t{' '.join(ops)}\t{','.join(sorted(fields_of(ops)))}\n")
    print(f"wrote candidate rows -> {os.path.relpath(out_path, ROOT)}")

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
