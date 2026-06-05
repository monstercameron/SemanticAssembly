"""Symbol / linking directive emission (C5):
  - `symbol` entity with `binding weak`/`symbolType` -> `.weak` / `.type`
  - function `binding weak` -> `.weak`; `symbolType` -> `.type`

    python tests/symbol_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sasm.emit import emit
from sasm.parser import parse

WEAK_SYMBOL = """
maybe is symbol
maybe external yes
maybe binding weak
maybe symbolType func
"""

WEAK_FUNCTION = """
F is function | symbol helper | binding weak | symbolType func | abi linux.riscv64
F in x Int64 a0 | out r Int64 a0 | effect none | leaf yes | stack bytes 0
B is block | in F | entry yes
r is insn | in B | operation Return
"""


def main():
    s = emit(parse(WEAK_SYMBOL))
    assert "\t.weak\tmaybe" in s, s
    assert "\t.type\tmaybe, @function" in s, s

    f = emit(parse(WEAK_FUNCTION))
    assert "\t.weak\thelper" in f, f
    assert "\t.type\thelper, @function" in f, f
    assert "\t.globl\thelper" not in f, "weak binding must not also emit .globl"

    print("symbol/linking emission: OK (.weak and .type for symbols and functions)")


if __name__ == "__main__":
    main()
