"""`sasm fmt` — canonical formatter (DESIGN §11.1).

Re-serializes a parsed Program to one deterministic `.sasm` layout:

  - entities in source order; a blank line between them
  - `<name> is <Type>` first (when typed), then the entity's facts grouped by
    predicate (first-appearance order), preserving row order within a predicate
  - an argument is quoted iff it contains whitespace or is empty (so `purpose`
    strings round-trip; bare tokens stay bare)

Properties (verified by tests/fmt_test.py):
  - **idempotent**: format(parse(format(x))) == format(parse(x))
  - **semantics-preserving**: emit(parse(format(x))) == emit(parse(x))

It does not reorder facts within a predicate, and it never changes the emitted
`.s`. It is intentionally not a pretty-printer with alignment — just a stable,
diff-friendly normal form.
"""

from __future__ import annotations

from .model import Program


def _render_arg(arg: str) -> str:
    if arg == "" or any(c.isspace() for c in arg):
        return f'"{arg}"'
    return arg


def format_program(prog: Program) -> str:
    blocks: list[str] = []
    for name in prog.order:
        ent = prog.entities[name]
        lines: list[str] = []
        if ent.type is not None:
            lines.append(f"{name} is {ent.type}")
        for pred, rows in ent.facts.items():
            for row in rows:
                rendered = " ".join(_render_arg(a) for a in row)
                lines.append(f"{name} {pred} {rendered}".rstrip())
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
