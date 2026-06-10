/* Motor control over memory-mapped blocks — the reference.
 *
 * Arduino analogues:
 *   analogWrite(pin, duty)              -> pwmSetDuty(pwm, channel, duty)
 *   digitalWrite(DIR, x) + analogWrite  -> motorDrive(gpio, pwm, dirPin, ch, duty)
 *   Stepper.step(n)                     -> stepperAdvance(gpio, phase, n)
 *
 * PWM block (FE310-flavored): duty compare registers at base + 0x20 + 4*channel.
 * Stepper: classic 4-phase full-step sequence driven on gpio pins 0..3 from a
 * lookup table in .rodata — table-driven device writes, the embedded staple.
 *
 * Why this is HIGH-challenge in raw assembly:
 *   - indexed device addressing (base + 0x20 + channel*4): one bad shift and
 *     the wrong channel's motor changes speed;
 *   - the stepper's phase is MODULAR state threaded through a loop that also
 *     performs device writes and a busy delay — phase, step count, and both
 *     base pointers all live across every iteration;
 *   - writing a full phase PATTERN to output_val (not one bit) while the
 *     pattern table lives in read-only memory: two regions with two different
 *     access disciplines in one loop body.
 */
typedef unsigned int u32;

static const u32 stepPattern[4] = {0x3, 0x6, 0xC, 0x9};  /* AB, BC, CD, DA */

void pwmSetDuty(volatile u32 *pwm, long channel, long duty) {
    pwm[8 + channel] = (u32)duty;          /* 0x20/4 = index 8 */
}

void motorDrive(volatile u32 *gpio, volatile u32 *pwm,
                long dirPin, long channel, long duty) {
    if (duty < 0) {                        /* negative duty = reverse */
        gpio[3] |= (u32)1 << dirPin;
        duty = -duty;
    } else {
        gpio[3] &= ~((u32)1 << dirPin);
    }
    pwmSetDuty(pwm, channel, duty);
}

/* Advance the stepper `steps` full steps from `phase`; returns the new phase.
 * Writes each pattern to gpio[3] (output_val) with a settle delay between. */
long stepperAdvance(volatile u32 *gpio, long phase, long steps) {
    for (long i = 0; i < steps; i++) {
        phase = (phase + 1) & 3;
        gpio[3] = stepPattern[phase];
        for (volatile long d = 500; d > 0; d--) {}
    }
    return phase;
}
