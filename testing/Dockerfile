# RISC-V test image: cross-compiler (with libc) + user-mode emulator.
# Build once:  docker build -t sasm-riscv-test testing/
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc-riscv64-linux-gnu \
        libc6-dev-riscv64-cross \
        qemu-user-static \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
