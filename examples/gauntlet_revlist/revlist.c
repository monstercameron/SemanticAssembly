/* In-place singly-linked-list reversal + position-weighted sum — reference.
 *
 * Why this is HIGH-challenge in raw assembly:
 *   - the three-pointer rotation (prev/cursor/next) has a strict intra-row
 *     ordering: load cursor->next BEFORE overwriting it, save cursor into
 *     prev BEFORE advancing — get any pair backwards and the list silently
 *     becomes a cycle or a two-node stub (no crash, just wrong);
 *   - every pointer lives in a register that is rewritten every iteration —
 *     the classic register-rotation clobber trap;
 *   - two functions share one translation unit: separate frames, separate
 *     contracts, one label namespace.
 *
 * Node layout: { long value; struct Node *next; }  -> value@0, next@8.
 */
typedef struct Node { long value; struct Node *next; } Node;

Node *revlist(Node *head) {
    Node *prev = 0;
    while (head) {
        Node *next = head->next;   /* read BEFORE the overwrite */
        head->next = prev;
        prev = head;               /* save BEFORE the advance   */
        head = next;
    }
    return prev;
}

long sumlist(const Node *head) {
    long sum = 0;
    long position = 1;             /* weighted: order changes the answer */
    while (head) {
        sum += head->value * position;
        position++;
        head = head->next;
    }
    return sum;
}
