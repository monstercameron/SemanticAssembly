"""Parse .sasm text into a Program.

Grammar (one fact per line):
    <subject> is <Type>
    <subject> <predicate> <arg> <arg> ...

  - `#` starts a comment (to end of line)
  - double-quoted tokens preserve spaces and are taken verbatim (no escape
    processing -- so "Hello\n" keeps the literal backslash-n for the assembler)
  - blank lines ignored
  - compact pipe sugar (LANGUAGE §20): `<subject> <pred> <args> | <pred> <args>
    | ...` is exactly equivalent to repeating the subject on each clause. It
    parses to identical facts -- pure surface sugar.
"""

from __future__ import annotations

import re

from .model import Program

# subjects and predicates are bare identifiers (LANGUAGE casing rules) — a
# quoted token like "a b" must not silently become an entity name that the
# formatter later re-renders bare and re-parses as something else
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


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
        if c == "|":                     # clause separator (pipe sugar)
            toks.append("|")
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and line[j] != '"':
                buf.append(line[j])
                j += 1
            if j >= n:
                raise ParseError(f"unterminated string: {line.strip()!r}")
            toks.append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and not line[j].isspace() and line[j] not in "#|":
                j += 1
            toks.append(line[i:j])
            i = j
    return toks


class ParseError(SyntaxError):
    pass


def _split_clauses(toks: list[str]) -> list[list[str]]:
    """Split a token list on `|` into clauses (pipe sugar)."""
    clauses: list[list[str]] = [[]]
    for t in toks:
        if t == "|":
            clauses.append([])
        else:
            clauses[-1].append(t)
    return clauses


def parse(text: str) -> Program:
    prog = Program()
    for lineno, raw in enumerate(text.splitlines(), 1):
        toks = tokenize(raw)
        if not toks:
            continue

        clauses = _split_clauses(toks)
        # first clause carries the subject; subsequent clauses reuse it
        head = clauses[0]
        if len(head) < 2:
            raise ParseError(
                f"line {lineno}: a fact needs a subject and a predicate: {raw.strip()!r}")
        subj = head[0]
        if not _IDENT.match(subj):
            raise ParseError(
                f"line {lineno}: subject {subj!r} is not a bare identifier")
        ent = prog.ensure(subj)
        if not ent.lineno:
            ent.lineno = lineno

        def apply(pred: str, args: list[str]) -> None:
            if not _IDENT.match(pred):
                raise ParseError(
                    f"line {lineno}: predicate {pred!r} is not a bare identifier")
            if pred == "is":
                if len(args) != 1:
                    raise ParseError(
                        f"line {lineno}: `{subj} is` takes exactly one type, "
                        f"got {args!r}")
                if ent.type is not None:
                    raise ParseError(
                        f"line {lineno}: {subj} is already declared "
                        f"`is {ent.type}` — an entity has exactly one type "
                        f"(E-DUP)")
                ent.type = args[0]
            else:
                ent.add(pred, args)

        apply(head[1], head[2:])
        for clause in clauses[1:]:
            if not clause:
                raise ParseError(f"line {lineno}: empty clause after `|`: {raw.strip()!r}")
            apply(clause[0], clause[1:])
    return prog
