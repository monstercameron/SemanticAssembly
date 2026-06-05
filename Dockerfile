# Self-contained evaluation environment for Semantic Assembly.
#
# Bundles everything needed to run the FULL suite with no host dependencies:
#   - Python 3            -> the sasm toolchain + compiler snapshot + validator
#   - riscv64 cross gcc    -> assemble/link the emitted .s (with libc)
#   - qemu-user-static     -> execute the riscv64 binaries
#
#   docker build -t sasm-eval .
#   docker run --rm sasm-eval            # runs eval.sh: snapshots + validator + qemu
#
# (testing/Dockerfile is the leaner, mount-the-repo image used by testing/run.sh
#  for fast behavioral-only iteration; this image is the reproducible whole-suite.)
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python-is-python3 \
        gcc-riscv64-linux-gnu \
        libc6-dev-riscv64-cross \
        qemu-user-static \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY . /work

CMD ["bash", "eval.sh"]
