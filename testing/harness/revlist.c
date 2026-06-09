/* Harness: exit 0 iff revlist reverses in place and sumlist sees the order.
 * List 10,20,30,40: sumlist = 10*1+20*2+30*3+40*4 = 300.
 * Reversed 40,30,20,10: sumlist = 40*1+30*2+20*3+10*4 = 200. */
typedef struct Node { long value; struct Node *next; } Node;

Node *revlist(Node *head);
long sumlist(const Node *head);

int main(void) {
    Node n4 = {40, 0};
    Node n3 = {30, &n4};
    Node n2 = {20, &n3};
    Node n1 = {10, &n2};

    if (sumlist(&n1) != 300) return 1;          /* forward checksum */

    Node *r = revlist(&n1);
    if (r != &n4) return 2;                     /* new head is the old tail */
    if (r->next != &n3 || n3.next != &n2 || n2.next != &n1 || n1.next != 0)
        return 3;                               /* every link flipped */
    if (sumlist(r) != 200) return 4;            /* reversed checksum */

    if (revlist(0) != 0) return 5;              /* empty list */
    Node solo = {7, 0};
    if (revlist(&solo) != &solo || solo.next != 0) return 6;  /* one node */

    return 0;
}
