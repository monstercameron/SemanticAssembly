// sum_array — sum n 64-bit elements. A loop, memory reads, and a CFG.
long sum_array(const long *data, long n) {
    long sum = 0;
    for (long i = 0; i < n; i++) {
        sum += data[i];
    }
    return sum;
}
