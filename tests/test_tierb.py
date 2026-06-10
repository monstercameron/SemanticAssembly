"""Tier B slice (Zba/Zbb/Zbs scalar bitmanip) + the A1 closure slices.

Because the kernel is table-driven, the new ops get the FULL analysis stack
for free: structural checks, liveness, value-flow, extension gating, emission,
and executable semantics in the taint interpreter."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.emit import emit                    # noqa: E402
from sasm.interp import Machine               # noqa: E402
from sasm.parser import parse                 # noqa: E402
from sasm.validate import validate            # noqa: E402

MASK = (1 << 64) - 1

BITS = """prog is program
prog target rva23u64
F is function
F symbol bits
F visibility global
F in x Int64 a0
F in y Int64 a1
F out z Int64 a0
x is value
x type Int64
y is value
y type Int64
z is value
z type Int64
E is block
E in F
E entry yes
E terminates return
i1 is insn
i1 in E
i1 operation AddShiftedBy3
i1 destination t0
i1 firstSource a0
i1 secondSource a1
i2 is insn
i2 in E
i2 operation AndNot
i2 destination t0
i2 firstSource t0
i2 secondSource a1
i3 is insn
i3 in E
i3 operation CountSetBits
i3 destination t1
i3 firstSource t0
i4 is insn
i4 in E
i4 operation RotateRightImmediate
i4 destination t2
i4 firstSource a0
i4 immediate 8
i5 is insn
i5 in E
i5 operation MaximumUnsigned
i5 destination a0
i5 firstSource t1
i5 secondSource t2
i5 writes z
r1 is insn
r1 in E
r1 operation Return
r1 returns z
"""


def _codes(src):
    return [d.code for d in validate(parse(src))]


def test_tierb_validates_emits_and_executes():
    assert _codes(BITS) == []
    out = emit(parse(BITS))
    for mnem in ("sh3add", "andn", "cpop", "rori", "maxu"):
        assert mnem in out, mnem
    m = Machine(parse(BITS))
    x, y = 0xDEADBEEF, 0xFF
    got = m.call("bits", [x, y]) & MASK
    t0 = (((x << 3) + y) & MASK) & ~y & MASK
    ref = max(bin(t0).count("1"), ((x >> 8) | (x << 56)) & MASK)
    assert got == ref and not m.diags


def test_tierb_extension_gating():
    assert "E-EXT-UNAVAILABLE" in _codes(BITS.replace("rva23u64", "rv64gc"))
    assert "E-EXT-UNAVAILABLE" not in _codes(BITS)


def test_tierb_unary_semantics():
    cases = {
        "CountLeadingZeros": (0x1, 63), "CountTrailingZeros": (0x8, 3),
        "SignExtendByte": (0x80, (-128) & MASK),
        "ZeroExtendHalfword": (0x12345678, 0x5678),
        "ReverseBytes": (0x0102030405060708, 0x0807060504030201),
    }
    for op, (arg, want) in cases.items():
        src = BITS.replace("i3 operation CountSetBits", f"i3 operation {op}")
        src = src.replace("i5 firstSource t1\ni5 secondSource t2",
                          "i5 firstSource t1\ni5 secondSource zero")
        src = src.replace("i3 firstSource t0", "i3 firstSource a0")
        m = Machine(parse(src))
        assert (m.call("bits", [arg, 0]) & MASK) == want, op


# ---------------------------------------------------------- A1 closure slices

def test_emitkind_restatement_is_derivable():
    bad = BITS.replace("r1 operation Return",
                       "r1 operation Return\nr1 emitKind pseudo")
    assert "E-DERIVABLE" in _codes(bad)


def test_emitkind_contradiction_is_an_error():
    bad = BITS.replace("i1 operation AddShiftedBy3",
                       "i1 operation AddShiftedBy3\ni1 emitKind pseudo")
    assert "E-ISA-FIELD" in _codes(bad)


def test_effect_restatement_is_derivable():
    bad = BITS.replace("i1 operation AddShiftedBy3",
                       "i1 operation AddShiftedBy3\ni1 effect none")
    # `effect none` equals the table default but IS the none case — exempt;
    # a memory-op restatement is the flagged shape:
    fib = (pathlib.Path(__file__).resolve().parents[1]
           / "examples/brainworms_fib/fib.sasm").read_text(encoding="utf-8")
    bad2 = fib.replace("saveReturnAddress memory region stackFrame\n", "")
    bad2 = bad2.replace("saveReturnAddress memory volatile yes\n", "")
    assert "E-DERIVABLE" in _codes(bad2)
