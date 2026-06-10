"""Taint-interpreter tests (DESIGN §19): every example executes correctly
in-process AND its semantic facts are confirmed on the trace; every classic
lie is caught with an R-* diagnostic naming the row."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.parser import parse                    # noqa: E402
from sasm.interp import Machine, run_function, run_program  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(rel: str):
    return parse((ROOT / rel).read_text(encoding="utf-8"))


def _errors(m):
    return [str(d) for d in m.diags if d.severity == "error"]


# ---------------------------------------------------------------- positives

def test_add2():
    r, m = run_function(_load("examples/simple_add2/add2.sasm"), "add2", [2, 3])
    assert r == 5 and not m.diags


def test_sum_array():
    m = Machine(_load("examples/challenging_sum_array/sum_array.sasm"))
    base = m.alloc_int64_array([1, 2, 3, 4, 5])
    assert m.call("sum_array", [base, 5]) == 15
    assert m.call("sum_array", [base, 0]) == 0
    assert not m.diags


def test_fib_clean_with_declared_phi():
    r, m = run_function(_load("examples/brainworms_fib/fib.sasm"), "fib", [10])
    assert r == 55 and not m.diags
    cov = m.coverage()
    assert cov["blocksNotExecuted"] == [] and cov["readsUnconfirmed"] == []
    assert cov["liveOutChecked"] == 2


def test_ackermann_deep_recursion():
    r, m = run_function(_load("examples/gauntlet_ackermann/ackermann.sasm"),
                        "ack", [3, 3])
    assert r == 61 and not m.diags
    assert m.coverage()["blocksNotExecuted"] == []


def test_quicksort_sorts_in_machine_memory():
    m = Machine(_load("examples/gauntlet_quicksort/quicksort.sasm"))
    arr = [5, 2, 9, 2, -7, 0, 12, 5, -7, 3, 1, 8]
    base = m.alloc_int64_array(arr)
    m.call("qsort64", [base, 0, len(arr) - 1])
    assert m.read_int64_array(base, len(arr)) == sorted(arr)
    assert not _errors(m)


def test_revlist_round_trip():
    m = Machine(_load("examples/gauntlet_revlist/revlist.sasm"))
    n4 = m.alloc_int64_array([40, 0])
    n3 = m.alloc_int64_array([30, n4])
    n2 = m.alloc_int64_array([20, n3])
    n1 = m.alloc_int64_array([10, n2])
    assert m.call("sumlist", [n1]) == 300
    head = m.call("revlist", [n1])
    assert head == n4 and m.call("sumlist", [head]) == 200
    assert not m.diags


def test_device_gpio():
    """Arduino-style I/O against a fake register block; device effects clean."""
    m = Machine(_load("examples/device_gpio/gpio.sasm"))
    gpio = m.alloc_int64_array([0, 0])           # 16 bytes = 4 x u32
    m.call("pinModeOutput", [gpio, 5])
    m.call("pinModeOutput", [gpio, 3])
    assert m._load(gpio + 8, 4, False) == (1 << 5) | (1 << 3)
    m.call("digitalWrite", [gpio, 5, 1])
    m.call("digitalWrite", [gpio, 3, 1])
    m.call("digitalWrite", [gpio, 5, 0])         # RMW: pin 3 must survive
    assert m._load(gpio + 12, 4, False) == (1 << 3)
    m._store(gpio + 0, 1 << 7, 4)
    assert m.call("digitalRead", [gpio, 7]) == 1
    assert m.call("digitalRead", [gpio, 6]) == 0
    assert m.call("blink", [gpio, 5, 3]) == 6
    assert not m.diags


def test_device_motor():
    """PWM duty, sign-driven direction, table-driven stepper; regions clean."""
    m = Machine(_load("examples/device_motor/motor.sasm"))
    gpio = m.alloc_int64_array([0, 0])
    pwm = m.alloc_int64_array([0] * 8)
    m.call("pwmSetDuty", [pwm, 2, 180])
    assert m._load(pwm + 32 + 8, 4, False) == 180
    m.call("motorDrive", [gpio, pwm, 6, 1, -75])
    assert m._load(gpio + 12, 4, False) == (1 << 6)      # reverse
    assert m._load(pwm + 32 + 4, 4, False) == 75          # magnitude
    m.call("motorDrive", [gpio, pwm, 6, 1, 50])
    assert m._load(gpio + 12, 4, False) == 0              # forward
    assert m.call("stepperAdvance", [gpio, 0, 6]) == 2
    assert m._load(gpio + 12, 4, False) == 0xC            # pattern[2]
    assert not m.diags


def test_device_region_lie_is_caught():
    """Claim the GPIO store is stack traffic: the access lands on the heap and
    the runtime region check calls the lie."""
    src = _read_text("examples/device_gpio/gpio.sasm").replace(
        "storeOutputEnable memory region gpioRegisters",
        "storeOutputEnable memory region stackFrame")
    m = Machine(parse(src))
    gpio = m.alloc_int64_array([0, 0])
    m.call("pinModeOutput", [gpio, 5])
    assert any(d.code == "R-EFFECT" and "stackFrame" in d.message
               for d in m.diags)


def _read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_start_programs():
    code, m = run_program(_load("examples/hello_world/hello.sasm"))
    assert code == 0 and m.stdout.decode() == "Hello from semantic assembly!\n"
    code, m = run_program(_load("examples/sum_of_squares/sum_of_squares.sasm"))
    assert code == 0 and m.stdout.decode().strip() == "385"
    code, m = run_program(_load("examples/data_demo/data_demo.sasm"))
    assert code == 42 and not _errors(m)


# ---------------------------------------------------------------- the lies

FIB = (ROOT / "examples/brainworms_fib/fib.sasm").read_text(encoding="utf-8")


def _fib_diags(src, n=5):
    _, m = run_function(parse(src), "fib", [n])
    return [str(d) for d in m.diags]


def test_path_dependent_clobber_caught_dynamically():
    """The clobber the static may-analysis provably misses (DESIGN §11):
    read number from caller-saved a0 after the call."""
    bad = FIB.replace("computeNumberMinusTwo firstSource s0",
                      "computeNumberMinusTwo firstSource a0")
    ds = _fib_diags(bad, 10)
    assert any("R-VALUE-FLOW" in d and "computeNumberMinusTwo" in d for d in ds)


def test_effect_lie_caught():
    ds = _fib_diags(FIB.replace("Fib effect call", "Fib effect none"))
    assert any("R-EFFECT" in d for d in ds)


def test_frame_lie_caught():
    ds = _fib_diags(FIB.replace("Fib stack bytes 32", "Fib stack bytes 48"))
    assert any("R-ABI-FRAME" in d for d in ds)


def test_missing_restore_caught():
    bad = "\n".join(l for l in FIB.splitlines()
                    if not l.startswith("restoreCallerS0")) + "\n"
    ds = _fib_diags(bad)
    assert any("R-ABI-PRESERVE" in d and "s0" in d for d in ds)


def test_clobbered_return_address_halts_with_diagnosis():
    """Delete the ra restore: the machine must stop with R-ABI-PRESERVE,
    not wander off into garbage like real silicon."""
    bad = "\n".join(l for l in FIB.splitlines()
                    if not l.startswith("restoreReturnAddress")) + "\n"
    ds = _fib_diags(bad)
    assert any("R-ABI-PRESERVE" in d and "return token" in d for d in ds)


def test_undeclared_phi_is_flagged():
    """Remove the declared mergesFrom: the base-path return must be flagged."""
    bad = FIB.replace("result mergesFrom number\n", "")
    ds = _fib_diags(bad)
    assert any("R-VALUE-FLOW" in d and "mergesFrom" in d for d in ds)


def test_stale_liveout_tag_caught():
    bad = FIB.replace("callFibNumberMinusOne liveOut s0:number",
                      "callFibNumberMinusOne liveOut s0:firstResult")
    ds = _fib_diags(bad)
    assert any("R-LIVE-OUT" in d or "R-VALUE-FLOW" in d for d in ds)
