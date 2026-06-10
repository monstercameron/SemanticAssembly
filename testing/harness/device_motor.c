/* Harness: fake GPIO + PWM register blocks stand in for the hardware. */
typedef unsigned int u32;

void pwmSetDuty(volatile u32 *pwm, long channel, long duty);
void motorDrive(volatile u32 *gpio, volatile u32 *pwm,
                long dirPin, long channel, long duty);
long stepperAdvance(volatile u32 *gpio, long phase, long steps);

static const u32 pattern[4] = {0x3, 0x6, 0xC, 0x9};

int main(void) {
    volatile u32 gpio[4] = {0, 0, 0, 0};
    volatile u32 pwm[16] = {0};            /* duty compares at index 8.. */

    pwmSetDuty(pwm, 0, 128);
    if (pwm[8] != 128) return 1;
    pwmSetDuty(pwm, 2, 180);               /* indexed: channel 2, not 0 */
    if (pwm[10] != 180 || pwm[8] != 128) return 2;

    motorDrive(gpio, pwm, 6, 1, -75);      /* reverse: dir set, |duty| */
    if (gpio[3] != (1u << 6) || pwm[9] != 75) return 3;
    motorDrive(gpio, pwm, 6, 1, 50);       /* forward: dir cleared */
    if (gpio[3] != 0 || pwm[9] != 50) return 4;

    long phase = stepperAdvance(gpio, 0, 6);
    if (phase != 2) return 5;              /* (0 +6 advances) & 3 -> 2 */
    if (gpio[3] != pattern[2]) return 6;   /* coils hold the final pattern */
    phase = stepperAdvance(gpio, phase, 3);
    if (phase != 1 || gpio[3] != pattern[1]) return 7;
    if (stepperAdvance(gpio, phase, 0) != 1) return 8;   /* zero steps */

    return 0;
}
