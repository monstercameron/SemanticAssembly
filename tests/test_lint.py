"""Every-surface-explicit checks (DESIGN §14): E-RESERVED, E-STACK-OP,
E-STACK-BALANCE, W-LINT, region-name resolution, writes-to-discard.
Each test is one of the silently-passing probes from the 2026-06 lint audit."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.parser import parse          # noqa: E402
from sasm.validate import validate     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIB = (ROOT / "examples/brainworms_fib/fib.sasm").read_text(encoding="utf-8")

BASE = """prog is program
prog target rva23u64
F is function
F symbol f
F visibility global
F in x Int64 a0
F out y Int64 a0
x is value
x type Int64
y is value
y type Int64
E is block
E in F
E entry yes
E terminates return
{rows}
r1 is insn
r1 in E
r1 operation Return
"""


def _codes(src):
    return [(d.severity, d.code, d.handle) for d in validate(parse(src))]


def _has(src, code, handle=None):
    return any(c == code and (handle is None or h == handle)
               for _, c, h in _codes(src))


def test_reserved_register_write_is_an_error():
    src = BASE.format(rows="i1 is insn\ni1 in E\ni1 operation AddImmediate\n"
                           "i1 destination globalPointer\n"
                           "i1 firstSource globalPointer\ni1 immediate 16")
    assert _has(src, "E-RESERVED", "i1")


def test_sp_write_without_stack_effect():
    bad = FIB.replace("allocateFrame effect stack.allocate",
                      "allocateFrame purpose x")
    assert _has(bad, "E-STACK-OP", "allocateFrame")


def test_unbalanced_frame_on_return():
    bad = FIB.replace("freeFrame immediate 32", "freeFrame immediate 16")
    assert _has(bad, "E-STACK-BALANCE", "returnResult")


def test_allocation_must_match_declared_bytes():
    bad = FIB.replace("allocateFrame immediate -32", "allocateFrame immediate -48")
    assert _has(bad, "E-STACK-BALANCE", "Fib")


def test_frame_without_declared_stack_bytes():
    bad = FIB.replace("Fib stack bytes 32\n", "")
    assert _has(bad, "E-STACK-BALANCE", "Fib")


def test_self_move_lint():
    src = BASE.format(rows="i1 is insn\ni1 in E\ni1 operation Move\n"
                           "i1 destination a0\ni1 firstSource a0")
    assert _has(src, "W-LINT", "i1")


def test_discarded_computation_lint():
    src = BASE.format(rows="i1 is insn\ni1 in E\ni1 operation Add\n"
                           "i1 destination zero\ni1 firstSource a0\n"
                           "i1 secondSource a0")
    assert _has(src, "W-LINT", "i1")


def test_undeclared_region_name_is_an_error():
    bad = FIB.replace("saveReturnAddress memory region stackFrame",
                      "saveReturnAddress memory region stakFrame")
    assert _has(bad, "E-REF", "saveReturnAddress")


def test_undeclared_effect_qualifier_is_an_error():
    src = (ROOT / "examples/device_gpio/gpio.sasm").read_text(encoding="utf-8")
    bad = src.replace("PinModeOutput effect device.write gpioRegisters",
                      "PinModeOutput effect device.write gpioRegs")
    assert _has(bad, "E-REF", "PinModeOutput")


def test_writes_to_discard_is_an_error():
    src = BASE.format(rows="i1 is insn\ni1 in E\ni1 operation Add\n"
                           "i1 destination zero\ni1 firstSource a0\n"
                           "i1 secondSource a0\ni1 writes y")
    assert _has(src, "E-VALUE-FLOW", "i1")


def test_all_examples_stay_clean():
    for p in sorted((ROOT / "examples").glob("*/*.sasm")):
        diags = validate(parse(p.read_text(encoding="utf-8")))
        assert not [d for d in diags if d.severity == "error"], p.name


# ------------------------------------------- W-RMW-RACE (review finding)

RMW = """prog is program
prog target rva23u64
sharedRegs is memoryRegion
sharedRegs kind device
sharedRegs volatile yes
sharedRegs concurrentWriters yes
F is function
F symbol f
F in p Address a0
F effect device.read sharedRegs
F effect device.write sharedRegs
F leaf yes
F stack bytes 0
p is value
p type Address
E is block
E in F
E entry yes
E terminates return
ld1 is insn
ld1 in E
ld1 operation LoadWord
ld1 destination t0
ld1 base a0
ld1 offset 12
ld1 effect device.read
ld1 memory region sharedRegs
or1 is insn
or1 in E
or1 operation OrImmediate
or1 destination t0
or1 firstSource t0
or1 immediate 32
st1 is insn
st1 in E
st1 operation StoreWord
st1 secondSource t0
st1 base a0
st1 offset 12
st1 effect device.write
st1 memory region sharedRegs
r1 is insn
r1 in E
r1 operation Return
"""


def test_rmw_on_concurrent_region_is_flagged():
    from sasm.parser import parse as _p
    from sasm.validate import validate as _v
    assert any(d.code == "W-RMW-RACE" and d.handle == "st1"
               for d in _v(_p(RMW)))


def test_rmw_without_concurrent_writers_is_the_explicit_contract():
    quiet = RMW.replace("sharedRegs concurrentWriters yes\n", "")
    from sasm.parser import parse as _p
    from sasm.validate import validate as _v
    assert not any(d.code == "W-RMW-RACE" for d in _v(_p(quiet)))


def test_amo_is_the_sanctioned_form():
    atomic = RMW.replace("""ld1 operation LoadWord
ld1 destination t0
ld1 base a0
ld1 offset 12""", """ld1 operation LoadWord
ld1 destination t0
ld1 base a0
ld1 offset 12""")
    # replace the load+or+store with a single AtomicOr at the same address
    atomic = RMW
    for h in ("ld1", "or1", "st1"):
        atomic = "\n".join(l for l in atomic.splitlines()
                           if not l.startswith(h + " ")) + "\n"
    atomic = atomic.replace("r1 is insn", """amo1 is insn
amo1 in E
amo1 operation AtomicOr
amo1 destination t0
amo1 secondSource t1
amo1 base a0
amo1 effect device.write
amo1 memory region sharedRegs
seed1 is insn
seed1 in E
seed1 operation LoadImmediate
seed1 destination t1
seed1 immediate 32
r1 is insn""")
    # seed t1 before the AMO uses it: move seed1 before amo1 textually
    from sasm.parser import parse as _p
    from sasm.validate import validate as _v
    diags = _v(_p(atomic))
    assert not any(d.code == "W-RMW-RACE" for d in diags)
