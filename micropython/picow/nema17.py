from machine import Pin
import uasyncio as asyncio
import time

CLOCKWISE = 1
COUNTERCLOCKWISE = -1
STEPPER_ENABLE_IS_ACTIVE_LOW = True
DIR_SETUP_MS = 5

class NEMA17Stepper:
    def __init__(self, dir_pin, step_pin, en_pin):
        self.dir = Pin(dir_pin, Pin.OUT)
        self.step = Pin(step_pin, Pin.OUT)
        self.en = Pin(en_pin, Pin.OUT)
        self._enabled = False
        self._dir_needs_settle = True
        self.enabled = False

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        enable_level = 0 if STEPPER_ENABLE_IS_ACTIVE_LOW else 1
        disable_level = 1 if STEPPER_ENABLE_IS_ACTIVE_LOW else 0
        self.en.value(enable_level if value else disable_level)
        self._enabled = bool(value)
    
    @property
    def direction(self):
        return CLOCKWISE if self.dir.value() == 1 else COUNTERCLOCKWISE

    @direction.setter
    def direction(self, value):
        if value == CLOCKWISE:
            self.dir.value(1)
        elif value == COUNTERCLOCKWISE:
            self.dir.value(0)
        else:
            raise ValueError("direction must be CLOCKWISE or COUNTERCLOCKWISE")
        self._dir_needs_settle = True

    async def step_motor(self, steps, delay_ms):
        if not self.enabled:
            raise Exception("Motor is not enabled")

        if steps <= 0:
            return

        self.step.value(0)

        if self._dir_needs_settle:
            await asyncio.sleep_ms(DIR_SETUP_MS)
            self._dir_needs_settle = False

        half_pulse_delay_us = max(100, int(delay_ms * 500))

        for step_index in range(steps):
            self.step.value(1)
            time.sleep_us(half_pulse_delay_us)
            self.step.value(0)
            time.sleep_us(half_pulse_delay_us)

            if (step_index & 0x1F) == 0x1F:
                await asyncio.sleep_ms(0)

async def test_nema17_stepper():
    # Define pin numbers for stepper motor control
    STEPPER_DIR_PIN = 0
    STEPPER_STEP_PIN = 1
    STEPPER_EN_PIN = 2

    print("\n" + "="*60)
    print("NEMA17 STEPPER MOTOR TEST")
    print("="*60)

    # Initialize stepper motor
    print("\nInitializing NEMA17 stepper motor...")
    motor = NEMA17Stepper(
        dir_pin=STEPPER_DIR_PIN,
        step_pin=STEPPER_STEP_PIN,
        en_pin=STEPPER_EN_PIN
    )

    TOTAL_REVS = 25
    STEPS_PER_REV = 200
    DELAY_MS = 2  # Delay between steps in milliseconds

    try:
        print("Enabling motor...")
        motor.enabled = True
        motor.direction = CLOCKWISE
        print("\nRotating clockwise for {} revolution(s)...".format(TOTAL_REVS))
        await motor.step_motor(TOTAL_REVS * STEPS_PER_REV, DELAY_MS)
        
        print("Disabling motor...")
        motor.enabled = False
        await asyncio.sleep_ms(1000)
        motor.direction = COUNTERCLOCKWISE

        print("\nRotating counterclockwise for {} revolution(s)...".format(TOTAL_REVS))
        print("Enabling motor...")
        motor.enabled = True
        await motor.step_motor(TOTAL_REVS * STEPS_PER_REV, DELAY_MS)

        print("\nTest completed successfully.")

    except KeyboardInterrupt:
        print("\nKeyboard interrupt received. Stopping...")

    finally:
        print("Disabling motor...")
        motor.enabled = False

if __name__ == "__main__":
    asyncio.run(test_nema17_stepper())
