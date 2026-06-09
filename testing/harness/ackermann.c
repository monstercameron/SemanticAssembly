/* Harness: exit 0 iff every probe matches the Ackermann reference.
 * ack(3,3) drives 2432 recursive calls through the frame discipline. */
long ack(long m, long n);

int main(void) {
    if (ack(0, 0) != 1)  return 1;
    if (ack(0, 7) != 8)  return 2;
    if (ack(1, 5) != 7)  return 3;
    if (ack(2, 3) != 9)  return 4;
    if (ack(3, 3) != 61) return 5;
    return 0;
}
