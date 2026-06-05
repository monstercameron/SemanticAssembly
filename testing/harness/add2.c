#include <stdio.h>
extern long add2(long left, long right);
int main(void) {
    long r = add2(2, 3);
    printf("add2(2, 3) = %ld (want 5)\n", r);
    return r == 5 ? 0 : 1;
}
