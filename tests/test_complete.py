"""Regressions for the completion pass (2026-06-10): the last three catalog
codes (E-DUP, E-ORDER-KEY, E-EXT-UNAVAILABLE), unterminated strings,
successor-exactness + predecessor-inverse, per-path restore proof, clobbers
narrowing, liveIn/kills, syscall names, valueBindings complete, value
provenance, and the §15.1 entry-label rule's emit side."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.emit import emit                    # noqa: E402
from sasm.parser import ParseError, parse     # noqa: E402
from sasm.validate import validate            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIB = (ROOT / "examples/brainworms_fib/fib.sasm").read_text(encoding="utf-8")
SUM = (ROOT / "examples/challenging_sum_array/sum_array.sasm"
       ).read_text(encoding="utf-8")


def _codes(src):
    return [(d.severity, d.code, d.handle) for d in validate(parse(src))]


def _has(src, code, handle=None, severity=None):
    return any(c == code and (handle is None or h == handle)
               and (severity is None or s == severity)
               for s, c, h in _codes(src))


# ------------------------------------------------------------------- E-DUP

def test_duplicate_destination_is_an_error():
    bad = FIB.replace("moveNumberToS0 firstSource a0",
                      "moveNumberToS0 firstSource a0\n"
                      "moveNumberToS0 destination s1")
    assert _has(bad, "E-DUP", "moveNumberToS0")


def test_reis_declaration_is_a_parse_error():
    with pytest.raises(ParseError):
        parse("x is value\nx is block\n")


def test_case_insensitive_block_labels_collide():
    bad = FIB.replace(
        "Epilogue is block",
        "recurse is block\nrecurse in Fib\nrecurse terminates return\n"
        "rrret is insn\nrrret in recurse\nrrret operation Return\n"
        "Epilogue is block")
    assert _has(bad, "E-DUP")


def test_assembler_symbol_collision_is_an_error():
    bad = FIB + "\nfib is data\nfib section data\nfib type Int64\nfib value 1\n"
    assert _has(bad, "E-DUP")


# -------------------------------------------------------------- E-ORDER-KEY

ORD = FIB.replace("allocateFrame operation AddImmediate",
                  "allocateFrame ordinal {a}\nallocateFrame operation AddImmediate"
                  ).replace("saveReturnAddress operation StoreDoubleword",
                            "saveReturnAddress ordinal {b}\n"
                            "saveReturnAddress operation StoreDoubleword")


def _ordinal_all(src):
    # give every Prologue insn an ordinal so E-ORDER-MIXED stays quiet
    out = src
    for h in ("saveCallerS0", "saveCallerS1", "loadConstantTwo",
              "baseCaseBranch"):
        out = out.replace(f"{h} operation", f"{h} ordinal 90\n{h} operation", 1)
    return out


def test_non_integer_ordinal_is_an_error_not_a_crash():
    bad = _ordinal_all(ORD.format(a="ten", b="20"))
    assert _has(bad, "E-ORDER-KEY", "allocateFrame")
    emit(parse(bad))                      # §15.1: emit must not crash


def test_duplicate_ordinal_is_an_error():
    bad = _ordinal_all(ORD.format(a="10", b="10"))
    assert _has(bad, "E-ORDER-KEY", "saveReturnAddress")


# -------------------------------------------------------- E-EXT-UNAVAILABLE

def test_extension_gating():
    src = """prog is program
