"""`sasm fmt` properties (C3, DESIGN §11.1), checked on every example:

  - idempotent:            format(parse(format(x))) == format(parse(x))
  - semantics-preserving:  emit(parse(format(x)))   == emit(parse(x))

    python tests/fmt_test.py
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sasm.emit import emit
from sasm.format import format_program
from sasm.parser import parse


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "examples", "*", "*.sasm")))
    assert files, "no example .sasm files found"
    for f in files:
        text = open(f, encoding="utf-8").read()
        once = format_program(parse(text))
        twice = format_program(parse(once))
        rel = os.path.relpath(f, ROOT)
        assert once == twice, f"fmt not idempotent: {rel}"
        assert emit(parse(once)) == emit(parse(text)), f"fmt changed emitted .s: {rel}"
        print(f"  OK  {rel}")
    print("sasm fmt: OK (idempotent and semantics-preserving on all examples)")


if __name__ == "__main__":
    main()
