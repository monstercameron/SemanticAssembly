"""Taint-tracking interpreter — executable semantics for `.sasm` (DESIGN §19).

Executes the FACT ROWS directly (never the emitted `.s`): a tiny RV64IM machine
where every register and every 8-byte memory cell carries a shadow **value
tag** alongside its concrete bits. The dangerous S-check facts stop being
analytically derived and become **observed**:

  reads v        -> the source register's tag either is `v` or it isn't, here
  writes v       -> stamps the destination's tag (a Call stamps the ABI return reg)
  liveOut r:v    -> snapshot r at the call row, compare at the matching return
  effect ...     -> the activation either touched non-stack memory / called /
                    trapped, or it didn't (internal-effect rule applied)
  preserves r    -> callee-saved bits at entry == bits at return, per activation
  stack bytes N  -> the first sp adjustment either is -N or it isn't
  successor ...  -> every executed control transfer is checked against the CFG

Violations are reported with the runtime codes of DESIGN §18.3 (R-*), the same
diagnostic shape as the static validator. Results are TRACE-SCOPED (§18.1): a
clean run proves the asserted contracts held on this path under this input —
nothing more — so `coverage()` reports what the run did NOT exercise.

The return address is a synthetic token, not a fake integer: `Call` mints one,
`Return` resolves it. Corrupt `ra` (the classic clobber) and the machine halts
with R-ABI-PRESERVE naming the row, exactly like real silicon would crash —
but with a diagnosis instead of a hexdump.

Semantics policy (mirrors the static may-form, DESIGN §18.3): a def WITHOUT a
`writes` fact sets the destination tag to unknown (None). `reads v` errors only
when a source holds a DIFFERENT tag; all-unknown sources pass and are counted
as unconfirmed in coverage — so a validator-clean file with legitimate
unannotated re-derivations never fails at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import isa
from .model import Entity, Program
from .validate import Diagnostic

MASK64 = (1 << 64) - 1

STACK_TOP = 0x7FFF_0000
STACK_LIMIT = STACK_TOP - 0x0010_0000        # 1 MiB of stack
DATA_BASE = 0x1000_0000
HEAP_BASE = 0x3000_0000
TOKEN_BASE = 0x7000_0000                     # synthetic return-address tokens

_SYS_WRITE, _SYS_EXIT, _SYS_EXIT_GROUP = 64, 93, 94

_LOAD_WIDTH = {"LoadByte": (1, True), "LoadHalfword": (2, True),
               "LoadWord": (4, True), "LoadDoubleword": (8, True),
               "LoadByteUnsigned": (1, False), "LoadHalfwordUnsigned": (2, False),
               "LoadWordUnsigned": (4, False)}
_STORE_WIDTH = {"StoreByte": 1, "StoreHalfword": 2, "StoreWord": 4,
                "StoreDoubleword": 8}


def _signed(v: int, bits: int = 64) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def _sext32(v: int) -> int:
    return _signed(v, 32) & MASK64


def _unescape(s: str) -> bytes:
    """Assembler-level escapes for `Bytes` data (the parser keeps them literal)."""
    out, i = bytearray(), 0
    esc = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, '"': 34}
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in esc:
            out.append(esc[s[i + 1]]); i += 2
        else:
            out.append(ord(s[i])); i += 1
    return bytes(out)


class ExecError(Exception):
    pass


@dataclass
class _Activation:
    fn: Entity
    entry_sp: int
    saved_callee: dict
    ret_token: int
    observed: set = field(default_factory=set)
    frame_checked: bool = False
    # liveOut snapshots taken at a call row, verified at the first row executed
    # after the call returns to this activation: [(call_handle, reg, value)]
    pending_live: list = field(default_factory=list)


class Machine:
    """One program, one machine. Drive it with call() / run_start()."""

    def __init__(self, prog: Program):
        self.prog = prog
        self.ops = isa.load_ops()
        self.abi = isa.load_abi()
        self.syscalls = {r["number"]: r for r in isa.load_syscalls().values()}
        self.regs: dict[str, int] = {r: 0 for r in isa.reg_names()}
        self.tags: dict[str, str | None] = {r: None for r in self.regs}
        self.mem: dict[int, int] = {}            # addr -> byte
        self.memtags: dict[int, str | None] = {}  # 8-aligned addr -> tag
        self.stdout = bytearray()
        self.exit_code: int | None = None
        self.diags: list[Diagnostic] = []
        self._seen_diags: set = set()
        self.steps = 0
        self._heap = HEAP_BASE
        self._tokens: dict[int, tuple] = {}      # ret token -> resume pc (or None=host)
        self._next_token = TOKEN_BASE
        # coverage
        self.blocks_run: set[str] = set()
        self.reads_confirmed: set[str] = set()
        self.reads_unknown: set[str] = set()
        self.liveout_checked: set[str] = set()
        self.fns_run: set[str] = set()

        self.regions = {e.name: e.scalar("kind")
                        for e in prog.of_type("memoryRegion")}
        # declared phis (LANGUAGE §4 `mergesFrom`): value -> the set of value
        # names it may legitimately be on some path (transitive, incl. itself)
        self.merges: dict[str, set] = {}
        for v in prog.of_type("value"):
            acc = {v.name} | {r[0] for r in v.all("mergesFrom") if r}
            self.merges[v.name] = acc

        self.fn_by_symbol: dict[str, Entity] = {}
        self.blocks: dict[str, list[Entity]] = {}
        self.insns: dict[str, list[Entity]] = {}
        for fn in prog.of_type("function"):
            self.fn_by_symbol[fn.scalar("symbol", fn.name)] = fn
            bs = prog.members_of(fn.name, "block")
            bs.sort(key=lambda b: (b.scalar("entry") != "yes", b.order))
            self.blocks[fn.name] = bs
            for b in bs:
                ins = prog.members_of(b.name, "insn")
                if ins and all(i.scalar("ordinal") is not None for i in ins):
                    ins = sorted(ins, key=lambda i: int(i.scalar("ordinal")))
                self.insns[b.name] = ins
        self.symbols: dict[str, int] = {}
        self._place_data()
        self.regs["stackPointer"] = STACK_TOP
        self.regs["zero"] = 0

    # ------------------------------------------------------------ memory

    def _place_data(self) -> None:
        """Mirror GAS layout: entities are CONTIGUOUS in declaration order with
        no implicit padding (a `.word` follows the previous byte); only an
        explicit `align` fact pads — so table-style data (consecutive Int32
        rows addressed from the first label) has identical addresses here and
        in the emitted `.s`."""
        addr = DATA_BASE
        for d in self.prog.of_type("data"):
            align = int(d.scalar("align", "1") or 1)
            addr = (addr + align - 1) // align * align
            self.symbols[d.name] = addr
            typ, val, size = d.scalar("type"), d.scalar("value"), d.scalar("size")
            if val is None:                       # bss reservation
                n = int(size or 0)
                for k in range(n):
                    self.mem[addr + k] = 0
                addr += max(n, 1)
            elif typ == "Bytes":
                bs = _unescape(val)
                for k, byte in enumerate(bs):
                    self.mem[addr + k] = byte
                addr += len(bs)
            else:
                width = {"Int8": 1, "Nat8": 1, "Boolean": 1, "Int16": 2, "Nat16": 2,
                         "Int32": 4, "Nat32": 4}.get(typ, 8)
                self._store(addr, int(val) & MASK64, width)
                addr += width

    def _load(self, addr: int, width: int, signed: bool) -> int:
        v = 0
        for k in range(width):
            v |= self.mem.get(addr + k, 0) << (8 * k)
        if signed:
            v = _signed(v, width * 8) & MASK64
        return v

    def _store(self, addr: int, value: int, width: int) -> None:
        for k in range(width):
            self.mem[addr + k] = (value >> (8 * k)) & 0xFF

    def alloc_int64_array(self, values: list[int], tag: str | None = None) -> int:
        """Host helper: place an Int64 array on the synthetic heap, return base."""
        base = self._heap
        for i, v in enumerate(values):
            self._store(base + 8 * i, v & MASK64, 8)
            self.memtags[base + 8 * i] = tag
        self._heap = (base + 8 * len(values) + 15) // 16 * 16
        return base

    def read_int64_array(self, base: int, count: int) -> list[int]:
        return [_signed(self._load(base + 8 * i, 8, False)) for i in range(count)]

    def _is_stack(self, addr: int) -> bool:
        return STACK_LIMIT <= addr <= STACK_TOP

    # ------------------------------------------------------------ helpers

    def _diag(self, sev: str, code: str, handle: str, msg: str) -> None:
        # dedupe: a loop hitting the same violation 10^4 times is one finding
        key = (sev, code, handle, msg)
        if key not in self._seen_diags:
            self._seen_diags.add(key)
            self.diags.append(Diagnostic(sev, code, handle, msg))

    def _reg(self, insn: Entity, fld: str) -> str:
        r = insn.scalar(fld)
        if r is None:
            raise ExecError(f"{insn.name}: missing field `{fld}`")
        return r

    def _get(self, reg: str) -> int:
        return 0 if reg == "zero" else self.regs[reg]

    def _set(self, reg: str, value: int, tag: str | None) -> None:
        if reg == "zero":
            return
        self.regs[reg] = value & MASK64
        self.tags[reg] = tag

    def _writes_tag(self, insn: Entity) -> str | None:
        ws = [w[0] for w in insn.all("writes") if w]
        return ws[0] if ws else None

    def _observe_access(self, insn, act, default_token: str, addr: int) -> None:
        """Record a memory access's OBSERVABLE effect, mirroring the static
        derivation (validate._observed_effects): the row's own effect facts
        refine the table default; stack-internal traffic is not observable
        (LANGUAGE §10). Also checks the declared region against where the
        access actually landed — a `region` fact whose kind disagrees with
        the concrete address is a lie, caught here."""
        facts = [r[0] for r in insn.all("effect") if r]
        effs = facts if facts else [default_token]
        region = None
        for r in insn.all("memory"):
            if len(r) >= 2 and r[0] == "region":
                region = r[1]
        kind = self.regions.get(region)
        on_stack = self._is_stack(addr)
        if kind == "stack" and not on_stack:
            self._diag("error", "R-EFFECT", insn.name,
                       f"declares `memory region {region}` (stack) but the "
                       f"access landed at {addr:#x}, outside the stack")
        if kind not in (None, "stack") and on_stack:
            self._diag("error", "R-EFFECT", insn.name,
                       f"declares `memory region {region}` ({kind}) but the "
                       f"access landed on the stack at {addr:#x}")
        internal = kind == "stack" and on_stack
        if internal:
            return
        for e in effs:
            if e in ("none", "stack.allocate", "stack.free"):
                continue
            if e in ("memory.read", "memory.write") and on_stack and region is None:
                continue          # unannotated stack traffic stays internal
            act.observed.add(e)

    def _check_reads(self, insn: Entity, srcs: list[str]) -> None:
        for row in insn.all("reads"):
            if not row:
                continue
            v = row[0]
            ok = self.merges.get(v, {v})        # declared phis satisfy the read
            held = [self.tags[s] for s in srcs if s != "zero"]
            if any(t in ok for t in held):
                self.reads_confirmed.add(insn.name)
            elif any(t is not None for t in held):
                self._diag("error", "R-VALUE-FLOW", insn.name,
                           f"reads {v} but {srcs} hold {held} on this trace")
            else:
                self.reads_unknown.add(insn.name)

    # ------------------------------------------------------------ entry points

    def call(self, name: str, args: list[int], max_steps: int = 5_000_000) -> int:
        """Call a function (handle or symbol) with integer args; return a0."""
        ent = self.prog.get(name)
        fn = ent if ent is not None and ent.type == "function" \
            else self.fn_by_symbol.get(name)
        if fn is None:
            raise ExecError(f"no function named {name!r}")
        arg_regs = self.abi.get(fn.scalar("abi") or "linux.riscv64",
                                {}).get("argInteger", ["a0"])
        for i, a in enumerate(args):
            self._set(arg_regs[i], a & MASK64, None)
        # tag the declared parameters so reads can confirm from row one
        for row in fn.all("in"):
            if len(row) >= 3:
                self.tags[row[2]] = row[0]
        tok = self._mint_token(None)
        self.regs["returnAddress"] = tok
        self._run(fn, tok, max_steps)
        return _signed(self._get("a0"))

    def run_start(self, max_steps: int = 5_000_000) -> int:
        """Run the program entry (_start style); returns the exit code."""
        progent = next(iter(self.prog.of_type("program")), None)
        sym = progent.scalar("entry") if progent else None
        fn = self.fn_by_symbol.get(sym or "_start")
        if fn is None:  # fall back: the only function
            fns = self.prog.of_type("function")
            if len(fns) != 1:
                raise ExecError("no program entry and multiple functions")
            fn = fns[0]
        tok = self._mint_token(None)
        self.regs["returnAddress"] = tok
        self._run(fn, tok, max_steps)
        return self.exit_code if self.exit_code is not None else 0

    def _mint_token(self, resume) -> int:
        t = self._next_token
        self._next_token += 16
        self._tokens[t] = resume
        return t

    # ------------------------------------------------------------ the loop

    def _enter(self, fn: Entity, tok: int) -> _Activation:
        abikey = fn.scalar("abi") or "linux.riscv64"
        callee = self.abi.get(abikey, {}).get("calleeSaved", [])
        act = _Activation(fn=fn, entry_sp=self.regs["stackPointer"],
                          saved_callee={r: self.regs[r] for r in callee},
                          ret_token=tok)
        self.fns_run.add(fn.name)
        return act

    def _leave(self, act: _Activation, at: str) -> None:
        fn = act.fn
        if self.regs["stackPointer"] != act.entry_sp:
            self._diag("error", "R-ABI-PRESERVE", at,
                       f"{fn.name}: sp at return is {self.regs['stackPointer']:#x}, "
                       f"entry was {act.entry_sp:#x} — frame not freed")
        for r, v in act.saved_callee.items():
            if r != "stackPointer" and self.regs[r] != v:
                self._diag("error", "R-ABI-PRESERVE", at,
                           f"{fn.name}: callee-saved {r} changed across the "
                           f"activation ({v:#x} -> {self.regs[r]:#x})")
        declared = {r[0] for r in fn.all("effect") if r and r[0] != "none"}
        extra = act.observed - declared
        if extra:
            self._diag("error", "R-EFFECT", at,
                       f"{fn.name}: performed {sorted(extra)} not covered by "
                       f"declared effects {sorted(declared) or ['none']}")

    def _run(self, fn0: Entity, tok0: int, max_steps: int) -> None:
        stack: list[_Activation] = [self._enter(fn0, tok0)]
        bs = self.blocks[fn0.name]
        if not bs:
            raise ExecError(f"{fn0.name}: no blocks")
        pc = (fn0.name, 0, 0)

        while True:
            if self.exit_code is not None:
                return
            self.steps += 1
            if self.steps > max_steps:
                raise ExecError(f"step budget exceeded ({max_steps})")
            fname, bi, ii = pc
            blocks = self.blocks[fname]
            block = blocks[bi]
            self.blocks_run.add(block.name)
            ins = self.insns[block.name]

            if ii >= len(ins):                       # implicit fall-through
                if bi + 1 >= len(blocks):
                    raise ExecError(f"{fname}: ran off the last block {block.name}")
                self._edge(block, blocks[bi + 1].name)
                pc = (fname, bi + 1, 0)
                continue

            insn = ins[ii]
            act = stack[-1]
            nxt = self._step(insn, block, blocks, bi, ii, act, stack)
            if nxt == "halt":
                return
            if nxt is not None:
                pc = nxt
            else:
                pc = (fname, bi, ii + 1)

    def _edge(self, frm: Entity, to: str) -> None:
        succ = frm.values("successor")
        if succ and to not in succ:
            self._diag("error", "R-CFG-EDGE", frm.name,
                       f"executed transfer {frm.name} -> {to} is not a declared successor")

    def _block_index(self, blocks: list[Entity], name: str) -> int:
        for i, b in enumerate(blocks):
            if b.name == name:
                return i
        raise ExecError(f"branch target {name!r} is not a block here")

    # ------------------------------------------------------------ one instruction

    def _step(self, insn, block, blocks, bi, ii, act, stack):
        op = insn.scalar("operation")
        spec = self.ops.get(op)
        if spec is None:
            raise ExecError(f"{insn.name}: unknown operation {op!r}")
        fname = act.fn.name
        wtag = self._writes_tag(insn)

        # resolve pending liveOut checks: this is the first row this activation
        # executes after its in-flight call returned
        if act.pending_live:
            for call_handle, reg, val in act.pending_live:
                if self.regs[reg] != val:
                    self._diag("error", "R-LIVE-OUT", call_handle,
                               f"{reg} changed across the call "
                               f"({val:#x} -> {self.regs[reg]:#x})")
            act.pending_live.clear()

        def src(fld):
            return self._get(self._reg(insn, fld))

        def offset_of():
            off = insn.scalar("offset")
            slot = self.prog.get(off) if off else None
            if slot is not None and slot.type == "stackSlot":
                return int(slot.scalar("offset"))
            return int(off)

        cls = spec["class"]

        # ---------- arithmetic / logic / shifts / compares / muldiv ----------
        if cls in ("arith", "logic", "shift", "compare", "muldiv", "cond") \
                or op in ("Move",):
            a = src("firstSource") if spec["uses"] and "firstSource" in spec["uses"] else 0
            b = src("secondSource") if "secondSource" in spec["uses"] else None
            imm = int(insn.scalar("immediate")) if insn.scalar("immediate") is not None else None
            self._check_reads(insn, [insn.scalar(f) for f in
                                     ("firstSource", "secondSource") if insn.scalar(f)])
            r = self._alu(op, insn, a, b, imm)
            dest = self._reg(insn, "destination")
            # frame-size contract: the first sp adjustment must match `stack bytes`
            if dest == "stackPointer" and insn.scalar("firstSource") == "stackPointer" \
                    and imm is not None and imm < 0 and not act.frame_checked:
                act.frame_checked = True
                declared = next((int(x[1]) for x in act.fn.all("stack")
                                 if len(x) >= 2 and x[0] == "bytes"), None)
                if declared is not None and -imm != declared:
                    self._diag("error", "R-ABI-FRAME", insn.name,
                               f"{fname}: allocates {-imm} bytes but declares "
                               f"`stack bytes {declared}`")
            self._set(dest, r, wtag if wtag else
                      (self.tags.get(insn.scalar("firstSource"))
                       if op == "Move" else None))
            return None

        # ---------- constants ----------
        if op == "LoadImmediate":
            self._set(self._reg(insn, "destination"),
                      int(insn.scalar("immediate")) & MASK64, wtag)
            return None
        if op == "LoadAddress":
            sym = insn.scalar("symbol")
            if sym not in self.symbols:
                raise ExecError(f"{insn.name}: unknown symbol {sym!r}")
            self._set(self._reg(insn, "destination"), self.symbols[sym], wtag)
            return None
        if op == "NoOperation":
            return None

        # ---------- memory ----------
        if op in _LOAD_WIDTH:
            base = self._reg(insn, "base")
            self._check_reads(insn, [base])
            addr = (self._get(base) + offset_of()) & MASK64
            width, signed = _LOAD_WIDTH[op]
            v = self._load(addr, width, signed)
            tag = wtag if wtag else (self.memtags.get(addr) if width == 8 else None)
            self._set(self._reg(insn, "destination"), v, tag)
            self._observe_access(insn, act, "memory.read", addr)
            return None
        if op in _STORE_WIDTH:
            base = self._reg(insn, "base")
            val_reg = self._reg(insn, "secondSource")
            self._check_reads(insn, [val_reg, base])
            addr = (self._get(base) + offset_of()) & MASK64
            width = _STORE_WIDTH[op]
            self._store(addr, self._get(val_reg), width)
            if width == 8:
                self.memtags[addr] = self.tags.get(val_reg)
            self._observe_access(insn, act, "memory.write", addr)
            return None

        # ---------- branches ----------
        if spec["control"] == "branch":
            taken = self._branch_taken(op, insn)
            self._check_reads(insn, [insn.scalar(f) for f in
                                     ("firstSource", "secondSource") if insn.scalar(f)])
            if taken:
                tgt = insn.scalar("target")
                self._edge(block, tgt)
                return (act.fn.name, self._block_index(blocks, tgt), 0)
            if bi + 1 >= len(blocks):
                raise ExecError(f"{block.name}: branch falls off the function")
            self._edge(block, blocks[bi + 1].name)
            return (act.fn.name, bi + 1, 0)

        if op == "Jump":
            tgt = insn.scalar("target")
            self._edge(block, tgt)
            return (act.fn.name, self._block_index(blocks, tgt), 0)

        # ---------- calls / returns ----------
        if op == "Call":
            if self.regs["stackPointer"] % 16:
                self._diag("error", "R-ABI-ALIGN", insn.name,
                           f"sp is {self.regs['stackPointer']:#x} at a call "
                           f"(not 16-byte aligned)")
            act.observed.add("call")
            # snapshot declared liveOut for verification at the resume point
            pending = []
            for row in insn.all("liveOut"):
                if row and ":" in row[0]:
                    reg, val = row[0].split(":", 1)
                    if self.tags.get(reg) not in (val, None):
                        self._diag("error", "R-LIVE-OUT", insn.name,
                                   f"declares liveOut {reg}:{val} but {reg} holds "
                                   f"{self.tags.get(reg)} on this trace")
                    pending.append((reg, self.regs[reg]))
                    self.liveout_checked.add(insn.name)
            sym = insn.scalar("symbol")
            callee = self.fn_by_symbol.get(sym)
            if callee is None:
                raise ExecError(f"{insn.name}: call target {sym!r} is not in this "
                                f"program (external calls are unsupported in exec)")
            tok = self._mint_token((act.fn.name, bi, ii + 1))
            self._set("returnAddress", tok, None)
            for reg, val in pending:
                act.pending_live.append((insn.name, reg, val))
            new_act = self._enter(callee, tok)
            # parameter tags for the callee
            for row in callee.all("in"):
                if len(row) >= 3:
                    self.tags[row[2]] = row[0]
            stack.append(new_act)
            return (callee.name, 0, 0)

        if op == "Return":
            tok = self.regs["returnAddress"]
            # tokens are single-use: a second return through the same token is
            # exactly the clobbered-ra bug (ret to a stale frame's address)
            resume = self._tokens.pop(tok, "·invalid")
            if resume == "·invalid":
                self._diag("error", "R-ABI-PRESERVE", insn.name,
                           f"{act.fn.name}: returnAddress holds {tok:#x}, not a "
                           f"live return token — ra was clobbered and not restored")
                return "halt"
            self._leave(act, insn.name)
            for row in insn.all("returns"):
                if row:
                    out_regs = [r[2] for r in act.fn.all("out") if len(r) >= 3]
                    held = [self.tags.get(r) for r in out_regs]
                    ok = self.merges.get(row[0], {row[0]})
                    if any(t in ok for t in held):
                        self.reads_confirmed.add(insn.name)
                    elif any(t is not None for t in held):
                        self._diag("error", "R-VALUE-FLOW", insn.name,
                                   f"returns {row[0]} but {out_regs} hold {held} "
                                   f"— a legitimate merge needs a declared "
                                   f"`mergesFrom` (LANGUAGE §4)")
                    else:
                        self.reads_unknown.add(insn.name)
            stack.pop()
            if resume is None:
                return "halt"                      # back to the host
            rf, rbi, rii = resume
            return resume

        # ---------- syscalls ----------
        if op == "EnvironmentCall":
            act.observed.add("syscall")
            num = str(_signed(self._get("a7")))
            row = self.syscalls.get(num)
            name = insn.scalar("syscall")
            if name and row and row["name"] != name:
                self._diag("error", "R-EFFECT", insn.name,
                           f"`syscall {name}` declared but a7 holds {num} "
                           f"({row['name'] if row else 'unknown'})")
            if num == str(_SYS_WRITE):
                buf, ln = self._get("a1"), self._get("a2")
                self.stdout += bytes(self.mem.get(buf + k, 0) for k in range(ln))
                self._set("a0", ln, None)
                return None
            if num in (str(_SYS_EXIT), str(_SYS_EXIT_GROUP)):
                self.exit_code = _signed(self._get("a0")) & 0xFF
                return "halt"
            raise ExecError(f"{insn.name}: unsupported syscall {num}")

        raise ExecError(f"{insn.name}: operation {op!r} not supported by exec "
                        f"(class {cls})")

    # ------------------------------------------------------------ ALU / branches

    def _alu(self, op, insn, a, b, imm):
        sa, sb = _signed(a), _signed(b) if b is not None else None
        if op == "Add": return (a + b) & MASK64
        if op == "Subtract": return (a - b) & MASK64
        if op == "AddImmediate": return (a + imm) & MASK64
        if op == "AddWord": return _sext32(a + b)
        if op == "SubtractWord": return _sext32(a - b)
        if op == "AddImmediateWord": return _sext32(a + imm)
        if op == "And": return a & b
        if op == "Or": return a | b
        if op == "ExclusiveOr": return a ^ b
        if op == "AndImmediate": return a & (imm & MASK64)
        if op == "OrImmediate": return a | (imm & MASK64)
        if op == "ExclusiveOrImmediate": return a ^ (imm & MASK64)
        if op == "ShiftLeftLogical": return (a << (b & 63)) & MASK64
        if op == "ShiftRightLogical": return a >> (b & 63)
        if op == "ShiftRightArithmetic": return (sa >> (b & 63)) & MASK64
        if op == "ShiftLeftLogicalImmediate": return (a << (imm & 63)) & MASK64
        if op == "ShiftRightLogicalImmediate": return a >> (imm & 63)
        if op == "ShiftRightArithmeticImmediate": return (sa >> (imm & 63)) & MASK64
        if op == "SetLessThan": return 1 if sa < sb else 0
        if op == "SetLessThanUnsigned": return 1 if a < b else 0
        if op == "SetLessThanImmediate": return 1 if sa < imm else 0
        if op == "SetLessThanImmediateUnsigned": return 1 if a < (imm & MASK64) else 0
        if op == "Multiply": return (a * b) & MASK64
        if op == "MultiplyWord": return _sext32(a * b)
        if op == "Divide":
            if sb == 0: return MASK64
            if sa == -(1 << 63) and sb == -1: return sa & MASK64
            q = abs(sa) // abs(sb)                 # trunc toward zero, exact ints
            return (-q if (sa < 0) != (sb < 0) else q) & MASK64
        if op == "DivideUnsigned": return MASK64 if b == 0 else (a // b)
        if op == "Remainder":
            if sb == 0: return a
            if sa == -(1 << 63) and sb == -1: return 0
            q = abs(sa) // abs(sb)
            q = -q if (sa < 0) != (sb < 0) else q
            return (sa - q * sb) & MASK64
        if op == "RemainderUnsigned": return a if b == 0 else (a % b)
        if op == "Move": return a
        if op == "ConditionalZeroIfZero": return 0 if b == 0 else a
        if op == "ConditionalZeroIfNonzero": return 0 if b != 0 else a
        raise ExecError(f"{insn.name}: ALU op {op!r} unimplemented")

    def _branch_taken(self, op, insn) -> bool:
        a = self._get(self._reg(insn, "firstSource"))
        sa = _signed(a)
        if op == "BranchIfZero": return a == 0
        if op == "BranchIfNonzero": return a != 0
        b = self._get(self._reg(insn, "secondSource"))
        sb = _signed(b)
        return {"BranchEqual": a == b, "BranchNotEqual": a != b,
                "BranchLessThan": sa < sb, "BranchGreaterOrEqual": sa >= sb,
                "BranchLessThanUnsigned": a < b,
                "BranchGreaterOrEqualUnsigned": a >= b}[op]

    # ------------------------------------------------------------ coverage

    def coverage(self) -> dict:
        """Trace-scope honesty (§18.1): what this run did and did NOT exercise."""
        all_blocks = {b.name for f in self.fns_run for b in self.blocks[f]}
        return {
            "functionsRun": sorted(self.fns_run),
            "blocksNotExecuted": sorted(all_blocks - self.blocks_run),
            "readsConfirmed": len(self.reads_confirmed),
            "readsUnconfirmed": sorted(self.reads_unknown),
            "liveOutChecked": len(self.liveout_checked),
            "steps": self.steps,
        }


def run_function(prog: Program, name: str, args: list[int]) -> tuple[int, Machine]:
    m = Machine(prog)
    result = m.call(name, args)
    return result, m


def run_program(prog: Program) -> tuple[int, Machine]:
    m = Machine(prog)
    code = m.run_start()
    return code, m
