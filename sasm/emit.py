"""π : .sasm → .s  — the lossy projection (DESIGN §15).

Reads ONLY authoritative facts and templates them. No analysis, no rewriting.
Deterministic: identical input → byte-identical output.

Emission rules (pinned against the golden examples, DESIGN §15):
  - file begins with `\t.text` when there are functions (data sections precede it)
  - global function:  `\t.globl\t<symbol>` then `<symbol>:`
  - blocks emit in source order, entry block first; a non-entry block gets a
    label `.L<lowercased-handle>:` iff some instruction targets it
  - an instruction line is `\t<mnemonic>\t<operands>` (tab after the mnemonic,
    `, ` between operands — both already baked into the op `emit` template, whose
    first space we convert to a tab); operand-less ops are just `\t<mnemonic>`
  - register fields map through regs.tsv (returnAddress -> ra); an `offset` that
    names a stackSlot resolves to that slot's numeric offset; a `target` resolves
    to the destination block's label
"""

from __future__ import annotations

import string

from . import isa
from .model import Entity, Program

_FORMATTER = string.Formatter()


class EmitError(Exception):
    pass


def _label_of(block_name: str) -> str:
    return ".L" + block_name.lower()


def _blocks_of(prog: Program, fn: Entity) -> list[Entity]:
    blocks = prog.members_of(fn.name, "block")
    # entry block first, then source order
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    return blocks


def _insns_of(prog: Program, block: Entity) -> list[Entity]:
    """Instructions in execution order: by `ordinal` if the block uses them
    (all-or-nothing per block, DESIGN §11.1; validator enforces E-ORDER-MIXED),
    otherwise source order."""
    insns = prog.members_of(block.name, "insn")
    if insns and all(i.scalar("ordinal") is not None for i in insns):
        return sorted(insns, key=lambda i: int(i.scalar("ordinal")))
    return insns


def _resolve_field(prog: Program, insn: Entity, reg_asm: dict, field: str) -> str:
    if field in isa.REGISTER_FIELDS:
        reg = insn.scalar(field)
        return reg_asm.get(reg, reg)
    if field == "offset":
        off = insn.scalar("offset")
        slot = prog.get(off) if off else None
        if slot is not None and slot.type == "stackSlot":
            return slot.scalar("offset")
        return off
    if field == "target":
        return _label_of(insn.scalar("target"))
    # immediate, symbol, anything else: verbatim
    return insn.scalar(field)


def _emit_insn(prog: Program, insn: Entity, ops: dict, reg_asm: dict) -> str:
    sem = insn.scalar("operation")
    if sem not in ops:
        raise EmitError(f"{insn.name}: unknown operation {sem!r}")
    template = ops[sem]["emit"]
    fields = {name for _, name, _, _ in _FORMATTER.parse(template) if name}
    filled = template.format(
        **{f: _resolve_field(prog, insn, reg_asm, f) for f in fields}
    )
    mnemonic, sep, rest = filled.partition(" ")
    return f"\t{mnemonic}\t{rest}" if sep else f"\t{mnemonic}"


# scalar data type -> GAS directive (RISC-V widths)
_DATA_DIRECTIVE = {
    "Int8": ".byte", "Nat8": ".byte", "Boolean": ".byte",
    "Int16": ".half", "Nat16": ".half",
    "Int32": ".word", "Nat32": ".word",
    "Int64": ".dword", "Nat64": ".dword", "Address": ".dword",
}


def _emit_data(prog: Program, lines: list[str]) -> None:
    order = ["rodata", "data", "bss"]
    data = prog.of_type("data")
    by_section: dict[str, list[Entity]] = {}
    for d in data:
        by_section.setdefault(d.scalar("section", "data"), []).append(d)
    for section in order + [s for s in by_section if s not in order]:
        if section not in by_section:
            continue
        lines.append(f"\t.section .{section}")
        for d in by_section[section]:
            binding = d.scalar("binding")
            if binding == "global":
                lines.append(f"\t.globl\t{d.name}")
            elif binding == "weak":
                lines.append(f"\t.weak\t{d.name}")
            align = d.scalar("align")
            if align:
                lines.append(f"\t.balign {align}")          # n bytes (unambiguous)
            lines.append(f"{d.name}:")
            typ, val, size = d.scalar("type"), d.scalar("value"), d.scalar("size")
            if val is None:                                  # uninitialized (bss): reserve
                lines.append(f"\t.zero {size}")
            elif typ == "Bytes":
                lines.append(f'\t.ascii "{val}"')
            else:
                lines.append(f"\t{_DATA_DIRECTIVE.get(typ, '.dword')} {val}")
            if size is not None and val is not None:
                lines.append(f"\t.size\t{d.name}, {size}")


def _type_directive(name: str, symbol_type: str) -> str:
    kind = "function" if symbol_type == "func" else "object"
    return f"\t.type\t{name}, @{kind}"


def _emit_symbols(prog: Program, lines: list[str]) -> None:
    """Linker directives for `symbol` entities (external refs / weak / typed)."""
    for s in prog.of_type("symbol"):
        binding = s.scalar("binding")
        if binding == "weak":
            lines.append(f"\t.weak\t{s.name}")
        elif binding == "global":
            lines.append(f"\t.globl\t{s.name}")
        st = s.scalar("symbolType")
        if st:
            lines.append(_type_directive(s.name, st))


def emit(prog: Program) -> str:
    """Project a parsed Program to RISC-V assembly text."""
    ops = isa.load_ops()
    reg_asm = isa.load_reg_asm()
    lines: list[str] = []

    _emit_symbols(prog, lines)
    _emit_data(prog, lines)

    funcs = prog.of_type("function")
    if funcs:
        lines.append("\t.text")
    for fn in funcs:
        symbol = fn.scalar("symbol", fn.name)
        binding = fn.scalar("binding")
        if binding == "weak":
            lines.append(f"\t.weak\t{symbol}")
        elif binding == "global" or fn.scalar("visibility") == "global":
            lines.append(f"\t.globl\t{symbol}")
        if fn.scalar("symbolType"):
            lines.append(_type_directive(symbol, fn.scalar("symbolType")))
        lines.append(f"{symbol}:")

        blocks = _blocks_of(prog, fn)
        targets = {
            t
            for b in blocks
            for insn in prog.members_of(b.name, "insn")
            if (t := insn.scalar("target"))
        }
        for b in blocks:
            if b.scalar("entry") != "yes" and b.name in targets:
                lines.append(f"{_label_of(b.name)}:")
            for insn in _insns_of(prog, b):
                lines.append(_emit_insn(prog, insn, ops, reg_asm))

    return "\n".join(lines) + "\n"
