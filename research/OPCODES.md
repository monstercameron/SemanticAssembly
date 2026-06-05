# Semantic opcode table

The instruction's agent-facing identity is a **semantic name** (`operation Add`),
not a mnemonic (`add`). The mnemonic is a *derived* lowering detail produced by
`π` (DESIGN §15). This is the core of "semantic assembly": instructions carry
meaning, not just encoding.

**`sasm/optable.tsv` is the single source of truth.** This file is a rendered,
grouped view for humans; if the two disagree, the TSV wins. The toolchain
(parser, validator, emitter) is fully table-driven from the TSV.

## How a fact uses it

```
addLeftAndRight operation Add      # semantic name — authoritative
addLeftAndRight destination a0
addLeftAndRight firstSource a0
addLeftAndRight secondSource a1
```

Lowering looks up `Add` → `emit = "add {destination}, {firstSource}, {secondSource}"`,
fills the operand fields, and discards everything else. From the same row the
validator derives `defines={a0}`, `uses={a0,a1}`, `effect=none`, `control=seq`.
Operand fields are full words (`destination`/`firstSource`/`secondSource`/
`immediate`), never the RISC-V acronyms (`rd`/`rs1`/`rs2`/`imm`).

## Columns

| Column | Meaning |
|--------|---------|
| `sem` | semantic name — the authoritative `operation` value in a fact |
| `mnemonic` | RISC-V assembler mnemonic emitted by `π` |
| `class` | family: arith logic shift compare muldiv cond load store const branch jump pseudo system atomic |
| `fmt` | encoding format: R I S B U J pseudo (keys `formats.tsv` for immediate ranges) |
| `defines` / `uses` | operand-role fields read for def/use (def/use truth, DESIGN §12) |
| `effect` | none memory.read memory.write fence syscall trap |
| `control` | successor kind: seq branch jump call return syscall |
| `tier` | validation fidelity tier (DESIGN §7.3): A B V P |
| `emit` | lowering template; `{field}` resolved from the fact's authoritative facts |
| `meaning` | register-transfer description (documentation) |

## Naming conventions

**PascalCase, full words, no acronyms, no terse suffixes** — the name reads as
plain English describing what the instruction does. (`sub`→`Subtract`,
`xor`→`ExclusiveOr`, `addi`→`AddImmediate`, `sltu`→`SetLessThanUnsigned`,
`ld`→`LoadDoubleword`, `mulhsu`→`MultiplyHighSignedUnsigned`,
`ecall`→`EnvironmentCall`.) The same rule governs operand fields, value names, and
instruction handles (LANGUAGE casing rules).

---

## Tier A — full semantic validation (the first working slice)

### Arithmetic
| sem | mnemonic | meaning |
|-----|----------|---------|
| Add | add | destination = firstSource + secondSource |
| Subtract | sub | destination = firstSource - secondSource |
| AddImmediate | addi | destination = firstSource + immediate |
| AddWord | addw | destination = signExtend32(firstSource + secondSource) |
| SubtractWord | subw | destination = signExtend32(firstSource - secondSource) |
| AddImmediateWord | addiw | destination = signExtend32(firstSource + immediate) |

### Logic
| sem | mnemonic | meaning |
|-----|----------|---------|
| And | and | destination = firstSource and secondSource |
| Or | or | destination = firstSource or secondSource |
| ExclusiveOr | xor | destination = firstSource exclusiveOr secondSource |
| AndImmediate | andi | destination = firstSource and immediate |
| OrImmediate | ori | destination = firstSource or immediate |
| ExclusiveOrImmediate | xori | destination = firstSource exclusiveOr immediate |

### Shift
| sem | mnemonic | meaning |
|-----|----------|---------|
| ShiftLeftLogical | sll | destination = firstSource shiftedLeftBy (secondSource and 63) |
| ShiftRightLogical | srl | destination = firstSource shiftedRightLogicalBy (secondSource and 63) |
| ShiftRightArithmetic | sra | destination = firstSource shiftedRightArithmeticBy (secondSource and 63) |
| ShiftLeftLogicalImmediate | slli | destination = firstSource shiftedLeftBy immediate |
| ShiftRightLogicalImmediate | srli | destination = firstSource shiftedRightLogicalBy immediate |
| ShiftRightArithmeticImmediate | srai | destination = firstSource shiftedRightArithmeticBy immediate |

