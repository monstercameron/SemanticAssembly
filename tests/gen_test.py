"""Generator coverage guard (B1): every real (non-pseudo) op in the hand-curated
optable must exist in upstream riscv-opcodes — catches table drift / typos.

Skips cleanly when the upstream clone is absent (so CI's no-network job passes):
    git clone --depth 1 https://github.com/riscv/riscv-opcodes gen/riscv-opcodes

    python tests/gen_test.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gen"))

import generate  # noqa: E402

PSEUDO = {"li", "la", "mv", "nop", "j", "jr", "call", "tail", "ret", "beqz", "bnez"}


def main():
    base = os.path.join(ROOT, "gen", "riscv-opcodes")
    if not os.path.isdir(base):
        print("gen_test: SKIP (gen/riscv-opcodes not cloned)")
        return 0
    upstream = generate.load_upstream(base)
    assert upstream, "no instructions parsed from riscv-opcodes"
    missing = sorted(m for m in (generate.hand_mnemonics() - PSEUDO) if m not in upstream)
    assert not missing, f"hand-table ops not found upstream: {missing}"
    print(f"generator coverage: OK ({len(generate.hand_mnemonics() - PSEUDO)} real ops confirmed upstream)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
