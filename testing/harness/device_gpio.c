/* Harness: a fake GPIO register block stands in for the device — exactly how
 * the functions would meet real hardware via an mmap'd base on a Pi. */
typedef unsigned int u32;

void pinModeOutput(volatile u32 *gpio, long pin);
void digitalWrite(volatile u32 *gpio, long pin, long level);
long digitalRead(volatile u32 *gpio, long pin);
long blink(volatile u32 *gpio, long pin, long count);

int main(void) {
    volatile u32 regs[4] = {0, 0, 0, 0};   /* input_val, input_en, output_en, output_val */

    pinModeOutput(regs, 5);
    if (regs[2] != (1u << 5)) return 1;
    pinModeOutput(regs, 3);                /* RMW: pin 5 must survive */
    if (regs[2] != ((1u << 5) | (1u << 3))) return 2;

    digitalWrite(regs, 5, 1);
    if (regs[3] != (1u << 5)) return 3;
    digitalWrite(regs, 3, 1);              /* RMW: pin 5 stays high */
    if (regs[3] != ((1u << 5) | (1u << 3))) return 4;
    digitalWrite(regs, 5, 0);              /* clear 5, keep 3 */
    if (regs[3] != (1u << 3)) return 5;

    regs[0] = 1u << 7;
    if (digitalRead(regs, 7) != 1) return 6;
    if (digitalRead(regs, 6) != 0) return 7;

    if (blink(regs, 5, 3) != 6) return 8;  /* 3 cycles = 6 writes */
    if (regs[3] != (1u << 3)) return 9;    /* blink ends LOW; pin 3 untouched */

    return 0;
}