### Compare / set
| sem | mnemonic | meaning |
|-----|----------|---------|
| SetLessThan | slt | destination = (firstSource lessThanSigned secondSource) ? 1 : 0 |
| SetLessThanUnsigned | sltu | destination = (firstSource lessThanUnsigned secondSource) ? 1 : 0 |
| SetLessThanImmediate | slti | destination = (firstSource lessThanSigned immediate) ? 1 : 0 |
| SetLessThanImmediateUnsigned | sltiu | destination = (firstSource lessThanUnsigned immediate) ? 1 : 0 |

### Multiply / divide (M)
| sem | mnemonic | meaning |
|-----|----------|---------|
| Multiply | mul | destination = lowBits(firstSource times secondSource) |
| MultiplyHighSigned | mulh | destination = highBits(signed firstSource times signed secondSource) |
| MultiplyHighSignedUnsigned | mulhsu | destination = highBits(signed firstSource times unsigned secondSource) |
| MultiplyHighUnsigned | mulhu | destination = highBits(unsigned firstSource times unsigned secondSource) |
| Divide | div | destination = firstSource dividedBySigned secondSource |
| DivideUnsigned | divu | destination = firstSource dividedByUnsigned secondSource |
| Remainder | rem | destination = firstSource remainderSigned secondSource |
| RemainderUnsigned | remu | destination = firstSource remainderUnsigned secondSource |
| MultiplyWord | mulw | destination = signExtend32(firstSource times secondSource) |
| DivideWord | divw | destination = signExtend32(firstSource dividedBySigned secondSource) |
| DivideWordUnsigned | divuw | destination = signExtend32(firstSource dividedByUnsigned secondSource) |
| RemainderWord | remw | destination = signExtend32(firstSource remainderSigned secondSource) |
| RemainderWordUnsigned | remuw | destination = signExtend32(firstSource remainderUnsigned secondSource) |

### Conditional (Zicond)
| sem | mnemonic | meaning |
|-----|----------|---------|
| ConditionalZeroIfZero | czero.eqz | destination = (secondSource equals 0) ? 0 : firstSource |
| ConditionalZeroIfNonzero | czero.nez | destination = (secondSource notEquals 0) ? 0 : firstSource |

### Load (effect memory.read)
| sem | mnemonic | meaning |
|-----|----------|---------|
| LoadByte | lb | destination = signExtend8(memory[base + offset]) |
| LoadHalfword | lh | destination = signExtend16(memory[base + offset]) |
| LoadWord | lw | destination = signExtend32(memory[base + offset]) |
| LoadDoubleword | ld | destination = memory64[base + offset] |
| LoadByteUnsigned | lbu | destination = zeroExtend8(memory[base + offset]) |
| LoadHalfwordUnsigned | lhu | destination = zeroExtend16(memory[base + offset]) |
| LoadWordUnsigned | lwu | destination = zeroExtend32(memory[base + offset]) |

### Store (effect memory.write)
| sem | mnemonic | meaning |
|-----|----------|---------|
| StoreByte | sb | memory[base + offset] = lowByte(secondSource) |
| StoreHalfword | sh | memory[base + offset] = lowHalfword(secondSource) |
| StoreWord | sw | memory[base + offset] = lowWord(secondSource) |
| StoreDoubleword | sd | memory64[base + offset] = secondSource |

### Constants / addresses
| sem | mnemonic | meaning |
|-----|----------|---------|
| LoadUpperImmediate | lui | destination = signExtend32(immediate shiftedLeftBy 12) |
| AddUpperImmediateToProgramCounter | auipc | destination = programCounter + signExtend32(immediate shiftedLeftBy 12) |
| LoadImmediate | li | destination = immediate (pseudo) |
| LoadAddress | la | destination = addressOf symbol (pseudo) |
| Move | mv | destination = firstSource (pseudo) |
| NoOperation | nop | no operation (pseudo) |

