#!/usr/bin/env bash
# Full evaluation suite. Designed to run inside the eval image (Dockerfile),
# which provides python, the riscv64 cross toolchain, and qemu — so all three
# tiers run in one place with no host dependencies:
#
#   docker build -t sasm-eval . && docker run --rm sasm-eval
#
# It also runs on a host that happens to have python + the cross toolchain + qemu.
set -u
cd "$(dirname "$0")"
fail=0

echo "==================== 1/3  compiler snapshots (python) ===================="
bash tests/snapshot.sh || fail=1

echo
echo "==================== 2/3  validator (python) ============================="
bash tests/check.sh || fail=1
python tests/sugar_test.py || fail=1
python tests/ordinal_test.py || fail=1
python tests/fmt_test.py || fail=1

echo
echo "==================== 3/3  behavioral: assemble + run (qemu-riscv64) ======"
if command -v qemu-riscv64-static >/dev/null 2>&1; then
  bash testing/intest.sh || fail=1
else
  echo "SKIP  (no qemu-riscv64-static; run inside the eval image for this tier)"
fi

echo
if [ "$fail" = 0 ]; then
  echo "==================== ALL EVAL CHECKS PASSED ===================="
else
  echo "==================== EVAL FAILURES ============================="
fi
exit $fail