prog target rv64i
F is function
F symbol f
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
m1 is insn
m1 in E
m1 operation Multiply
m1 destination a0
m1 firstSource a0
m1 secondSource a0
m1 writes y
r1 is insn
r1 in E
r1 operation Return
r1 returns y
"""
    assert _has(src, "E-EXT-UNAVAILABLE", "m1")        # mul needs M
    assert not _has(src.replace("rv64i", "rv64im"), "E-EXT-UNAVAILABLE")
    assert _has(src.replace("rv64i", "rv64bogus"), "E-EXT-UNAVAILABLE", "prog")


# ------------------------------------------------------------------ parser

def test_unterminated_string_is_a_parse_error():
    with pytest.raises(ParseError):
        parse('x is value\nx meaning "no closing quote\n')


# ------------------------------------------------- CFG exactness both ways

def test_stale_successor_is_an_error():
    """The original audit probe: a declared successor the terminator cannot
    take silently widened every dataflow merge — now E-CFG-EDGE."""
    bad = FIB.replace("Prologue successor Recurse",
                      "Prologue successor Recurse\nPrologue successor Ghost")
    bad = bad.replace("Epilogue is block",
                      "Ghost is block\nGhost in Fib\nGhost terminates return\n"
                      "gret is insn\ngret in Ghost\ngret operation Return\n"
                      "Epilogue is block")
    assert _has(bad, "E-CFG-EDGE", "Prologue")


def test_wrong_predecessor_is_an_error():
    bad = FIB.replace("Epilogue predecessor Prologue",
                      "Epilogue predecessor Recurse")
    assert _has(bad, "E-CFG-EDGE", "Epilogue")


# ------------------------------------------------ per-path restore proof

def test_restore_missing_on_one_of_two_paths():
    """fib restores s0/s1/ra in the shared epilogue. Add a branch AFTER the
    recursion (where all three are dirty) to a second return block with no
    restores: the set-wise check passes (restores exist somewhere), the
    per-path proof must not."""
    bad = FIB.replace("Recurse terminates fallthrough",
                      "Recurse terminates branch")
    bad = bad.replace("Recurse successor Epilogue",
                      "Recurse successor Epilogue\nRecurse successor FastExit")
    bad += (
        "\nshortcutBranch is insn\nshortcutBranch in Recurse\n"
        "shortcutBranch operation BranchIfZero\nshortcutBranch firstSource a0\n"
        "shortcutBranch target FastExit\nshortcutBranch fallthrough Epilogue\n"
        "FastExit is block\nFastExit in Fib\nFastExit terminates return\n"
        "FastExit predecessor Recurse\n"
        "fastFree is insn\nfastFree in FastExit\n"
        "fastFree operation AddImmediate\nfastFree destination stackPointer\n"
        "fastFree firstSource stackPointer\nfastFree immediate 32\n"
        "fastFree effect stack.free\n"
        "fastRet is insn\nfastRet in FastExit\nfastRet operation Return\n")
    assert _has(bad, "E-ABI-PRESERVE", "fastRet")


def test_mismatched_save_restore_slot_pairing():
    bad = FIB.replace("restoreCallerS0 restores s0 SlotSavedS0",
                      "restoreCallerS0 restores s0 SlotSavedS1")
    assert _has(bad, "E-ABI-PRESERVE", "Fib")


# ------------------------------------------------------ clobbers narrowing

def test_clobbers_narrowing_quiets_w_clobber():
    """Leave `number` in caller-saved a3 across the call, but declare the
    callee only clobbers a0/a1: W-CLOBBER must NOT fire for a3 (and the
    value-flow must accept the binding)."""
    src = FIB.replace("moveNumberToS0 destination s0",
                      "moveNumberToS0 destination a3")
    src = src.replace("computeNumberMinusOne firstSource s0",
                      "computeNumberMinusOne firstSource a3")
    src = src.replace("computeNumberMinusTwo firstSource s0",
                      "computeNumberMinusTwo firstSource a3")
    src = src.replace("callFibNumberMinusOne liveOut s0:number",
                      "callFibNumberMinusOne liveOut a3:number\n"
                      "callFibNumberMinusOne clobbers a0 a1")
    with_narrowing = [d for d in validate(parse(src))
                      if d.code in ("W-CLOBBER", "E-VALUE-FLOW")
                      and "a3" in d.message]
    assert not with_narrowing
    # without the clobbers fact the same layout IS flagged
    wide = src.replace("callFibNumberMinusOne clobbers a0 a1\n", "")
    assert any(d.code in ("W-CLOBBER", "E-VALUE-FLOW")
               for d in validate(parse(wide)))


# --------------------------------------------------------- liveIn / kills

def test_stale_livein_is_an_error():
    bad = SUM.replace("loopGuard reads index",
                      "loopGuard liveIn t5:scratch\nloopGuard reads index")
    assert _has(bad, "E-LIVE-ASSERT", "loopGuard")


def test_stale_kills_is_an_error():
    bad = SUM.replace("loopGuard reads index",
                      "loopGuard kills t0\nloopGuard reads index")
    assert _has(bad, "E-LIVE-ASSERT", "loopGuard")


# ---------------------------------------------------------- syscall names

def test_unknown_syscall_name_is_an_error():
    hello = (ROOT / "examples/hello_world/hello.sasm").read_text(encoding="utf-8")
    bad = hello.replace("doExit syscall exit", "doExit syscall exi")
    assert _has(bad, "E-REF", "doExit")


# ------------------------------------------------- valueBindings complete

def test_value_bindings_complete_flags_missing_read():
    bad = FIB.replace("computeNumberMinusTwo immediate -2",
                      "computeNumberMinusTwo immediate -2\n"
                      "computeNumberMinusTwo valueBindings complete")
    bad = bad.replace("computeNumberMinusTwo reads number\n", "")
    assert _has(bad, "E-VALUE-FLOW", "computeNumberMinusTwo")


# ----------------------------------------------------- value provenance

def test_defined_by_must_match_a_writes_row():
    bad = FIB.replace("firstResult meaning",
                      "firstResult definedBy computeNumberMinusOne\n"
                      "firstResult meaning")
    assert _has(bad, "E-REF", "firstResult")


def test_stored_in_must_match_slot_stores():
    bad = FIB.replace("number meaning",
                      "number storedIn SlotSavedS1\nnumber meaning")
    assert _has(bad, "E-REF", "number")
