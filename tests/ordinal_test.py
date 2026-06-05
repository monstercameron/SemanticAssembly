"""`ordinal` ordering (DESIGN §11.1, C2): when a block's instructions carry
`ordinal`, the emitter lays them out in ordinal order regardless of source order;
a block mixing ordinaled and bare instructions is rejected (E-ORDER-MIXED).

    python tests/ordinal_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sasm.emit import emit
from sasm.parser import parse
from sasm.validate import validate

# Instructions written in SCRAMBLED source order; ordinals impose execution order.
ORDERED = """
A is function | symbol a | visibility global | in left Int64 a0 | in right Int64 a1
A out result Int64 a0 | effect none | leaf yes | stack bytes 0
E is block | in A | entry yes
ret2 is insn | in E | operation Return | ordinal 30
add1 is insn | in E | operation Add | destination a0 | firstSource a0 | secondSource a1 | ordinal 10
"""

EXPECTED = "\t.text\n\t.globl\ta\na:\n\tadd\ta0, a0, a1\n\tret\n"

MIXED = """
B is function | symbol b | visibility global | in x Int64 a0 | out r Int64 a0 | effect none | leaf yes | stack bytes 0
F is block | in B | entry yes
m1 is insn | in F | operation Move | destination a0 | firstSource a0 | ordinal 10
m2 is insn | in F | operation Return
"""


def main():
    got = emit(parse(ORDERED))
    assert got == EXPECTED, f"ordinal sort failed:\n{got!r}\nwant\n{EXPECTED!r}"

    codes = {d.code for d in validate(parse(MIXED))}
    assert "E-ORDER-MIXED" in codes, f"expected E-ORDER-MIXED, got {codes}"

    print("ordinal ordering: OK (sorts by ordinal; mixed blocks flagged E-ORDER-MIXED)")


if __name__ == "__main__":
    main()
