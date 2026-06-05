#!/usr/bin/env bash
# Validator test: every committed example must check clean (0 errors).
#   bash tests/check.sh
set -u
cd "$(dirname "$0")/.."
fail=0
for src in examples/*/*.sasm; do
  if python -m sasm check "$src" >/dev/null 2>/tmp/chk.err; then
    echo "CLEAN  $src"
  else
    echo "ERRORS $src"; sed 's/^/    /' /tmp/chk.err; fail=1
  fi
done
[ "$fail" = 0 ] && echo "all examples validate clean" || echo "VALIDATION FAILURES"
exit $fail
