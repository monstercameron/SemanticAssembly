/* In-place quicksort (Lomuto partition, inclusive bounds) — the reference.
 *
 * Why this is HIGH-challenge in raw assembly:
 *   - TWO recursive calls: array/high/pivotIndex must survive the first call
 *     (three callee-saved registers juggled at once), while low must survive
 *     the whole partition loop untouched in an argument register;
 *   - a partition loop with data-dependent swaps: five scratch registers
 *     rotating through address computations and element values, where reusing
 *     one a row too early silently corrupts the array;
 *   - an 8-block CFG (guard, loop header, body, swap, advance, done) where
 *     every fall-through edge is load-bearing — one misplaced block and the
 *     loop body executes once as straight-line code.
 */
void qsort64(long *a, long lo, long hi) {
    if (lo >= hi) return;
    long pivot = a[hi];
    long i = lo - 1;
    for (long j = lo; j < hi; j++) {
        if (a[j] <= pivot) {
            i++;
            long tmp = a[i]; a[i] = a[j]; a[j] = tmp;
        }
    }
    long tmp = a[i + 1]; a[i + 1] = a[hi]; a[hi] = tmp;
    long p = i + 1;
    qsort64(a, lo, p - 1);
    qsort64(a, p + 1, hi);
}
