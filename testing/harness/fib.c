#include <stdio.h>
extern long fib(long n);
int main(void) {
    long r = fib(10);
    printf("fib(10) = %ld (want 55)\n", r);
    return r == 55 ? 0 : 1;
}
