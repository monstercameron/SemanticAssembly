"""Regressions for the 2026-06-10 adversarial edge audit (14 findings).

Each test pins one finding's fix: silent-wrong became a validator error,
crashes became diagnostics or ExecError, and one integer grammar is shared by
check/emit/exec. Thesis discipline throughout: no fact silently believed, no
entity silently invisible, π never crashes."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sasm.emit import emit                       # noqa: E402
from sasm.format import format_program           # noqa: E402
from sasm.interp import ExecError, Machine, run_program  # noqa: E402
from sasm.parser import ParseError, parse        # noqa: E402
from sasm.validate import validate               # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADD2 = (ROOT / "examples/simple_add2/add2.sasm").read_text(encoding="utf-8")
HELLO = (ROOT / "examples/hello_world/hello.sasm").read_text(encoding="utf-8")


def _codes(src):
    return [(d.code, d.handle) for d in validate(parse(src))]


def _has(src, code, handle=None):
    return any(c == code and (handle is None or h == handle)
               for c, h in _codes(src))


# 1 ---------------------------------------------------------------- E-ENTITY

def test_missing_is_row_is_an_error_not_vanishing_code():
    bad = ADD2.replace("addLeftAndRight is insn\n", "")
    assert _has(bad, "E-ENTITY", "addLeftAndRight")


def test_typoed_entity_type_is_an_error():
    bad = ADD2.replace("addLeftAndRight is insn", "addLeftAndRight is insns")
    assert _has(bad, "E-ENTITY", "addLeftAndRight")


# 2 ------------------------------------------------- cross-function ownership

CROSS = """prog is program
prog target rva23u64
stackFrame is memoryRegion
stackFrame kind stack
F is function
F symbol f
F stack bytes 16
F preserves returnAddress
G is function
G symbol g
GSlot is stackSlot
GSlot in G
GSlot offset 24
GSlot type Int64
FEntry is block
FEntry in F
FEntry entry yes
FEntry terminates return
GEntry is block
GEntry in G
GEntry entry yes
GEntry terminates return
falloc is insn
falloc in FEntry
falloc operation AddImmediate
falloc destination stackPointer
falloc firstSource stackPointer
falloc immediate -16
falloc effect stack.allocate
fstore is insn
fstore in FEntry
fstore operation StoreDoubleword
fstore secondSource a0
fstore base stackPointer
fstore offset GSlot
fstore effect memory.write
fstore memory region stackFrame
ffree is insn
ffree in FEntry
ffree operation AddImmediate
ffree destination stackPointer
ffree firstSource stackPointer
ffree immediate 16
ffree effect stack.free
fret is insn
fret in FEntry
fret operation Return
gret is insn
gret in GEntry
gret operation Return
"""


def test_foreign_function_slot_is_an_error():
    assert _has(CROSS, "E-REF", "fstore")


# 6 --------------------------------------------------- cross-function targets

def test_jump_to_foreign_block_is_an_error():
    bad = CROSS.replace(
        "fret is insn",
        "fjump is insn\nfjump in FEntry\nfjump operation Jump\n"
        "fjump target GEntry\nFEntry successor GEntry\nfret is insn")
    assert _has(bad, "E-REF", "fjump")
    assert _has(bad, "E-REF", "FEntry")        # successor side too


# 3 ------------------------------------------------------------ fmt integrity

def test_fmt_quotes_comment_and_pipe_characters():
    src = ('msgRegion is memoryRegion\nmsgRegion kind readonly\n'
           'Msg is data\nMsg section rodata\nMsg type Bytes\n'
           'Msg value "item#1|x"\nMsg size 8\n')
    once = format_program(parse(src))
    assert emit(parse(once)) == emit(parse(src))


def test_quoted_subject_is_a_parse_error():
    with pytest.raises(ParseError):
        parse('"a b" is value\n')


# 4 ---------------------------------------------------------------- prog entry

def test_unresolvable_prog_entry_is_an_error():
    bad = HELLO.replace("prog entry _start", "prog entry doesNotExist")
    assert _has(bad, "E-REF", "prog")


def test_exec_start_refuses_unresolvable_declared_entry():
    bad = HELLO.replace("prog entry _start", "prog entry doesNotExist")
    with pytest.raises(ExecError):
        run_program(parse(bad))


# 5 ------------------------------------------------------------- entry blocks

def test_two_entry_blocks_is_an_error():
    bad = CROSS.replace("GEntry is block\nGEntry in G\nGEntry entry yes",
                        "GEntry is block\nGEntry in G\nGEntry entry yes\n"
                        "GExtra is block\nGExtra in G\nGExtra entry yes\n"
                        "GExtra terminates return\n"
                        "gxret is insn\ngxret in GExtra\ngxret operation Return")
    assert _has(bad, "E-CFG-LAYOUT", "G")


# 7 --------------------------------------------------------- offsetless slots

def test_slot_without_offset_is_an_error():
    bad = CROSS.replace("GSlot in G\nGSlot offset 24", "GSlot in F")
    assert _has(bad, "E-REF", "fstore")


# 8 -------------------------------------------------------- immediate grammar

def test_hex_immediate_is_an_error():
    bad = ADD2.replace("returnResult is insn",
                       "ld1 is insn\nld1 in Entry\nld1 operation LoadImmediate\n"
                       "ld1 destination t0\nld1 immediate 0x7FFF\n"
                       "returnResult is insn")
    assert _has(bad, "E-ISA-FIELD", "ld1")


def test_underscore_immediate_is_an_error():
    bad = ADD2.replace("returnResult is insn",
                       "ld1 is insn\nld1 in Entry\nld1 operation LoadImmediate\n"
                       "ld1 destination t0\nld1 immediate 1_000_000\n"
                       "returnResult is insn")
    assert _has(bad, "E-ISA-FIELD", "ld1")


# 9 ------------------------------------------------------------------- E-DATA

def test_data_align_zero_is_an_error():
    src = ("D is data\nD section data\nD type Int64\nD value 5\nD align 0\n")
    assert _has(src, "E-DATA", "D")


def test_bss_without_size_is_an_error():
    assert _has("D is data\nD section bss\n", "E-DATA", "D")


def test_bytes_size_must_match_escaped_length():
    bad = HELLO.replace("stdoutMessage size 30", "stdoutMessage size 99")
    assert _has(bad, "E-DATA", "stdoutMessage")


# 10 ----------------------------------------------------------- one writes

def test_multiple_writes_rows_is_an_error():
    bad = ADD2.replace("addLeftAndRight writes result",
                       "addLeftAndRight writes result\n"
                       "addLeftAndRight writes left")
    assert _has(bad, "E-VALUE-FLOW", "addLeftAndRight")


# 11 ------------------------------------------------------- emit never crashes

def test_emit_renders_none_for_missing_target():
    src = CROSS.replace("fret is insn",
                        "fjump is insn\nfjump in FEntry\nfjump operation Jump\n"
                        "fret is insn")
    out = emit(parse(src))                      # must not raise
    assert "None" in out


# 12/13 ------------------------------------------------- exec error discipline

def test_exec_too_many_args_is_execerror():
    with pytest.raises(ExecError):
        Machine(parse(ADD2)).call("add2", list(range(12)))


def test_exec_unknown_register_is_execerror():
    bad = ADD2.replace("addLeftAndRight secondSource a1",
                       "addLeftAndRight secondSource a99")
    with pytest.raises(ExecError):
        Machine(parse(bad)).call("add2", [1, 2])


# 14 ------------------------------------------------------------- is arity

def test_is_with_extra_args_is_a_parse_error():
    with pytest.raises(ParseError):
        parse("x is value garbage extra\n")
