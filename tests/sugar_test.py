"""Pipe-sugar equivalence (LANGUAGE §20): the compact `| ` form must parse to the
exact same facts (and emit the same .s) as the one-fact-per-line form.

    python tests/sugar_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sasm.emit import emit
from sasm.parser import parse

PLAIN = """
Add2 is function
Add2 symbol add2
Add2 visibility global
Add2 in left Int64 a0
Add2 in right Int64 a1
Add2 out result Int64 a0
Add2 effect none

Entry is block
Entry in Add2
Entry entry yes

addLeftAndRight is insn
addLeftAndRight in Entry
addLeftAndRight operation Add
addLeftAndRight destination a0
addLeftAndRight firstSource a0
addLeftAndRight secondSource a1

returnResult is insn
returnResult in Entry
returnResult operation Return
"""

SUGAR = """
Add2 is function | symbol add2 | visibility global
Add2 in left Int64 a0 | in right Int64 a1 | out result Int64 a0 | effect none

Entry is block | in Add2 | entry yes

addLeftAndRight is insn | in Entry | operation Add
addLeftAndRight destination a0 | firstSource a0 | secondSource a1

returnResult is insn | in Entry | operation Return
"""


def facts(prog):
    return {n: (e.type, dict(e.facts)) for n, e in prog.entities.items()}


def main():
    p, s = parse(PLAIN), parse(SUGAR)
    assert facts(p) == facts(s), "pipe sugar does not parse to identical facts"
    assert emit(p) == emit(s), "pipe sugar does not emit identical .s"
    print("pipe-sugar equivalence: OK (facts and emitted .s identical)")


if __name__ == "__main__":
    main()
