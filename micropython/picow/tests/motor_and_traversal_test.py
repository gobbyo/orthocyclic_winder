"""
Combined motor + traversal guide test.

- Runs brushed motor at target encoder speed (cycles/min).
- Counts encoder slots from IR sensor.
- Moves traversal NEMA17 stepper 10 steps for every encoder slot.
- Uses inside/outside traversal IR sensors to reverse direction at limits.
"""

from machine import Pin, PWM
import uasyncio as asyncio
import time

from nema17 import NEMA17Stepper

# Brushed motor (spindle) configuration
BJT_GATE_PIN = 4
PWM_FREQUENCY = 60
TARGET_ENCODER_SPEED_CPM = 70
MOTOR_DUTY_START = 60397
SPEED_CONTROL_INTERVAL_MS = 200
SPEED_CONTROL_KP_DUTY_PER_CPM = 32.7675
TARGET_ENCODER_ROTATIONS = 50
MAX_DUTY = 65535

# Encoder configuration
IR_SENSOR_ENCODER_PIN = 17
ENCODER_ACTIVE_LEVEL = 0
ENCODER_DEBOUNCE_MS = 3
ENCODER_SLOTS_PER_REV = 20
TARGET_ENCODER_SLOTS = TARGET_ENCODER_ROTATIONS * ENCODER_SLOTS_PER_REV

# Traversal stepper configuration
STEPPER_DIR_PIN = 0
STEPPER_STEP_PIN = 1
STEPPER_EN_PIN = 2
CLOCKWISE = 1
COUNTERCLOCKWISE = -1
STEPPER_STEPS_PER_REV = 200
STEPS_PER_ENCODER_SLOT = STEPPER_STEPS_PER_REV // ENCODER_SLOTS_PER_REV
STEPPER_DELAY_MS = 2

# Traversal limit sensor pins (active low)
IR_SENSOR_INSIDE_PIN = 18
IR_SENSOR_OUTSIDE_PIN = 19


def emergency_stop_encoder_motor():
    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)
    motor_pwm.duty_u16(MAX_DUTY)
    motor_pwm.deinit()


