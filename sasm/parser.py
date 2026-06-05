"""Parse .sasm text into a Program.

Grammar (one fact per line):
    <subject> is <Type>
    <subject> <predicate> <arg> <arg> ...

  - `#` starts a comment (to end of line)
  - double-quoted tokens preserve spaces and are taken verbatim (no escape
    processing -- so "Hello\n" keeps the literal backslash-n for the assembler)
  - blank lines ignored
"""

from __future__ import annotations

from .model import Program


def tokenize(line: str) -> list[str]:
    toks: list[str] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "#":
            break
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and line[j] != '"':
                buf.append(line[j])
                j += 1
            toks.append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and not line[j].isspace() and line[j] != "#":
                j += 1
            toks.append(line[i:j])
            i = j
    return toks


class ParseError(SyntaxError):
    pass


def parse(text: str) -> Program:
    prog = Program()
    for lineno, raw in enumerate(text.splitlines(), 1):
        toks = tokenize(raw)
        if not toks:
            continue
        if len(toks) < 2:
            raise ParseError(f"line {lineno}: a fact needs a subject and a predicate: {raw.strip()!r}")
        subj, pred, args = toks[0], toks[1], toks[2:]
        ent = prog.ensure(subj)
        if not ent.lineno:
            ent.lineno = lineno
        if pred == "is":
            if not args:
                raise ParseError(f"line {lineno}: `{subj} is` needs a type")
            ent.type = args[0]
        else:
            ent.add(pred, args)
    return prog
