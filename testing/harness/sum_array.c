#include <stdio.h>
extern long sum_array(const long *data, long n);
int main(void) {
    long a[5] = {1, 2, 3, 4, 5};
    long r = sum_array(a, 5);
    printf("sum_array([1,2,3,4,5]) = %ld (want 15)\n", r);
    return r == 15 ? 0 : 1;
}
