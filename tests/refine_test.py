"""A2 validator refinements: `requires` value-binding, asserted-liveOut mismatch
(E-LIVE-ASSERT), and unreachable-block detection (W-UNREACHABLE).

    python tests/refine_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sasm.parser import parse
from sasm.validate import validate


def codes(src):
    return {d.code for d in validate(parse(src))}


# `requires v in reg` where reg provably holds a different value
REQUIRES_BAD = """
n is value | type Int64
G is function | symbol g | in n Int64 a0 | out n Int64 a0 | effect none | leaf yes | stack bytes 0
E is block | in G | entry yes
clobber is insn | in E | operation LoadImmediate | destination a0 | immediate 0 | writes n
needN is insn | in E | operation Move | destination a0 | firstSource a0 | requires n in a0
done is insn | in E | operation Return | returns n
"""

# liveOut names a register that is dead immediately (overwritten, never read)
LIVEOUT_BAD = """
H is function | symbol h | in x Int64 a0 | out x Int64 a0 | effect none | leaf yes | stack bytes 0
E is block | in H | entry yes
dead is insn | in E | operation LoadImmediate | destination t3 | immediate 1 | liveOut t3:ghost
ret is insn | in E | operation Return
"""

# a block with no incoming edge from entry
UNREACHABLE = """
K is function | symbol k | in x Int64 a0 | out x Int64 a0 | effect none | leaf yes | stack bytes 0
E is block | in K | entry yes | terminates return
ret is insn | in E | operation Return
Island is block | in K | terminates return
orphan is insn | in Island | operation Return
"""


def main():
    assert "E-VALUE-FLOW" in codes(REQUIRES_BAD), codes(REQUIRES_BAD)
    assert "E-LIVE-ASSERT" in codes(LIVEOUT_BAD), codes(LIVEOUT_BAD)
    assert "W-UNREACHABLE" in codes(UNREACHABLE), codes(UNREACHABLE)
    print("A2 refinements: OK (requires / E-LIVE-ASSERT / W-UNREACHABLE all fire)")


if __name__ == "__main__":
    main()
