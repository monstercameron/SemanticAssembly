/* Ackermann — the reference the .sasm must match.
 *
 * Why this is HIGH-challenge in raw assembly:
 *   - nested recursion: ack(m-1, ack(m, n-1)) — the inner call's result feeds
 *     the outer call's ARGUMENT register while m must survive BOTH the inner
 *     call and the argument shuffle (classic silent-clobber territory);
 *   - three-way branching CFG (m==0 / n==0 / general) where every path must
 *     leave the frame balanced and the callee-saved contract intact;
 *   - extremely deep recursion (ack(3,3) makes 2432 calls) — any frame or
 *     save/restore mistake compounds until the stack is garbage.
 */
long ack(long m, long n) {
    if (m == 0) return n + 1;
    if (n == 0) return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}
