/* Arduino-style digital I/O over a memory-mapped GPIO block — the reference.
 *
 * The shape mirrors how this is really done:
 *   - Arduino:  pinMode(13, OUTPUT); digitalWrite(13, HIGH);
 *   - RPi/Linux userspace: mmap /dev/gpiomem, then poke registers through the
 *     mapped pointer.
 * Here the mapped BASE IS A PARAMETER (the RPi style) and the operations carry
 * the Arduino names — which is also exactly what makes the example testable:
 * the harness hands in a fake register block and asserts on it.
 *
 * Register map (SiFive FE310, the RISC-V "Arduino" chip), 32-bit registers:
 *   base + 0x00  input_val    pin input values
 *   base + 0x04  input_en     input enable bits
 *   base + 0x08  output_en    output enable bits   (pinMode OUTPUT)
 *   base + 0x0C  output_val   output values        (digitalWrite)
 *
 * Why this is HIGH-challenge in raw assembly:
 *   - every register access is a VOLATILE device access: a "redundant" load is
 *     not redundant, a "dead" store is not dead, and reordering is a bug —
 *     facts the .sasm states (`memoryRegion kind device`, `volatile yes`,
 *     `effect device.read/write`) and raw `.s` cannot;
 *   - read-modify-write bit twiddling (load, mask, or/and, store) where using
 *     a stale register image silently corrupts OTHER pins;
 *   - blink: a loop whose three values (base, pin, count) must all survive two
 *     calls per iteration plus a busy-wait delay.
 */
typedef unsigned int u32;

enum { INPUT_VAL = 0, INPUT_EN = 1, OUTPUT_EN = 2, OUTPUT_VAL = 3 };

void pinModeOutput(volatile u32 *gpio, long pin) {
    gpio[OUTPUT_EN] |= (u32)1 << pin;          /* RMW: other pins untouched */
}

void digitalWrite(volatile u32 *gpio, long pin, long level) {
    u32 mask = (u32)1 << pin;
    if (level)
        gpio[OUTPUT_VAL] |= mask;
    else
        gpio[OUTPUT_VAL] &= ~mask;
}

long digitalRead(volatile u32 *gpio, long pin) {
    return (gpio[INPUT_VAL] >> pin) & 1;
}

/* Blink the pin `count` times; returns the number of digitalWrite calls (2n).
 * The delay is a busy spin, Arduino delay() style. */
long blink(volatile u32 *gpio, long pin, long count) {
    for (long i = 0; i < count; i++) {
        digitalWrite(gpio, pin, 1);
        for (volatile long d = 2000; d > 0; d--) {}
        digitalWrite(gpio, pin, 0);
        for (volatile long d = 2000; d > 0; d--) {}
    }
    return count * 2;
}
