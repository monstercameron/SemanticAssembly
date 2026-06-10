"""Regressions from the gauntlet shakedown (2026-06-09).

Three challenging programs (ackermann / quicksort / revlist) were written
end-to-end and every friction point became a check. This file pins:
  - E-CFG-LAYOUT: the four clauses of DESIGN §11.1 (block reorder, row after
    terminator, running off the last block, entry-block target);
  - the noreturn-syscall terminator kind (terminates syscall);
  - the E-CFG-EDGE `terminates` cross-check;
  - the call-result rule: `writes <value>` on a Call binds the ABI return
    register (DESIGN §11.2).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.parser import parse          # noqa: E402
from sasm.validate import validate     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _codes(src: str) -> list[str]:
    return [d.code for d in validate(parse(src))]


def _messages(src: str, code: str) -> list[str]:
    return [d.message for d in validate(parse(src)) if d.code == code]


# ---------------------------------------------------------------- gauntlet examples stay clean

def test_gauntlet_examples_validate_clean():
    for rel in ("examples/gauntlet_ackermann/ackermann.sasm",
                "examples/gauntlet_quicksort/quicksort.sasm",
                "examples/gauntlet_revlist/revlist.sasm"):
        assert _codes(_read(rel)) == [], rel


# ---------------------------------------------------------------- E-CFG-LAYOUT

def test_block_reorder_is_caught():
    """The original audit probe: moving Done before Body must now error."""
    lines = _read("examples/challenging_sum_array/sum_array.sasm").splitlines()
    done = next(i for i, l in enumerate(lines) if l.startswith("Done is block"))
    moved = lines.pop(done)
    cond = next(i for i, l in enumerate(lines) if l.startswith("Condition is block"))
    lines.insert(cond + 1, moved)
    assert "E-CFG-LAYOUT" in _codes("\n".join(lines) + "\n")


def test_row_after_terminator_is_caught():
    src = _read("examples/brainworms_fib/fib.sasm") + (
        "\nstrayRow is insn\nstrayRow in Epilogue\nstrayRow operation NoOperation\n")
    msgs = _messages(src, "E-CFG-LAYOUT")
    assert any("after the terminator" in m for m in msgs)


def test_running_off_last_block_is_caught():
    # strip fib's final Return: the function now runs off Epilogue
    src = "\n".join(l for l in _read("examples/brainworms_fib/fib.sasm").splitlines()
                    if not l.startswith("returnResult")) + "\n"
    msgs = _messages(src, "E-CFG-LAYOUT")
    assert any("runs off its last block" in m for m in msgs)


def test_entry_block_target_is_legal_and_labeled():
    """The §15.1 label rule landed: targeting the entry block is legal, and
    the emitter defines `.L<entry>` right after the function symbol (two
    labels, one address) — no dangling reference."""
    from sasm.emit import emit
    src = _read("examples/gauntlet_revlist/revlist.sasm").replace(
        "returnReversedHead operation Return",
        "loopForever is insn\nloopForever in ReverseDone\n"
        "loopForever operation Jump\nloopForever target ReverseEntry\n"
        "ReverseDone successor ReverseEntry\n"
        "returnReversedHead operation Return")
    # the Jump makes Return unreachable-after-terminator? No: Jump IS the
    # terminator, Return follows it -> drop the Return instead
    src = "\n".join(l for l in src.splitlines()
                    if not l.startswith("returnReversedHead")) + "\n"
    out = emit(parse(src))
    assert ".Lreverseentry:" in out          # label defined
    assert "j\t.Lreverseentry" in out        # and referenced
    layout = [d for d in validate(parse(src))
              if d.code == "E-CFG-LAYOUT" and "entry" in d.message]
    assert not layout


# ---------------------------------------------------------------- terminates cross-check

def test_noreturn_syscall_is_a_terminator():
    """hello's Entry ends in `syscall exit` and declares `terminates syscall`."""
    assert _codes(_read("examples/hello_world/hello.sasm")) == []


def test_stale_terminates_fact_is_caught():
    src = _read("examples/hello_world/hello.sasm").replace(
        "Entry terminates syscall", "Entry terminates return")
    msgs = _messages(src, "E-CFG-EDGE")
    assert any("terminates return" in m for m in msgs)


# ---------------------------------------------------------------- call-result rule

def test_call_result_binds_return_register():
    """ackermann: callOuter `writes result` binds a0; reading result from a1
    after it must fail value-flow with the observed bindings named."""
    src = _read("examples/gauntlet_ackermann/ackermann.sasm").replace(
        "moveAnswer", "moveAnswer")  # identity guard: file must contain the calls
    assert "callOuter writes result" in src
    bad = src.replace(
        "returnResult operation Return",
        "bogusRead is insn\nbogusRead in Epilogue\nbogusRead operation Move\n"
        "bogusRead destination t6\nbogusRead firstSource a1\nbogusRead reads result\n"
        "returnResult operation Return")
    msgs = _messages(bad, "E-VALUE-FLOW")
    assert any("reads result" in m for m in msgs)


def test_call_result_does_not_bind_link_register():
    """The binding must land on a0, not returnAddress: reading the result value
    from a0 right after the call passes value-flow."""
    src = _read("examples/gauntlet_ackermann/ackermann.sasm").replace(
        "returnResult operation Return",
        "confirmRead is insn\nconfirmRead in Epilogue\nconfirmRead operation Move\n"
        "confirmRead destination t6\nconfirmRead firstSource a0\nconfirmRead reads result\n"
        "returnResult operation Return")
    assert "E-VALUE-FLOW" not in _codes(src)
