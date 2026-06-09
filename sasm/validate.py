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
    if cls in ("arith", "logic", "shift", "compare", "muldiv", "cond"):
        return 4 if sem.endswith("Word") or "Word" in sem else 8
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


def _is_int(s: str | None) -> bool:
    if s is None:
        return False
    try:
        int(s)
        return True
    except ValueError:
        return False


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
        for i in insns:
            tgt = i.scalar("target")
            if entry and tgt == entry:
                add("error", "E-CFG-LAYOUT", i.name,
                    f"targets the entry block {entry}: its label is suppressed "
                    f"by the emitter (§15.1) — branch to a non-entry block")

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
                for r in caller_saved:
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
        if spec["control"] == "call":            # conservative: a call lands a
            d |= caller_saved | {"returnAddress"}  # value in every caller-saved reg
        return d

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
            d |= caller_saved | {"returnAddress"}
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
                for r in sorted(live_out_i & caller_saved - produced):
                    add("warning", "W-CLOBBER", i.name,
                        f"{r} is live across this call but caller-saved (clobbered)")
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
            cur = (cur - full_def(i)) | use(i)


def validate(prog: Program) -> list[Diagnostic]:
    ops = isa.load_ops()
    regs = isa.reg_names()
    formats = isa.load_formats()
    abi = isa.load_abi()
    syscalls = isa.load_syscalls()

    diags: list[Diagnostic] = []

    def add(sev, code, handle, msg):
        diags.append(Diagnostic(sev, code, handle, msg))

    blocks = {e.name for e in prog.of_type("block")}
    funcs = {e.name for e in prog.of_type("function")}
    value_ent = {e.name: e for e in prog.of_type("value")}
    values = set(value_ent)
    slots = {e.name for e in prog.of_type("stackSlot")}
    regions = {e.name: e.scalar("kind") for e in prog.of_type("memoryRegion")}

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
        tgt = insn.scalar("target")
        if tgt is not None and tgt not in blocks:
            add("error", "E-REF", insn.name, f"`target {tgt}` is not a block")
        off = insn.scalar("offset")
        if off is not None and not _is_int(off) and off not in slots:
            add("error", "E-REF", insn.name,
                f"`offset {off}` is neither an integer nor a stackSlot")
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

        insns = prog.members_of(blk.name, "insn")
        ords = [i.scalar("ordinal") for i in insns]
        if any(o is not None for o in ords) and any(o is None for o in ords):
            add("error", "E-ORDER-MIXED", blk.name,
                "block mixes ordinaled and bare instructions")

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
                    add("warning", "W-SLOT", slot.name,
                        f"offset {off} is outside the {frame}-byte frame")

        _check_preserve(prog, fn, ops, abi, add)
        _check_layout(prog, fn, ops, syscalls, add)
        _check_liveness(prog, fn, ops, abi, regs, add)
        _check_backward(prog, fn, ops, abi, add)
        _check_value_flow(prog, fn, ops, abi, values, add)
        _check_reachability(prog, fn, add)

    return diags
