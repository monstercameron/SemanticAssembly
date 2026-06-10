"""Regression: saves/restores row-consistency (E-ABI-PRESERVE, row half).

Found by the D1 trace probes (2026-06-10): a `restores r slot` fact paired
set-wise with its `saves`, but nothing tied the fact to the row's actual
memory operand or register — the fact could lie about which slot the load
reads (an unchecked copy, banned by DESIGN §11 clause 2).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sasm.parser import parse
from sasm.validate import validate

FIB = (ROOT / "examples" / "brainworms_fib" / "fib.sasm").read_text(
    encoding="utf-8")


def _errors(src):
    return [d for d in validate(parse(src))
            if d.severity == "error" and d.code == "E-ABI-PRESERVE"]


def test_clean_fib_has_no_spill_row_errors():
    assert not _errors(FIB)


def test_restore_offset_lies_about_slot():
    bad = FIB.replace("restoreCallerS1 offset SlotSavedS1",
                      "restoreCallerS1 offset SlotSavedS0")
    errs = _errors(bad)
    assert any("restoreCallerS1" in str(e) and "SlotSavedS0" in str(e)
               for e in errs), errs


def test_save_offset_lies_about_slot():
    bad = FIB.replace("saveCallerS1 offset SlotSavedS1",
                      "saveCallerS1 offset SlotSavedS0")
    errs = _errors(bad)
    assert any("saveCallerS1" in str(e) for e in errs), errs


def test_restore_moves_wrong_register():
    bad = FIB.replace("restoreCallerS1 destination s1",
                      "restoreCallerS1 destination s2")
    errs = _errors(bad)
    assert any("moves s2, not s1" in str(e) for e in errs), errs


def test_raw_integer_offset_must_match_declared_slot():
    bad = FIB.replace("saveCallerS1 offset SlotSavedS1",
                      "saveCallerS1 offset 0")
    errs = _errors(bad)
    assert any("offset 0" in str(e) for e in errs), errs