async def motor_and_traversal_test():
    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)

    stepper = NEMA17Stepper(STEPPER_DIR_PIN, STEPPER_STEP_PIN, STEPPER_EN_PIN)
    stepper.direction = COUNTERCLOCKWISE
    stepper.enabled = False

    ir_sensor_inside = Pin(IR_SENSOR_INSIDE_PIN, Pin.IN)
    ir_sensor_outside = Pin(IR_SENSOR_OUTSIDE_PIN, Pin.IN)

    encoder_pin = Pin(IR_SENSOR_ENCODER_PIN, Pin.IN, Pin.PULL_UP)

    encoder_slot_count = 0
    traversal_slots_processed = 0
    stepper_steps_moved = 0
    last_encoder_edge_ms = time.ticks_ms()
    encoder_in_gap = (encoder_pin.value() == ENCODER_ACTIVE_LEVEL)
    running = True
    stop_requested = False

    def clamp_duty_value(duty_value):
        return max(0, min(MAX_DUTY, int(duty_value)))

    def target_speed_cpm():
        if TARGET_ENCODER_SPEED_CPM <= 0:
            raise ValueError("TARGET_ENCODER_SPEED_CPM must be > 0")
        return TARGET_ENCODER_SPEED_CPM

    def encoder_irq(pin):
        nonlocal encoder_slot_count, last_encoder_edge_ms, encoder_in_gap, stop_requested

        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_encoder_edge_ms) < ENCODER_DEBOUNCE_MS:
            return
        last_encoder_edge_ms = now_ms

        sensor_value = pin.value()
        if sensor_value == ENCODER_ACTIVE_LEVEL:
            if not encoder_in_gap:
                encoder_in_gap = True
                encoder_slot_count += 1
                if encoder_slot_count >= TARGET_ENCODER_SLOTS:
                    stop_requested = True
        else:
            encoder_in_gap = False

    async def report_revolutions():
        last_reported_revs = 0
        while running:
            revolutions = encoder_slot_count // ENCODER_SLOTS_PER_REV
            while last_reported_revs < revolutions:
                last_reported_revs += 1
                print(f"Revolutions: {last_reported_revs}")
            await asyncio.sleep_ms(5)

    async def drive_traversal_from_encoder():
        nonlocal traversal_slots_processed, stepper_steps_moved

        while running:
            pending_slots = encoder_slot_count - traversal_slots_processed
            if pending_slots <= 0:
                await asyncio.sleep_ms(2)
                continue

            inside_triggered = ir_sensor_inside.value() == 0
            outside_triggered = ir_sensor_outside.value() == 0

            if inside_triggered and not outside_triggered:
                stepper.direction = CLOCKWISE
            elif outside_triggered and not inside_triggered:
                stepper.direction = COUNTERCLOCKWISE

            stepper.enabled = True
            await stepper.step_motor(STEPS_PER_ENCODER_SLOT, STEPPER_DELAY_MS)
            stepper.enabled = False
            traversal_slots_processed += 1
            stepper_steps_moved += STEPS_PER_ENCODER_SLOT

    async def run_motor_speed_profile():
        nonlocal running
        target_cpm = target_speed_cpm()
        print("Starting combined motor + traversal test")
        print(f"PWM Frequency: {PWM_FREQUENCY}Hz")
        print(f"Encoder Pin: GPIO{IR_SENSOR_ENCODER_PIN}")
        print(f"Stepper per slot: {STEPS_PER_ENCODER_SLOT} steps")
        print(f"Target encoder speed: {target_cpm:.1f} cpm")
        print(f"Target encoder rotations: {TARGET_ENCODER_ROTATIONS}")

        duty_value = clamp_duty_value(MOTOR_DUTY_START)
        motor_pwm.duty_u16(duty_value)

        last_slots = encoder_slot_count
        last_control_ms = time.ticks_ms()

        while not stop_requested:
            await asyncio.sleep_ms(5)

            now_ms = time.ticks_ms()
            elapsed_ms = time.ticks_diff(now_ms, last_control_ms)
            if elapsed_ms < SPEED_CONTROL_INTERVAL_MS:
                continue

            current_slots = encoder_slot_count
            slot_delta = current_slots - last_slots
            measured_cps = (slot_delta * 1000.0) / (elapsed_ms * ENCODER_SLOTS_PER_REV)
            measured_cpm = measured_cps * 60.0

            speed_error_cpm = target_cpm - measured_cpm
            duty_value -= int(speed_error_cpm * SPEED_CONTROL_KP_DUTY_PER_CPM)
            duty_value = clamp_duty_value(duty_value)
            motor_pwm.duty_u16(duty_value)

            last_slots = current_slots
            last_control_ms = now_ms

        motor_pwm.duty_u16(MAX_DUTY)
        running = False
        print("Target encoder rotations reached, motor stopping.")

    irq_trigger = Pin.IRQ_FALLING | Pin.IRQ_RISING
    encoder_pin.irq(trigger=irq_trigger, handler=encoder_irq)

    rev_task = asyncio.create_task(report_revolutions())
    traversal_task = asyncio.create_task(drive_traversal_from_encoder())

    try:
        await run_motor_speed_profile()
    except Exception as exc:
        print(f"Error during test: {exc}")
    finally:
        running = False
        encoder_pin.irq(handler=None)

        try:
            await traversal_task
        except Exception:
            pass

        rev_task.cancel()
        try:
            await rev_task
        except asyncio.CancelledError:
            pass

        motor_pwm.duty_u16(MAX_DUTY)
        motor_pwm.deinit()
        stepper.enabled = False

        expected_steps = encoder_slot_count * STEPS_PER_ENCODER_SLOT
        step_difference = expected_steps - stepper_steps_moved
        pending_slots = encoder_slot_count - traversal_slots_processed
        motor_encoder_revolutions = encoder_slot_count / ENCODER_SLOTS_PER_REV
        stepper_revolutions = stepper_steps_moved / STEPPER_STEPS_PER_REV
        revolution_difference = motor_encoder_revolutions - stepper_revolutions
        print(f"Final encoder slot count: {encoder_slot_count}")
        print(f"Final traversal step count: {stepper_steps_moved}")
        print(f"Expected traversal step count: {expected_steps}")
        print(f"Expected minus actual step difference: {step_difference}")
        print(f"Motor encoder revolutions: {motor_encoder_revolutions:.3f}")
        print(f"Stepper revolutions: {stepper_revolutions:.3f}")
        print(f"Motor minus stepper revolution difference: {revolution_difference:.3f}")
        print(f"Final pending slot count: {pending_slots}")
        print("Combined test finished.")


def run_test():
    try:
        asyncio.run(motor_and_traversal_test())
    except KeyboardInterrupt:
        emergency_stop_encoder_motor()
        print("\nTest interrupted by user")
    finally:
        emergency_stop_encoder_motor()


if __name__ == "__main__":
    run_test()
