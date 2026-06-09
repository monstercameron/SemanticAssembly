"""Load the TSV data tables and expose them to the toolchain.

The tables are the single source of truth (DESIGN §7.2, OPCODES.md). This module
turns them into plain dicts; it carries no logic beyond parsing.
"""

from __future__ import annotations

import csv
import os

_DIR = os.path.dirname(__file__)


def _rows(name: str) -> list[dict]:
    with open(os.path.join(_DIR, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _list(field: str) -> list[str]:
    return [x for x in field.split(",") if x and x != "-"]


def load_ops() -> dict[str, dict]:
    """semantic name -> spec row, with `defines`/`uses` split into lists."""
    ops = {}
    for r in _rows("optable.tsv"):
        r["defines"] = _list(r["defines"])
        r["uses"] = _list(r["uses"])
        ops[r["sem"]] = r
    return ops


def load_reg_asm() -> dict[str, str]:
    """canonical register name -> assembler mnemonic (returnAddress -> ra)."""
    return {r["reg"]: r["asm"] for r in _rows("regs.tsv")}


def reg_names() -> set[str]:
    """the set of valid canonical register names (what .sasm facts use)."""
    return {r["reg"] for r in _rows("regs.tsv")}


def load_formats() -> dict[str, dict]:
    """encoding format -> row (immediate ranges, alignment)."""
    return {r["fmt"]: r for r in _rows("formats.tsv")}


def load_syscalls() -> dict[str, dict]:
    """syscall name -> row. A row whose `return` is '-' never returns (exit)."""
    return {r["name"]: r for r in _rows("syscalls.tsv")}


def load_abi() -> dict[str, dict[str, list[str]]]:
    """abi name -> {property -> [values]}."""
    out: dict[str, dict[str, list[str]]] = {}
    for r in _rows("abi.tsv"):
        out.setdefault(r["abi"], {})[r["property"]] = r["value"].split()
    return out


# register-valued operand fields (these get mapped through reg->asm at emit)
REGISTER_FIELDS = frozenset(
    {"destination", "firstSource", "secondSource", "thirdSource", "base"}
)
