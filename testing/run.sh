#!/usr/bin/env bash
# Host-side driver: build the image once, then run the in-container test suite
# with the repo mounted read-only at /work.
#
#   bash testing/run.sh
#
# Requires Docker Desktop running. On Windows/git-bash we disable MSYS path
# translation and feed Docker a Windows-style path for the bind mount.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG=sasm-riscv-test

docker build -t "$IMG" "$ROOT/testing"

# Resolve a mount path Docker Desktop accepts from git-bash.
if command -v cygpath >/dev/null 2>&1; then
  MOUNT="$(cygpath -w "$ROOT")"
else
  MOUNT="$ROOT"
fi

MSYS_NO_PATHCONV=1 docker run --rm -v "${MOUNT}:/work" "$IMG" bash testing/intest.sh
