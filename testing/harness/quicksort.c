/* Harness: exit 0 iff qsort64 sorts every probe correctly.
 * Includes duplicates, already-sorted, reverse-sorted, negatives, and a
 * single-element + empty range (the lo>=hi early return). */
void qsort64(long *a, long lo, long hi);

static int sorted(const long *a, long n) {
    for (long i = 1; i < n; i++)
        if (a[i - 1] > a[i]) return 0;
    return 1;
}

int main(void) {
    long a[] = {5, 2, 9, 2, -7, 0, 12, 5, -7, 3, 1, 8};
    long b[] = {1, 2, 3, 4, 5};
    long c[] = {9, 7, 5, 3, 1, -1};
    long d[] = {42};

    qsort64(a, 0, 11);
    if (!sorted(a, 12)) return 1;
    if (a[0] != -7 || a[11] != 12) return 2;

    qsort64(b, 0, 4);                 /* already sorted */
    if (!sorted(b, 5)) return 3;

    qsort64(c, 0, 5);                 /* reverse sorted */
    if (!sorted(c, 6) || c[0] != -1 || c[5] != 9) return 4;

    qsort64(d, 0, 0);                 /* single element: lo >= hi fast path */
    if (d[0] != 42) return 5;

    return 0;
}