### Branches (control branch)
| sem | mnemonic | meaning |
|-----|----------|---------|
| BranchEqual | beq | if firstSource equals secondSource goto target |
| BranchNotEqual | bne | if firstSource notEquals secondSource goto target |
| BranchLessThan | blt | if firstSource lessThanSigned secondSource goto target |
| BranchGreaterOrEqual | bge | if firstSource greaterOrEqualSigned secondSource goto target |
| BranchLessThanUnsigned | bltu | if firstSource lessThanUnsigned secondSource goto target |
| BranchGreaterOrEqualUnsigned | bgeu | if firstSource greaterOrEqualUnsigned secondSource goto target |
| BranchIfZero | beqz | if firstSource equals 0 goto target (pseudo) |
| BranchIfNonzero | bnez | if firstSource notEquals 0 goto target (pseudo) |

### Jumps / calls (control jump/call/return)
| sem | mnemonic | meaning |
|-----|----------|---------|
| JumpAndLink | jal | destination = programCounter + 4; goto target |
| JumpAndLinkRegister | jalr | destination = programCounter + 4; goto firstSource + offset |
| Jump | j | goto target (pseudo) |
| JumpRegister | jr | goto firstSource (pseudo) |
| Call | call | returnAddress = programCounter + 4; goto symbol (pseudo) |
| TailCall | tail | goto symbol without link (pseudo) |
| Return | ret | goto returnAddress (pseudo) |

### System
| sem | mnemonic | effect | meaning |
|-----|----------|--------|---------|
| EnvironmentCall | ecall | syscall | trap to environment for a system call |
| EnvironmentBreak | ebreak | trap | trap to the debugger |
| Fence | fence | fence | order memory accesses |

### Atomics (A — Zaamo / Zalrsc / Zacas; address in `base`, value in `secondSource`)
| sem | mnemonic | meaning |
|-----|----------|---------|
| LoadReserved | lr.d | destination = memory64[base]; register a reservation |
| StoreConditional | sc.d | if reservation valid: memory64[base] = secondSource, destination = 0; else 1 |
| AtomicSwap | amoswap.d | destination = memory64[base]; memory64[base] = secondSource |
| AtomicAdd | amoadd.d | destination = memory64[base]; memory64[base] = destination + secondSource |
| AtomicAnd | amoand.d | destination = memory64[base]; memory64[base] = destination and secondSource |
| AtomicOr | amoor.d | destination = memory64[base]; memory64[base] = destination or secondSource |
| AtomicExclusiveOr | amoxor.d | destination = memory64[base]; memory64[base] = destination exclusiveOr secondSource |
| AtomicMaximumSigned | amomax.d | destination = memory64[base]; memory64[base] = maximumSigned(destination, secondSource) |
| AtomicMinimumSigned | amomin.d | destination = memory64[base]; memory64[base] = minimumSigned(destination, secondSource) |
| AtomicMaximumUnsigned | amomaxu.d | destination = memory64[base]; memory64[base] = maximumUnsigned(destination, secondSource) |
| AtomicMinimumUnsigned | amominu.d | destination = memory64[base]; memory64[base] = minimumUnsigned(destination, secondSource) |
| AtomicCompareAndSwap | amocas.d | if memory64[base] equals destination: memory64[base] = secondSource; destination = original (Zacas) |

---

## Tiers B / V / P — coverage now, fidelity later

These are **generated** from `riscv/riscv-opcodes` (DESIGN §7.2) rather than
hand-written here. They get a `sem` name from the same conventions, a correct
`emit` template, and structural validation. Fidelity follows DESIGN §7.3:

- **Tier B** — F, D, C, B (Zba/Zbb/Zbs), Zfa, Zcb, Zfhmin, Zicbom/p/z, Zawrs.
- **Tier V** — RVV 1.0 vector (needs `vtype`/`vl`/`LMUL`/`SEW` modeling).
- **Tier P** — Zicsr, privileged, Sv*, H: opaque, structural only.

When the generator lands, this section is replaced by a generated appendix; the
Tier A table above stays hand-curated as the validated, golden core.
