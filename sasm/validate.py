"""Validator — turns DESIGN §14 diagnostic codes into checks.

This first cut covers the *structural* checks that need no dataflow fixpoint
(the cheap, fully-specified ones). Liveness / value-flow (E-LIVE-*, W-CLOBBER,
E-VALUE-FLOW) and the derivable-fact linter come later; they share the CFG built
here.

Diagnostic shape (DESIGN §5.1/§14): `severity code handle: message`.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from . import isa
from .model import Entity, Program

_FORMATTER = string.Formatter()


@dataclass
class Diagnostic:
    severity: str  # "error" | "warning"
    code: str
    handle: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity} {self.code} {self.handle}: {self.message}"


_TYPE_BYTES = {
    "Int8": 1, "Nat8": 1, "Boolean": 1,
    "Int16": 2, "Nat16": 2,
    "Int32": 4, "Nat32": 4, "Float32": 4,
    "Int64": 8, "Nat64": 8, "Float64": 8, "Address": 8,
}
_WIDTH_SUFFIX = {"Byte": 1, "Halfword": 2, "Word": 4, "Doubleword": 8}
_NO_WIDTH = {  # ops that produce no typed value
    "NoOperation", "Jump", "JumpRegister", "TailCall", "Return",
    "BranchIfZero", "BranchIfNonzero",
}


def _op_width(spec: dict) -> int | None:
    """Access/result width in bytes, derived from the op (None if not typed).

    (Derived here rather than stored as an optable column; a column can replace
    this later — DESIGN E-TYPE note.)"""
    sem, cls = spec["sem"], spec["class"]
    if cls in ("load", "store"):
        for suffix, n in _WIDTH_SUFFIX.items():
            if sem.endswith(suffix):
                return n
        return 8
    if cls in ("arith", "logic", "shift", "compare", "muldiv", "cond",
               "zba", "zbb", "zbs"):
        return 4 if ("Word" in sem and "Halfword" not in sem) else 8
    if cls == "atomic":
        return 8
    if cls in ("const", "pseudo", "jump"):
        return None if sem in _NO_WIDTH else 8
    return None


def _value_width(v) -> int | None:
    """Width in bytes of a declared value, from its type, pointer-ness, or bits."""
    t = v.scalar("type")
    if t:
        if t in _TYPE_BYTES:
            return _TYPE_BYTES[t]
        if t.endswith("Pointer"):
            return 8
    bits = v.scalar("bits")
    if _is_int(bits):
        return max(1, int(bits) // 8)
    return None


_INT = __import__("re").compile(r"-?\d+\Z")

# every entity type the vocabulary defines (LANGUAGE) — anything else is a
# typo that would make the entity invisible to every of_type/members_of walk
KNOWN_TYPES = frozenset({
    "program", "function", "block", "insn", "data", "stackSlot", "value",
    "memoryRegion", "symbol", "parameter", "vectorConfig",
})

_DATA_WIDTH = {"Int8": 1, "Nat8": 1, "Boolean": 1, "Int16": 2, "Nat16": 2,
               "Int32": 4, "Nat32": 4, "Int64": 8, "Nat64": 8, "Address": 8}


def _is_int(s: str | None) -> bool:
    """ONE integer grammar for the whole toolchain: decimal, optional minus.
    (Python's int() accepts 0x… nowhere but '1_000_000' everywhere — a literal
    that validated clean, executed clean, and emitted .s GAS rejects. One
    grammar, three tools — 2026-06 edge audit.)"""
    return s is not None and bool(_INT.match(s))


def _escaped_length(s: str) -> int:
    """byte length of a Bytes literal after assembler escapes (\\n etc.)."""
    n, i = 0, 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in "ntr0\\\"":
            i += 2
        else:
            i += 1
        n += 1
    return n


def _observed_effects(prog: Program, fn: Entity, ops: dict, regions: dict) -> set[str]:
    """Union of per-instruction observable effects (internal-effect rule applied)."""
    obs: set[str] = set()
    for blk in prog.members_of(fn.name, "block"):
        for insn in prog.members_of(blk.name, "insn"):
            spec = ops.get(insn.scalar("operation"))
            facts = [r[0] for r in insn.all("effect") if r]
            # an instruction's own effect facts refine the op-table effect
            effs = set(facts) if facts else (
                {spec["effect"]} if spec and spec["effect"] != "none" else set()
            )
            region = None
            for r in insn.all("memory"):
                if len(r) >= 2 and r[0] == "region":
                    region = r[1]
            kind = regions.get(region)
            for e in effs:
                if e in ("memory.read", "memory.write") and kind == "stack":
                    continue  # internal-effect rule (LANGUAGE §10)
                if e in ("stack.allocate", "stack.free", "none"):
                    continue
                obs.add(e)
    return obs


_SEED_ALWAYS = frozenset(
    {"stackPointer", "globalPointer", "threadPointer", "returnAddress", "zero"}
)


_OPERAND_FIELDS = ("destination", "firstSource", "secondSource", "thirdSource", "base")


def _role_regs(insn: Entity, tokens) -> set[str]:
    """Resolve op-table defines/uses tokens to registers.

    A token is either an operand-field name (resolve via the instruction's fact,
    e.g. `destination` -> a0) or a literal register name (e.g. `returnAddress`
    for Return/Call, which read/write `ra` directly with no operand field).
    """
    out = set()
    for t in tokens:
        r = insn.scalar(t) if t in _OPERAND_FIELDS else t
        if r and r != "zero":
            out.add(r)
    return out


def _check_preserve(prog, fn, ops, abi, add) -> None:
    """E-ABI-PRESERVE: a callee-saved register the function reuses must be saved,
    restored, and declared `preserves` (LANGUAGE §1; DESIGN §14).

    A reg is *clobbered* if some instruction writes it (per the op table) and that
    instruction is not itself the restoring reload. Reusing a callee-saved reg
    incurs the obligation; the function need only account for the ones it touches.
    `stackPointer` is excluded — it is managed by stack.allocate/free, not spills.
    """
    abikey = fn.scalar("abi") or "linux.riscv64"
    callee = set(abi.get(abikey, {}).get("calleeSaved", [])) - {"stackPointer"}
    if not callee:
        return

    saved = {r[0] for i in _fn_insns(prog, fn) for r in i.all("saves") if r}
    restored = {r[0] for i in _fn_insns(prog, fn) for r in i.all("restores") if r}
    declared = {r[0] for r in fn.all("preserves") if r}

    clobbered = set()
    for insn in _fn_insns(prog, fn):
        if insn.has("restores"):
            continue  # the restoring reload is not a clobber
        spec = ops.get(insn.scalar("operation"))
        if not spec:
            continue
        for v in _role_regs(insn, spec["defines"]):
            if v in callee:
                clobbered.add(v)

    for r in sorted(clobbered):
        missing = []
        if r not in saved:
            missing.append("not saved")
        if r not in restored:
            missing.append("not restored")
        if r not in declared:
            missing.append("not declared `preserves`")
        if missing:
            add("error", "E-ABI-PRESERVE", fn.name,
                f"reuses callee-saved {r} but it is {', '.join(missing)}")


def _fn_insns(prog, fn):
    for blk in prog.members_of(fn.name, "block"):
        yield from prog.members_of(blk.name, "insn")


# predicates that carry ONE authoritative slot per entity (LANGUAGE grammar
# rules): a second row is dead text the first silently wins over — the exact
# append-style-edit trap E-DUP exists for
_SINGLE_VALUED = {
    "insn": {"in", "operation", "destination", "firstSource", "secondSource",
             "thirdSource", "base", "immediate", "offset", "symbol", "target",
             "fallthrough", "ordinal", "syscall", "emitKind"},
    "block": {"in", "entry", "terminates", "loop", "backEdgeTo"},
    "function": {"symbol", "visibility", "binding", "abi", "leaf",
                 "framePointer", "variadic", "privilege", "unwind"},
    "data": {"section", "type", "value", "size", "align", "binding"},
    "stackSlot": {"in", "offset", "type", "role", "size", "stores"},
    "value": {"in", "type", "signed", "bits", "unit"},
    "program": {"target", "xlen", "abi", "pic", "compressed", "emission",
                "endian", "entry"},
    "memoryRegion": {"kind", "volatile", "concurrentWriters"},
    "symbol": {"external", "binding", "symbolType", "reloc", "linkerDefined"},
}


def _check_dup(prog, add) -> None:
    """E-DUP: duplicate single-valued facts, case-insensitive block-label
    collisions (`.L` labels are lowercased and file-scoped), and assembler
    symbol collisions across functions/data/symbol entities."""
    for e in prog.entities.values():
        singles = _SINGLE_VALUED.get(e.type, set())
        for pred, rows in e.facts.items():
            if pred in singles and len(rows) > 1:
                add("error", "E-DUP", e.name,
                    f"`{pred}` appears {len(rows)} times but is "
                    f"single-valued — only the first row is read; the "
                    f"duplicates are dead text (edit the row, never append)")

    by_label: dict[str, list[str]] = {}
    for b in prog.of_type("block"):
        by_label.setdefault(b.name.lower(), []).append(b.name)
    for low, names in by_label.items():
        if len(names) > 1:
            add("error", "E-DUP", names[1],
                f"block handles {names} collide case-insensitively — emitted "
                f"labels are `.L{low}` for both (the .L namespace is "
                f"file-scoped and lowercased)")

    emitted: dict[str, list[str]] = {}
    for f in prog.of_type("function"):
        emitted.setdefault(f.scalar("symbol", f.name), []).append(f.name)
    for d in prog.of_type("data"):
        emitted.setdefault(d.name, []).append(d.name)
    for s in prog.of_type("symbol"):
        emitted.setdefault(s.name, []).append(s.name)
    for sym, owners in emitted.items():
        if len(owners) > 1:
            add("error", "E-DUP", owners[1],
                f"label `{sym}` is emitted by multiple entities {owners} — "
                f"the assembler namespace is one flat scope")


def _call_clobbers(insn, caller_saved) -> set:
    """A Call's clobber set: the full ABI caller-saved set by default,
    narrowed by declared `clobbers <reg>...` facts for a known callee
    (LANGUAGE §3). `clobbers callerSaved` is the explicit default."""
    regs = [x for row in insn.all("clobbers") for x in row]
    if not regs or "callerSaved" in regs:
        return set(caller_saved)
    return set(regs) | {"returnAddress"}


def _check_rmw(prog, fn, ops, concurrent, add) -> None:
    """W-RMW-RACE (external review finding, 2026-06-10): naming an RMW hazard
    does not make it atomic. A plain load-modify-store to the same address on
    a region declared `concurrentWriters yes` (interrupt handlers, other
    cores, DMA) can lose updates between the load and the store. Flag it:
    use an atomic op, mask interrupts, or take a lock. Regions WITHOUT the
    fact carry the explicit single-writer assumption — that is the contract."""
    if not concurrent:
        return
    for blk in prog.members_of(fn.name, "block"):
        pending: dict[tuple, str] = {}      # (base, offset) -> loading handle
        for i in prog.members_of(blk.name, "insn"):
            spec = ops.get(i.scalar("operation"))
            if not spec:
                continue
            region = None
            for r in i.all("memory"):
                if len(r) >= 2 and r[0] == "region":
                    region = r[1]
            if region not in concurrent:
                continue
            key = (i.scalar("base"), i.scalar("offset"))
            if spec["class"] == "load":
                pending[key] = i.name
            elif spec["class"] == "store" and key in pending:
                add("warning", "W-RMW-RACE", i.name,
                    f"non-atomic read-modify-write on `{region}` "
                    f"(concurrentWriters yes): loaded at {pending[key]}, "
                    f"stored here — a concurrent writer between the two loses "
                    f"updates. Use an atomic op, mask interrupts, or lock")
            elif spec["class"] == "atomic":
                pending.pop(key, None)      # AMO is the sanctioned form


def _check_lint(prog, fn, ops, abi, add) -> None:
    """E-RESERVED + W-LINT (DESIGN §14): legal-but-never-intended shapes that
    raw assembly permits silently. These need NO declared context — they are
    derived from A-facts and the ABI tables alone."""
    abikey = fn.scalar("abi") or "linux.riscv64"
    reserved = set(abi.get(abikey, {}).get("reserved", []))
    for blk in prog.members_of(fn.name, "block"):
        for i in prog.members_of(blk.name, "insn"):
            spec = ops.get(i.scalar("operation"))
            if not spec:
                continue
            for d in _role_regs(i, spec["defines"]):
                if d in reserved:
                    add("error", "E-RESERVED", i.name,
                        f"writes {d}, which the platform ABI reserves "
                        f"(abi.tsv `reserved`) — the runtime owns it")
            if spec["sem"] == "Move" \
                    and i.scalar("destination") == i.scalar("firstSource"):
                add("warning", "W-LINT", i.name,
                    "self-move: destination equals source — a no-op")
            if i.scalar("destination") == "zero" and spec["sem"] != "NoOperation":
                add("warning", "W-LINT", i.name,
                    "result written to `zero` is discarded — use NoOperation "
                    "or a real destination")
            if spec["control"] == "branch":
                tgt, ft = i.scalar("target"), i.scalar("fallthrough")
                if tgt and tgt == ft:
                    add("warning", "W-LINT", i.name,
                        "branch target equals its fall-through — the branch "
                        "decides nothing")


def _check_stack(prog, fn, ops, syscalls, add) -> None:
    """E-STACK-OP + E-STACK-BALANCE (DESIGN §14): the stack pointer is an
    explicit surface. Every sp write must declare `effect stack.allocate` or
    `stack.free` and be a CONSTANT AddImmediate; a forward pass then proves,
    per path: balanced frames at every return, consistent depth at merges,
    16-byte alignment at every call, and that the allocation matches the
    declared `stack bytes` (closing the A3 prologue cross-check statically)."""
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    names = {b.name for b in blocks}
    declared = next((int(r[1]) for r in fn.all("stack")
                     if len(r) >= 2 and r[0] == "bytes" and _is_int(r[1])), None)

    def sp_delta(i, spec) -> int | None:
        """delta this row applies to sp, or None if sp untouched."""
        if "stackPointer" not in _role_regs(i, spec["defines"]):
            return None
        if not any(r and r[0] in ("stack.allocate", "stack.free")
                   for r in i.all("effect")):
            add("error", "E-STACK-OP", i.name,
                "adjusts stackPointer without declaring `effect "
                "stack.allocate` / `stack.free` — sp is an explicit surface")
        if spec["sem"] == "AddImmediate" \
                and i.scalar("firstSource") == "stackPointer" \
                and _is_int(i.scalar("immediate")):
            return int(i.scalar("immediate"))
        add("error", "E-STACK-BALANCE", i.name,
            "non-constant stackPointer adjustment — v0 frames are constant "
            "AddImmediate only (dynamic allocation is out of scope)")
        return 0

    offset_in: dict[str, int] = {blocks[0].name: 0}
    min_off = 0
    worklist = [blocks[0].name]
    blk_by = {b.name: b for b in blocks}
    seen_merge_err = set()
    while worklist:
        bname = worklist.pop()
        off = offset_in[bname]
        noreturn = False
        for i in prog.members_of(bname, "insn"):
            spec = ops.get(i.scalar("operation"))
            if not spec:
                continue
            if spec["control"] == "call" and off % 16 != 0:
                add("error", "E-ABI-ALIGN", i.name,
                    f"call at stack depth {-off}: sp is not 16-byte aligned "
                    f"on this path")
            if spec["control"] == "return" and off != 0:
                add("error", "E-STACK-BALANCE", i.name,
                    f"returns with stack depth {-off}: the frame is "
                    f"{'not freed' if off < 0 else 'over-freed'} on this path")
            if spec["control"] == "syscall":
                row = syscalls.get(i.scalar("syscall") or "")
                if row and row.get("return") == "-":
                    noreturn = True
            d = sp_delta(i, spec)
            if d is not None:
                off += d
                min_off = min(min_off, off)
        if noreturn:
            continue
        for s in blk_by[bname].values("successor"):
            if s not in names:
                continue
            if s in offset_in:
                if offset_in[s] != off and (bname, s) not in seen_merge_err:
                    seen_merge_err.add((bname, s))
                    add("error", "E-STACK-BALANCE", s,
                        f"inconsistent stack depth at merge: {-offset_in[s]} "
                        f"vs {-off} arriving from {bname}")
            else:
                offset_in[s] = off
                worklist.append(s)

    if min_off != 0 and declared is None:
        add("error", "E-STACK-BALANCE", fn.name,
            f"moves sp to depth {-min_off} but declares no `stack bytes` — "
            f"the frame must be an explicit fact")
    elif declared is not None and declared != 0 and -min_off != declared:
        add("error", "E-STACK-BALANCE", fn.name,
            f"declares `stack bytes {declared}` but the deepest sp adjustment "
            f"is {-min_off}")


def _check_restore_paths(prog, fn, ops, abi, syscalls, add) -> None:
    """E-ABI-PRESERVE, the per-path half: every clobbered callee-saved
    register (and returnAddress after any call) must be restored on EVERY
    path to a return — the set-wise check passes a function that restores on
    only one of two return paths. Also: each `saves r slot` must pair with a
    `restores r slot` through the SAME slot."""
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    names = {b.name for b in blocks}
    abikey = fn.scalar("abi") or "linux.riscv64"
    tracked = (set(abi.get(abikey, {}).get("calleeSaved", []))
               - {"stackPointer"}) | {"returnAddress"}

    saves_pairs, restores_pairs = set(), set()
    for blk in blocks:
        for i in prog.members_of(blk.name, "insn"):
            for r in i.all("saves"):
                if len(r) >= 2:
                    saves_pairs.add((r[0], r[1]))
            for r in i.all("restores"):
                if len(r) >= 2:
                    restores_pairs.add((r[0], r[1]))
    for reg, slot in sorted(saves_pairs - restores_pairs):
        add("error", "E-ABI-PRESERVE", fn.name,
            f"saves {reg} to {slot} but never restores through that slot — "
            f"save/restore must pair through the SAME named slot")
    for reg, slot in sorted(restores_pairs - saves_pairs):
        add("error", "E-ABI-PRESERVE", fn.name,
            f"restores {reg} from {slot} but never saves through that slot")

    blk_by = {b.name: b for b in blocks}
    dirty_in: dict[str, frozenset] = {blocks[0].name: frozenset()}
    worklist = [blocks[0].name]
    flagged = set()
    while worklist:
        bname = worklist.pop()
        dirty = set(dirty_in[bname])
        noreturn = False
        for i in prog.members_of(bname, "insn"):
            spec = ops.get(i.scalar("operation"))
            if not spec:
                continue
            restored_here = {r[0] for r in i.all("restores") if r}
            if restored_here:
                dirty -= restored_here
            else:
                defs = _role_regs(i, spec["defines"])
                if spec["control"] == "call":
                    defs = defs | {"returnAddress"}
                dirty |= defs & tracked
            if spec["control"] == "return":
                for r in sorted(dirty):
                    if (bname, r) not in flagged:
                        flagged.add((bname, r))
                        add("error", "E-ABI-PRESERVE", i.name,
                            f"{r} is clobbered but not restored on the path "
                            f"through {bname}")
            if spec["control"] == "syscall":
                row = syscalls.get(i.scalar("syscall") or "")
                if row and row.get("return") == "-":
                    noreturn = True
        if noreturn:
            continue
        new = frozenset(dirty)
        for s in blk_by[bname].values("successor"):
            if s not in names:
                continue
            prev = dirty_in.get(s)
            merged = new if prev is None else frozenset(prev | new)
            if prev is None or merged != prev:
                dirty_in[s] = merged
                worklist.append(s)


def _check_spill_rows(prog, fn, add) -> None:
    """E-ABI-PRESERVE, the row-consistency half: a `saves r slot` /
    `restores r slot` fact must describe what its own row DOES — the row's
    memory operand must address the named slot, and the register moved must
    be r. Without this the pairing check above is satisfiable by facts that
    lie about which slot the store/load actually touches (hole found by the
    D1 trace probes, 2026-06-10)."""
    slot_off = {s.name: s.scalar("offset") for s in prog.of_type("stackSlot")}
    for blk in prog.members_of(fn.name, "block"):
        for i in prog.members_of(blk.name, "insn"):
            for pred, regfield in (("saves", "secondSource"),
                                   ("restores", "destination")):
                for r in i.all(pred):
                    if len(r) < 2:
                        continue
                    reg, slot = r[0], r[1]
                    moved = i.scalar(regfield)
                    if moved is not None and moved != reg:
                        add("error", "E-ABI-PRESERVE", i.name,
                            f"declares `{pred} {reg} {slot}` but the row "
                            f"moves {moved}, not {reg}")
                    off = i.scalar("offset")
                    if off is None or slot not in slot_off or off == slot:
                        continue
                    verb = "store" if pred == "saves" else "load"
                    if off in slot_off:
                        add("error", "E-ABI-PRESERVE", i.name,
                            f"declares `{pred} {reg} {slot}` but the row's "
                            f"offset addresses {off} — the {verb} does not "
                            f"touch the declared slot")
                    elif str(off) != str(slot_off[slot]):
                        add("error", "E-ABI-PRESERVE", i.name,
                            f"declares `{pred} {reg} {slot}` (offset "
                            f"{slot_off[slot]}) but the row's {verb} uses "
                            f"offset {off}")


_TERMINATOR_KINDS = {"branch", "jump", "return", "syscall"}


def _check_layout(prog, fn, ops, syscalls, add) -> None:
    """E-CFG-LAYOUT (DESIGN §11.1/§14): block source order IS layout and π never
    synthesizes a jump, so:
      (1) a terminator must be its block's last row;
      (2) every implicit fall-through edge must land on the physically next block;
      (3) the function may not run off its last block;
      (4) nothing may target the entry block until §15.1's label rule lands.
    Also cross-checks a declared `terminates` against the actual terminator
    (the E-CFG-EDGE half of §13 step 2).

    A terminator is a branch/jump/return row — or a NORETURN syscall (an
    EnvironmentCall whose `syscall` name has `return -` in syscalls.tsv, e.g.
    exit): control provably never continues past it."""
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    n_entry = sum(1 for b in blocks if b.scalar("entry") == "yes")
    if n_entry != 1:
        # >1: the emitter suppresses EVERY entry label, so a branch to the
        # second produces an undefined-label .s; 0: "first block" is an
        # accident of declaration order. Either way layout is underdetermined.
        add("error", "E-CFG-LAYOUT", fn.name,
            f"has {n_entry} blocks marked `entry yes` — exactly one is "
            f"required (layout and the function label hang on it)")
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    names = {b.name for b in blocks}
    entry = blocks[0].name if blocks[0].scalar("entry") == "yes" else None
    nxt = {blocks[i].name: (blocks[i + 1].name if i + 1 < len(blocks) else None)
           for i in range(len(blocks))}

    def kind_of(i) -> str:
        """terminator kind of a row, or 'seq' if control continues past it."""
        spec = ops.get(i.scalar("operation"))
        c = spec["control"] if spec else "seq"
        if c in ("branch", "jump", "return"):
            return c
        if c == "syscall":
            row = syscalls.get(i.scalar("syscall") or "")
            if row and row.get("return") == "-":
                return "syscall"          # noreturn: exit / exit_group
        return "seq" if c != "call" else "call"

    for b in blocks:
        insns = prog.members_of(b.name, "insn")
        kinds = [kind_of(i) for i in insns]

        # (1) terminator must be last
        term_at = next((k for k, c in enumerate(kinds)
                        if c in _TERMINATOR_KINDS), None)
        if term_at is not None and term_at != len(insns) - 1:
            add("error", "E-CFG-LAYOUT", insns[term_at + 1].name,
                f"row after the terminator `{insns[term_at].name}` in {b.name} "
                f"— move it before the terminator or into a successor block")

        last = insns[-1] if insns else None
        ctrl = kinds[-1] if kinds else "seq"

        # terminates cross-check (declared vs actual last row)
        declared_kind = b.scalar("terminates")
        actual = ctrl if ctrl in _TERMINATOR_KINDS else "fallthrough"
        allowed = {actual} | ({"call"} if ctrl == "call" else set())
        if declared_kind and declared_kind not in allowed:
            add("error", "E-CFG-EDGE", b.name,
                f"declares `terminates {declared_kind}` but the last row "
                f"{'(' + last.name + ') ' if last else ''}is {actual}")

        # (2)/(3) fall-through adjacency
        succ = [s for s in b.values("successor") if s in names]
        if ctrl == "branch":
            tgt = last.scalar("target")
            ft = last.scalar("fallthrough")
            if ft is None:
                rest = [s for s in succ if s != tgt]
                ft = rest[0] if len(rest) == 1 else None
            if ft is None:
                add("error", "E-CFG-LAYOUT", last.name,
                    f"cannot determine the fall-through successor of {b.name}: "
                    f"declare `fallthrough <block>` on the branch or exactly "
                    f"one non-target `successor`")
            elif ft != nxt[b.name]:
                add("error", "E-CFG-LAYOUT", b.name,
                    f"falls through to {ft} but the next block in layout is "
                    f"{nxt[b.name] or 'nothing'} — reorder the blocks or make "
                    f"the edge an explicit Jump row")
        elif ctrl not in _TERMINATOR_KINDS:
            # plain end (seq/call) or an empty block: implicit fall-through
            if nxt[b.name] is None:
                add("error", "E-CFG-LAYOUT", b.name,
                    f"{fn.name} runs off its last block {b.name} without a "
                    f"terminator — end it with Return or Jump")
            elif len(succ) != 1:
                add("error", "E-CFG-LAYOUT", b.name,
                    f"falls through without a terminator but declares "
                    f"{len(succ)} successors — exactly one (the physically "
                    f"next block) is required")
            elif succ[0] != nxt[b.name]:
                add("error", "E-CFG-LAYOUT", b.name,
                    f"falls through to {succ[0]} but the next block in layout "
                    f"is {nxt[b.name]} — reorder the blocks or make the edge "
                    f"an explicit Jump row")

    # ---- successor exactness + predecessor inverse (§13 step 2, both ways) ----
    expected: dict[str, set] = {}
    for b in blocks:
        insns = prog.members_of(b.name, "insn")
        kinds = [kind_of(i) for i in insns]
        last = insns[-1] if insns else None
        ctrl = kinds[-1] if kinds else "seq"
        if ctrl == "branch":
            tgt = last.scalar("target")
            ft = last.scalar("fallthrough")
            if ft is None:
                rest = [s for s in b.values("successor")
                        if s in names and s != tgt]
                ft = rest[0] if len(rest) == 1 else None
            expected[b.name] = {x for x in (tgt, ft) if x in names}
        elif ctrl == "jump":
            expected[b.name] = {last.scalar("target")} & names
        elif ctrl in ("return", "syscall"):
            expected[b.name] = set()
        else:
            expected[b.name] = {nxt[b.name]} if nxt[b.name] else set()
    for b in blocks:
        declared = {s for s in b.values("successor") if s in names}
        for stale in sorted(declared - expected[b.name]):
            add("error", "E-CFG-EDGE", b.name,
                f"declares `successor {stale}` but the terminator cannot take "
                f"that edge — a stale edge silently widens every dataflow merge")
    computed_preds = {b.name: set() for b in blocks}
    for b in blocks:
        for s in expected[b.name]:
            computed_preds[s].add(b.name)
    for b in blocks:
        declared = {p for p in b.values("predecessor") if p in names}
        if declared and declared != computed_preds[b.name]:
            add("error", "E-CFG-EDGE", b.name,
                f"declares predecessors {sorted(declared)} but the CFG "
                f"computes {sorted(computed_preds[b.name])} — `predecessor` "
                f"must be the exact inverse of `successor` when present")


def _check_reachability(prog, fn, add) -> None:
    """W-UNREACHABLE: a block with no path from the entry along declared
    `successor` edges (DESIGN §13 / E-CFG-EDGE 'not reachable' half)."""
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    names = {b.name for b in blocks}
    entry = next((b for b in blocks if b.scalar("entry") == "yes"), blocks[0])
    succ = {b.name: [s for s in b.values("successor") if s in names] for b in blocks}
    seen = set()
    stack = [entry.name]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(succ[n])
    for b in blocks:
        if b.name not in seen:
            add("warning", "W-UNREACHABLE", b.name,
                f"block has no path from the entry of {fn.name}")


def _check_value_flow(prog, fn, ops, abi, value_names, add) -> None:
    """E-VALUE-FLOW (DESIGN §11.2): a `reads`/`returns V` must be satisfied by
    reaching definitions — V must be among the values its source register *might*
    hold here. A may-analysis (set of possible values per register, unioned at
    merges) so a benign phi (fib's epilogue: a0 ∈ {number, result}) passes, while
    a register that provably holds something else (a value clobbered by a call)
    is flagged. Unknown (empty) sets are never flagged.
    """
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    names = {b.name for b in blocks}
    abikey = fn.scalar("abi") or "linux.riscv64"
    caller_saved = set(abi.get(abikey, {}).get("callerSaved", []))
    out_regs = [row[2] for row in fn.all("out") if len(row) >= 3]
    insns = {b.name: prog.members_of(b.name, "insn") for b in blocks}
    succ = {b.name: [s for s in b.values("successor") if s in names] for b in blocks}
    preds = {b.name: [] for b in blocks}
    for b in blocks:
        for s in succ[b.name]:
            preds[s].append(b.name)

    seed: dict[str, set] = {}
    for row in fn.all("in"):
        if len(row) >= 3:
            seed.setdefault(row[2], set()).add(row[0])

    def transfer(state, blk, emit):
        st = {r: set(v) for r, v in state.items()}
        for i in insns[blk]:
            spec = ops.get(i.scalar("operation"))
            if not spec:
                continue
            srcs = _role_regs(i, spec["uses"])
            for row in i.all("reads"):
                v = row[0] if row else None
                if v in value_names:
                    poss = set().union(*(st.get(r, set()) for r in srcs)) if srcs else set()
                    if emit and poss and v not in poss:
                        add("error", "E-VALUE-FLOW", i.name,
                            f"reads {v} but {sorted(srcs)} hold {sorted(poss)}")
            # `valueBindings complete`: every source register holding a single
            # known value must be listed in this row's `reads` (the opt-in
            # exhaustiveness contract, LANGUAGE §3 — reads-side)
            if emit and any(r and r[0] == "complete"
                            for r in i.all("valueBindings")):
                declared_reads = {r[0] for r in i.all("reads") if r}
                for r in srcs:
                    poss = st.get(r, set())
                    if len(poss) == 1:
                        held = next(iter(poss))
                        if held in value_names and held not in declared_reads:
                            add("error", "E-VALUE-FLOW", i.name,
                                f"declares `valueBindings complete` but reads "
                                f"{held} (in {r}) is not listed")
            # `requires <value> in <reg>`: the value must occupy that register here
            for row in i.all("requires"):
                if len(row) >= 3 and row[1] == "in" and row[0] in value_names:
                    v, reg = row[0], row[2]
                    poss = st.get(reg, set())
                    if emit and poss and v not in poss:
                        add("error", "E-VALUE-FLOW", i.name,
                            f"requires {v} in {reg} but {reg} holds {sorted(poss)}")
            if spec["control"] == "return":
                for row in i.all("returns"):
                    v = row[0] if row else None
                    if v in value_names:
                        poss = set().union(*(st.get(r, set()) for r in out_regs)) if out_regs else set()
                        if emit and poss and v not in poss:
                            add("error", "E-VALUE-FLOW", i.name,
                                f"returns {v} but {sorted(out_regs)} hold {sorted(poss)}")
            if spec["control"] == "call":
                for r in _call_clobbers(i, caller_saved):
                    st[r] = {f"·call:{i.name}:{r}"}
            writes = [w[0] for w in i.all("writes") if w]
            dests = _role_regs(i, spec["defines"])
            if spec["control"] == "call" and writes:
                # `writes <value>` on a Call binds the callee's RESULT, which
                # arrives in the ABI return register — not in the link register
                # the op table lists as the def (DESIGN §11.2 call-result rule).
                ret_int = abi.get(abikey, {}).get("returnInteger", ["a0"])
                dests = {ret_int[0]}
            for d in dests:
                st[d] = set(writes) if writes else {f"·def:{i.name}:{d}"}
        return st

    def merge(ps):
        m: dict[str, set] = {}
        for p in ps:
            for r, v in exit_state[p].items():
                m.setdefault(r, set()).update(v)
        return m

    entry_state = {b.name: (dict(seed) if b.scalar("entry") == "yes" else {}) for b in blocks}
    exit_state = {b.name: {} for b in blocks}
    for _ in range(len(blocks) * len(blocks) + 5):  # bounded fixpoint
        changed = False
        for b in blocks:
            if b.scalar("entry") != "yes":
                entry_state[b.name] = merge(preds[b.name]) if preds[b.name] else {}
            ex = transfer(entry_state[b.name], b.name, emit=False)
            if ex != exit_state[b.name]:
                exit_state[b.name] = ex
                changed = True
        if not changed:
            break

    for b in blocks:
        transfer(entry_state[b.name], b.name, emit=True)


def _check_liveness(prog, fn, ops, abi, regs, add) -> None:
    """Forward 'must be defined on all paths' analysis (DESIGN §13 step 5).

    Delivers E-LIVE-UNDEF (use before def) and E-LIVE-RET (result undefined at
    return). Backward checks (W-DEAD, W-CLOBBER) and value-flow are deferred.
    """
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    names = {b.name for b in blocks}

    abikey = fn.scalar("abi") or "linux.riscv64"
    caller_saved = set(abi.get(abikey, {}).get("callerSaved", []))
    callee_saved = set(abi.get(abikey, {}).get("calleeSaved", []))

    def insn_def(i):
        spec = ops.get(i.scalar("operation"))
        if spec is None:
            return set()
        d = _role_regs(i, spec["defines"])
        if spec["control"] == "call":            # conservative by default,
            d |= _call_clobbers(i, caller_saved) | {"returnAddress"}
        return d                                  # narrowed by `clobbers` facts

    def insn_use(i):
        spec = ops.get(i.scalar("operation"))
        return _role_regs(i, spec["uses"]) if spec else set()

    insns = {b.name: prog.members_of(b.name, "insn") for b in blocks}
    blockdef = {b.name: set().union(*(insn_def(i) for i in insns[b.name])) if insns[b.name] else set()
                for b in blocks}

    preds = {b.name: [] for b in blocks}
    succ = {b.name: [s for s in b.values("successor") if s in names] for b in blocks}
    for b in blocks:
        for s in succ[b.name]:
            preds[s].append(b.name)

    # live-in at entry: arguments, infra regs, and the callee-saved file (those
    # hold the caller's valid values, which a function may legitimately spill).
    seed = (
        {row[2] for row in fn.all("in") if len(row) >= 3}
        | set(_SEED_ALWAYS)
        | callee_saved
    )
    is_entry = {b.name: (b.scalar("entry") == "yes") for b in blocks}

    # forward fixpoint: avail_in = intersection of preds' avail_out (entry = seed)
    avail_in = {b.name: (set(seed) if is_entry[b.name] else set(regs)) for b in blocks}
    changed = True
    while changed:
        changed = False
        for b in blocks:
            if is_entry[b.name]:
                continue
            ps = preds[b.name]
            new = set(seed) if not ps else set.intersection(
                *(avail_in[p] | blockdef[p] for p in ps)
            )
            if new != avail_in[b.name]:
                avail_in[b.name] = new
                changed = True

    out_regs = {row[2] for row in fn.all("out") if len(row) >= 3}
    for b in blocks:
        running = set(avail_in[b.name])
        for i in insns[b.name]:
            for r in insn_use(i):
                if r not in running:
                    add("error", "E-LIVE-UNDEF", i.name,
                        f"{r} used before it is defined on some path into {b.name}")
            spec = ops.get(i.scalar("operation"))
            if spec and spec["control"] == "return":
                for r in out_regs:
                    if r not in running:
                        add("error", "E-LIVE-RET", i.name,
                            f"result register {r} is undefined on some return path")
            running |= insn_def(i)


def _check_backward(prog, fn, ops, abi, add) -> None:
    """Backward liveness (DESIGN §13): W-DEAD (dead store) and W-CLOBBER (value
    live across a call in a caller-saved register). Warnings only.

    Call/EnvironmentCall are modelled conservatively: a call USES the ABI argument
    registers (or its declared `arg` facts) and CLOBBERS all caller-saved; a
    syscall uses `a7` plus its declared `arg` registers.
    """
    blocks = prog.members_of(fn.name, "block")
    if not blocks:
        return
    blocks.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
    names = {b.name for b in blocks}
    abikey = fn.scalar("abi") or "linux.riscv64"
    A = abi.get(abikey, {})
    caller_saved = set(A.get("callerSaved", []))
    callee_saved = set(A.get("calleeSaved", []))
    arg_int = A.get("argInteger", [])
    produced = {"a0", "a1", "returnAddress"}  # what a call genuinely yields

    def real_def(i):
        spec = ops.get(i.scalar("operation"))
        return _role_regs(i, spec["defines"]) if spec else set()

    def full_def(i):
        spec = ops.get(i.scalar("operation"))
        d = real_def(i)
        if spec and spec["control"] == "call":
            d |= _call_clobbers(i, caller_saved) | {"returnAddress"}
        return d

    def use(i):
        spec = ops.get(i.scalar("operation"))
        if not spec:
            return set()
        argfacts = {r[1] for r in i.all("arg") if len(r) >= 2}
        if spec["control"] == "syscall":
            return {"a7"} | argfacts
        if spec["control"] == "call":
            return argfacts  # declared args only (avoids inflating liveness)
        return _role_regs(i, spec["uses"])

    insns = {b.name: prog.members_of(b.name, "insn") for b in blocks}
    succ = {b.name: [s for s in b.values("successor") if s in names] for b in blocks}
    exit_seed = ({row[2] for row in fn.all("out") if len(row) >= 3}) | callee_saved

    live_in = {b.name: set() for b in blocks}

    def block_lo(b):
        ss = succ[b.name]
        return set(exit_seed) if not ss else set().union(*(live_in[s] for s in ss))

    changed = True
    while changed:
        changed = False
        for b in reversed(blocks):
            cur = block_lo(b)
            for i in reversed(insns[b.name]):
                cur = (cur - full_def(i)) | use(i)
            if cur != live_in[b.name]:
                live_in[b.name] = cur
                changed = True

    for b in blocks:
        cur = block_lo(b)
        for i in reversed(insns[b.name]):
            live_out_i = set(cur)
            spec = ops.get(i.scalar("operation"))
            ctrl = spec["control"] if spec else ""
            if ctrl == "call":
                for r in sorted(live_out_i & _call_clobbers(i, caller_saved)
                                - produced):
                    add("warning", "W-CLOBBER", i.name,
                        f"{r} is live across this call but in its clobber set")
            elif ctrl not in ("syscall",):
                # skip argument registers: their liveness across calls is modelled
                # only coarsely (we can't see undeclared call args), so a "dead"
                # a0-a7 write is too often a call argument we can't see
                for r in sorted(real_def(i) - live_out_i - set(arg_int)):
                    add("warning", "W-DEAD", i.name,
                        f"writes {r} but it is never used before being overwritten")
            # asserted liveOut must match computed liveness (E-LIVE-ASSERT)
            for row in i.all("liveOut"):
                if not row:
                    continue
                reg = row[0].split(":")[0]
                if reg not in live_out_i:
                    add("error", "E-LIVE-ASSERT", i.name,
                        f"declares `liveOut {row[0]}` but {reg} is not live here")
            # a declared kill means the register is dead AFTER this row
            for row in i.all("kills"):
                if row and row[0] in live_out_i:
                    add("error", "E-LIVE-ASSERT", i.name,
                        f"declares `kills {row[0]}` but it is still live after "
                        f"this row")
            cur = (cur - full_def(i)) | use(i)
            # a declared liveIn means the register is live ENTERING this row
            for row in i.all("liveIn"):
                if row and row[0].split(":")[0] not in cur:
                    add("error", "E-LIVE-ASSERT", i.name,
                        f"declares `liveIn {row[0]}` but "
                        f"{row[0].split(':')[0]} is not live entering this row")


def validate(prog: Program) -> list[Diagnostic]:
    ops = isa.load_ops()
    regs = isa.reg_names()
    formats = isa.load_formats()
    abi = isa.load_abi()
    syscalls = isa.load_syscalls()

    diags: list[Diagnostic] = []

    def add(sev, code, handle, msg):
        diags.append(Diagnostic(sev, code, handle, msg))

    # ---------- entity typing: nothing may be invisible (E-ENTITY) ----------
    # An entity with facts but no `is` row — or a typo'd type — is skipped by
    # every of_type/members_of walk: its code VANISHES from check, emit, and
    # exec with a clean bill of health (the worst finding of the 2026-06 edge
    # audit). §2.1's invariant makes this an error, not a shrug.
    for e in prog.entities.values():
        if e.type is None and e.facts:
            add("error", "E-ENTITY", e.name,
                f"has {sum(len(r) for r in e.facts.values())} fact row(s) but "
                f"no `is <type>` declaration — every tool would silently "
                f"ignore it")
        elif e.type is not None and e.type not in KNOWN_TYPES:
            add("error", "E-ENTITY", e.name,
                f"`is {e.type}` is not a known entity type — the entity would "
                f"be invisible to every walk (did you mean one of "
                f"{sorted(KNOWN_TYPES)}?)")

    blocks = {e.name for e in prog.of_type("block")}
    funcs = {e.name for e in prog.of_type("function")}
    value_ent = {e.name: e for e in prog.of_type("value")}
    values = set(value_ent)
    block_fn = {b.name: b.scalar("in") for b in prog.of_type("block")}
    slot_ent = {e.name: e for e in prog.of_type("stackSlot")}
    fn_symbols = {f.scalar("symbol", f.name) for f in prog.of_type("function")}

    _check_dup(prog, add)

    # target profile -> available extensions (E-EXT-UNAVAILABLE)
    extmap = isa.load_extmap()
    profiles = isa.load_profiles()
    progent = next(iter(prog.of_type("program")), None)
    target_name = progent.scalar("target") if progent else None
    profile_exts = None
    if target_name is not None:
        profile_exts = profiles.get(target_name)
        if profile_exts is None:
            add("error", "E-EXT-UNAVAILABLE", progent.name,
                f"unknown target profile {target_name!r} (known: "
                f"{sorted(profiles)})")

    # `program entry` must resolve to a function symbol (a misspelled entry
    # was silently ignored by check AND exec --start fell back anyway)
    for p in prog.of_type("program"):
        ent_sym = p.scalar("entry")
        if ent_sym is not None and ent_sym not in fn_symbols:
            add("error", "E-REF", p.name,
                f"`entry {ent_sym}` matches no function symbol")

    # ---------- the data contract (E-DATA) ----------
    for d in prog.of_type("data"):
        section = d.scalar("section", "data")
        typ, val, size = d.scalar("type"), d.scalar("value"), d.scalar("size")
        align = d.scalar("align")
        if section not in ("rodata", "data", "bss"):
            add("error", "E-DATA", d.name, f"unknown section {section!r}")
        if typ is not None and typ != "Bytes" and typ not in _DATA_WIDTH:
            add("error", "E-DATA", d.name,
                f"unknown data type {typ!r} (would silently emit .dword)")
        if section == "bss":
            if val is not None:
                add("error", "E-DATA", d.name,
                    "bss data cannot carry a `value` (it is reserved, not "
                    "initialized)")
            if not _is_int(size):
                add("error", "E-DATA", d.name,
                    "bss data requires an integer `size` (else it emits "
                    "`.zero None`)")
        elif val is None:
            add("error", "E-DATA", d.name,
                f"{section} data requires a `value`")
        if typ == "Bytes" and val is not None and _is_int(size) \
                and _escaped_length(val) != int(size):
            add("error", "E-DATA", d.name,
                f"declares size {size} but the Bytes literal is "
                f"{_escaped_length(val)} bytes after escapes — the emitter "
                f"trusts `size` for .size and does not recount")
        if align is not None:
            if not _is_int(align) or int(align) < 1 \
                    or (int(align) & (int(align) - 1)) != 0:
                add("error", "E-DATA", d.name,
                    f"`align {align}` must be a power of two >= 1")

    # a declared phi (`mergesFrom`, LANGUAGE §4) must name a declared value;
    # provenance facts must resolve and agree with what they point at
    insn_ent = {e.name: e for e in prog.of_type("insn")}
    for v in value_ent.values():
        for r in v.all("mergesFrom"):
            if r and r[0] not in values:
                add("error", "E-REF", v.name,
                    f"`mergesFrom {r[0]}` is not a declared value")
        vin = v.scalar("in")
        if vin is not None and vin not in funcs:
            add("error", "E-REF", v.name, f"`in {vin}` is not a function")
        db = v.scalar("definedBy")
        if db is not None:
            producer = insn_ent.get(db)
            if producer is None:
                add("error", "E-REF", v.name,
                    f"`definedBy {db}` is not an insn")
            elif v.name not in {r[0] for r in producer.all("writes") if r}:
                add("error", "E-REF", v.name,
                    f"`definedBy {db}` but that row does not `writes {v.name}`")
        si = v.scalar("storedIn")
        if si is not None:
            slot = slot_ent.get(si)
            if slot is None:
                add("error", "E-REF", v.name,
                    f"`storedIn {si}` is not a stackSlot")
            elif slot.scalar("stores") not in (None, v.name):
                add("error", "E-REF", v.name,
                    f"`storedIn {si}` but that slot stores "
                    f"{slot.scalar('stores')!r}")
        rb = v.scalar("restoredBy")
        if rb is not None and rb not in insn_ent:
            add("error", "E-REF", v.name, f"`restoredBy {rb}` is not an insn")
    slots = {e.name for e in prog.of_type("stackSlot")}
    regions = {e.name: e.scalar("kind") for e in prog.of_type("memoryRegion")}
    concurrent_regions = {e.name for e in prog.of_type("memoryRegion")
                          if e.scalar("concurrentWriters") == "yes"}

    # ---------- instruction-level structural checks ----------
    for insn in prog.of_type("insn"):
        op = insn.scalar("operation")
        spec = ops.get(op)
        if spec is None:
            add("error", "E-ISA-OPCODE", insn.name, f"unknown operation {op!r}")
            continue

        needed = {f for _, f, _, _ in _FORMATTER.parse(spec["emit"]) if f}
        for f in sorted(needed):
            if insn.scalar(f) is None:
                add("error", "E-ISA-FIELD", insn.name, f"{op} requires field `{f}`")

        for f in isa.REGISTER_FIELDS:
            v = insn.scalar(f)
            if v is not None and v not in regs:
                add("error", "E-ISA-REG", insn.name, f"`{f} {v}` is not a register")

        inb = insn.scalar("in")
        if inb is not None and inb not in blocks:
            add("error", "E-REF", insn.name, f"`in {inb}` is not a block")
        my_fn = block_fn.get(inb)
        tgt = insn.scalar("target")
        if tgt is not None and tgt not in blocks:
            add("error", "E-REF", insn.name, f"`target {tgt}` is not a block")
        elif tgt is not None and my_fn is not None \
                and block_fn.get(tgt) != my_fn:
            add("error", "E-REF", insn.name,
                f"`target {tgt}` belongs to {block_fn.get(tgt)}, not "
                f"{my_fn} — control may not jump between functions' bodies")
        off = insn.scalar("offset")
        if off is not None and not _is_int(off):
            slot = slot_ent.get(off)
            if slot is None:
                add("error", "E-REF", insn.name,
                    f"`offset {off}` is neither an integer nor a stackSlot")
            else:
                if my_fn is not None and slot.scalar("in") != my_fn:
                    add("error", "E-REF", insn.name,
                        f"`offset {off}` names a slot in "
                        f"{slot.scalar('in')}'s frame, not {my_fn}'s — that "
                        f"address is someone else's memory")
                if not _is_int(slot.scalar("offset")):
                    add("error", "E-REF", insn.name,
                        f"stackSlot {off} has no integer `offset` — the "
                        f"emitter would write `None(sp)`")

        if len(insn.all("writes")) > 1:
            add("error", "E-VALUE-FLOW", insn.name,
                "more than one `writes` row — a row binds exactly one value "
                "(the static set-union and the runtime tag would disagree)")

        imm = insn.scalar("immediate")
        if imm is not None and not _is_int(imm):
            add("error", "E-ISA-FIELD", insn.name,
                f"`immediate {imm}` is not a decimal integer — one grammar "
                f"for all tools (hex/underscores diverge between check, "
                f"emit, and exec)")

        # extension gating: the op's class must be available in the target
        if profile_exts is not None:
            ext = extmap.get(spec["class"])
            if ext and ext not in profile_exts:
                add("error", "E-EXT-UNAVAILABLE", insn.name,
                    f"{op} needs extension {ext}, which `target "
                    f"{target_name}` does not include")

        # a `syscall <name>` must exist in syscalls.tsv (its number/noreturn
        # semantics drive the layout and runtime checks)
        sc = insn.scalar("syscall")
        if sc is not None and sc not in syscalls:
            add("error", "E-REF", insn.name,
                f"`syscall {sc}` is not in syscalls.tsv")

        # an effect row that merely restates the op table, with no region
        # qualifier and no memory facts, is a derivable copy (A1 slice)
        efacts = [r for r in insn.all("effect") if r]
        if len(efacts) == 1 and len(efacts[0]) == 1 \
                and efacts[0][0] == spec["effect"] and spec["effect"] != "none" \
                and not insn.has("memory"):
            add("error", "E-DERIVABLE", insn.name,
                f"`effect {spec['effect']}` restates the op table with no "
                f"qualifier — derivable; add a region or drop the row")

        # emitKind: the table already knows pseudo/real — a matching
        # declaration is a zero-information copy (A1), a mismatched one a lie
        ek = insn.scalar("emitKind")
        if ek is not None:
            derived = "pseudo" if spec["class"] == "pseudo" else "real"
            if ek == derived:
                add("error", "E-DERIVABLE", insn.name,
                    f"`emitKind {ek}` restates the op table — derivable copy")
            else:
                add("error", "E-ISA-FIELD", insn.name,
                    f"`emitKind {ek}` contradicts the op table ({derived})")

        # clobbers facts must name registers (or the literal `callerSaved`)
        for row in insn.all("clobbers"):
            for tok in row:
                if tok != "callerSaved" and tok not in regs:
                    add("error", "E-ISA-REG", insn.name,
                        f"`clobbers {tok}` is not a register")
        # effect/memory region qualifiers must resolve to declared regions
        for r in insn.all("effect"):
            if len(r) >= 2 and r[0].split(".")[0] in ("memory", "device") \
                    and r[1] not in regions:
                add("error", "E-REF", insn.name,
                    f"`effect {r[0]} {r[1]}` names an undeclared memoryRegion")
        for r in insn.all("memory"):
            if len(r) >= 2 and r[0] == "region" and r[1] not in regions:
                add("error", "E-REF", insn.name,
                    f"`memory region {r[1]}` is not a declared memoryRegion")

        # `writes` on a row that defines no register binds nothing (grammar rule)
        if insn.has("writes") and spec["control"] != "call" \
                and not _role_regs(insn, spec["defines"]):
            add("error", "E-VALUE-FLOW", insn.name,
                "`writes` on an operation that defines no register (or "
                "discards to `zero`) — the binding cannot exist")

        for pred in ("reads", "writes", "returns", "requires"):
            for r in insn.all(pred):
                if not r:
                    continue
                if r[0] in regs:
                    # naming a register restates the op table (§11.2) — derivable
                    add("error", "E-DERIVABLE", insn.name,
                        f"`{pred} {r[0]}` names a register; use a value name "
                        f"(register use is already in the op table)")
                elif r[0] not in values:
                    add("error", "E-REF", insn.name,
                        f"`{pred} {r[0]}` is not a declared value")

        ow = _op_width(spec)
        if ow is not None:
            for r in insn.all("writes"):
                v = value_ent.get(r[0]) if r else None
                vw = _value_width(v) if v else None
                if vw is not None and vw != ow:
                    add("error", "E-TYPE", insn.name,
                        f"writes {r[0]} ({v.scalar('type') or vw} bytes={vw}) "
                        f"but {op} produces {ow} bytes")

        imm = insn.scalar("immediate")
        if _is_int(imm):
            fmt = "shamt6" if spec["class"] == "shift" else spec["fmt"]
            frow = formats.get(fmt)
            if frow and frow["immmin"] != "-":
                lo, hi = int(frow["immmin"]), int(frow["immmax"])
                if not (lo <= int(imm) <= hi):
                    add("error", "E-IMM-RANGE", insn.name,
                        f"immediate {imm} out of range [{lo},{hi}] for {fmt}")

    # ---------- block-level checks ----------
    for blk in prog.of_type("block"):
        inf = blk.scalar("in")
        if inf is not None and inf not in funcs:
            add("error", "E-REF", blk.name, f"`in {inf}` is not a function")
        for s in blk.values("successor"):
            if s in blocks and block_fn.get(s) != blk.scalar("in"):
                add("error", "E-REF", blk.name,
                    f"`successor {s}` belongs to {block_fn.get(s)}, not "
                    f"{blk.scalar('in')} — CFG edges stay within a function")

        insns = prog.members_of(blk.name, "insn")
        ords = [i.scalar("ordinal") for i in insns]
        if any(o is not None for o in ords) and any(o is None for o in ords):
            add("error", "E-ORDER-MIXED", blk.name,
                "block mixes ordinaled and bare instructions")
        seen_ords: dict[str, str] = {}
        for i in insns:
            o = i.scalar("ordinal")
            if o is None:
                continue
            if not _is_int(o):
                add("error", "E-ORDER-KEY", i.name,
                    f"`ordinal {o}` is not a decimal integer")
            elif o in seen_ords:
                add("error", "E-ORDER-KEY", i.name,
                    f"`ordinal {o}` duplicates {seen_ords[o]}'s — order "
                    f"would be ambiguous")
            else:
                seen_ords[o] = i.name

        succ = {r[0] for r in blk.all("successor") if r}
        for i in insns:
            t = i.scalar("target")
            if t and t in blocks and t not in succ:
                add("error", "E-CFG-EDGE", blk.name,
                    f"`{i.name}` targets {t}, not a declared successor of {blk.name}")

    # ---------- function-level checks ----------
    for fn in prog.of_type("function"):
        for r in fn.all("stack"):
            if len(r) >= 2 and r[0] == "bytes" and _is_int(r[1]):
                n = int(r[1])
                if n % 16 != 0:
                    add("error", "E-ABI-ALIGN", fn.name,
                        f"stack frame {n} is not 16-byte aligned")

        if fn.scalar("leaf") == "yes":
            for blk in prog.members_of(fn.name, "block"):
                for i in prog.members_of(blk.name, "insn"):
                    s = ops.get(i.scalar("operation"))
                    if s and s["control"] == "call":
                        add("error", "E-LEAF", fn.name,
                            f"declared `leaf yes` but `{i.name}` is a call")

        declared = {r[0] for r in fn.all("effect") if r and r[0] != "none"}
        observed = _observed_effects(prog, fn, ops, regions)
        if declared != observed:
            parts = []
            if observed - declared:
                parts.append(f"performs {sorted(observed - declared)} not declared")
            if declared - observed:
                parts.append(f"declares {sorted(declared - observed)} not performed")
            add("error", "E-EFFECT", fn.name, "; ".join(parts))

        for pred in ("preserves", "usesCalleeSaved"):
            for r in fn.all(pred):
                if r and r[0] not in regs:
                    add("error", "E-ISA-REG", fn.name,
                        f"`{pred} {r[0]}` is not a register")

        frame = next((int(r[1]) for r in fn.all("stack")
                      if len(r) >= 2 and r[0] == "bytes" and _is_int(r[1])), None)
        if frame is not None:
            for slot in prog.members_of(fn.name, "stackSlot"):
                off = slot.scalar("offset")
                if _is_int(off) and not (0 <= int(off) < frame):
                    # ERROR, not warning: a slot outside the frame reads/writes
                    # the CALLER's memory — silent corruption that can pass
                    # behavioral tests when the victim slot is unused (found by
                    # the mutation tier, DESIGN §19)
                    add("error", "E-SLOT-RANGE", slot.name,
                        f"offset {off} is outside the {frame}-byte frame "
                        f"(the access lands in the caller's frame)")

        for r in fn.all("effect"):
            if len(r) >= 2 and r[0].split(".")[0] in ("memory", "device") \
                    and r[1] not in regions:
                add("error", "E-REF", fn.name,
                    f"`effect {r[0]} {r[1]}` names an undeclared memoryRegion")

        _check_preserve(prog, fn, ops, abi, add)
        _check_restore_paths(prog, fn, ops, abi, syscalls, add)
        _check_spill_rows(prog, fn, add)
        _check_lint(prog, fn, ops, abi, add)
        _check_rmw(prog, fn, ops, concurrent_regions, add)
        _check_stack(prog, fn, ops, syscalls, add)
        _check_layout(prog, fn, ops, syscalls, add)
        _check_liveness(prog, fn, ops, abi, regs, add)
        _check_backward(prog, fn, ops, abi, add)
        _check_value_flow(prog, fn, ops, abi, values, add)
        _check_reachability(prog, fn, add)

    return diags
