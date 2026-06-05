// A larger program: compute 1^2 + 2^2 + ... + 10^2 (= 385), print it, exit 0.
// Three functions, a loop, mul/div/rem, a stack digit-buffer, and syscalls — the
// hand-written semantic-assembly version is sum_of_squares.sasm.
#include <unistd.h>

long sum_of_squares(long n) {
    long acc = 0;
    for (long i = 1; i <= n; i++) acc += i * i;
    return acc;
}

void print_int(long n) {            // n >= 0
    char buf[32];
    char *p = buf + sizeof buf;     // build digits backward from the end
    do { *--p = '0' + (n % 10); n /= 10; } while (n != 0);
    write(1, p, (buf + sizeof buf) - p);
}

void _start(void) {
    print_int(sum_of_squares(10));
    write(1, "\n", 1);
    _exit(0);
}
