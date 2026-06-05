#!/usr/bin/env bash
# Compiler snapshot test (no Docker): π(x.sasm) must be byte-identical to the
# committed golden x.s. Fast, runs anywhere with Python.
#
#   bash tests/snapshot.sh
set -u
cd "$(dirname "$0")/.."
fail=0
for src in examples/*/*.sasm; do
  gold="${src%.sasm}.s"
  if [ ! -f "$gold" ]; then echo "NO GOLD  $src"; fail=1; continue; fi
  if python -m sasm emit "$src" | diff "$gold" - > /tmp/snap.diff 2>&1; then
    echo "OK    $src  ==  $gold"
  else
    echo "DIFF  $src"; sed 's/^/    /' /tmp/snap.diff; fail=1
  fi
done
[ "$fail" = 0 ] && echo "all snapshots match" || echo "SNAPSHOT FAILURES"
exit $fail
