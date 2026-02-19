from machine import Pin, PWM
import time

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

from nema17 import NEMA17Stepper
from windingcalculator import get_awg_diameter, winding_plan_from_awg


# Brushed motor (encoder motor)
BJT_GATE_PIN = 4
PWM_FREQUENCY = 60
MAX_DUTY = 65535
MOTOR_DUTY_START = 60397
REFERENCE_PITCH_MM = 1.25
BASE_ENCODER_SPEED_CPM = 70.0
SPEED_CONTROL_INTERVAL_MS_DEFAULT = 200
SPEED_CONTROL_KP_DUTY_PER_CPM_DEFAULT = 32.7675

# Encoder configuration
IR_SENSOR_ENCODER_PIN = 17
ENCODER_ACTIVE_LEVEL = 0
ENCODER_DEBOUNCE_MS = 3
ENCODER_SLOTS_PER_REV_DEFAULT = 20

# Traversal stepper configuration
STEPPER_DIR_PIN = 0
STEPPER_STEP_PIN = 1
STEPPER_EN_PIN = 2
CLOCKWISE = 1
STEPPER_DELAY_MS = 2


def emergency_stop_encoder_motor():
    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)
    motor_pwm.duty_u16(MAX_DUTY)
    motor_pwm.deinit()


def _load_winding_parameters(file_path="winding_coil_parameters.json"):
    with open(file_path, "r") as file_handle:
        params = json.load(file_handle)

    required_keys = ("total_turns", "spool_width_mm", "awg_size")
    missing_keys = [key for key in required_keys if key not in params]
    if missing_keys:
        raise ValueError("Missing required parameter(s): {}".format(", ".join(missing_keys)))

    loaded = {
        "total_turns": int(params["total_turns"]),
        "spool_width_mm": float(params["spool_width_mm"]),
        "awg_size": int(params["awg_size"]),
        "wire_type": params.get("wire_type", "magnet"),
        "encoder_slots_per_rev": int(params.get("encoder_slots_per_rev", ENCODER_SLOTS_PER_REV_DEFAULT)),
        "motor_duty_start": int(params.get("motor_duty_start", MOTOR_DUTY_START)),
        "speed_control_interval_ms": int(params.get("speed_control_interval_ms", SPEED_CONTROL_INTERVAL_MS_DEFAULT)),
        "speed_control_kp_duty_per_cpm": float(params.get("speed_control_kp_duty_per_cpm", SPEED_CONTROL_KP_DUTY_PER_CPM_DEFAULT)),
    }

    if loaded["total_turns"] <= 0:
        raise ValueError("total_turns must be > 0")
    if loaded["spool_width_mm"] <= 0:
        raise ValueError("spool_width_mm must be > 0")
    if loaded["encoder_slots_per_rev"] <= 0:
        raise ValueError("encoder_slots_per_rev must be > 0")
    if loaded["speed_control_interval_ms"] <= 0:
        raise ValueError("speed_control_interval_ms must be > 0")
    if loaded["speed_control_kp_duty_per_cpm"] <= 0:
        raise ValueError("speed_control_kp_duty_per_cpm must be > 0")

    return loaded


async def wind_first_layer():
    params = _load_winding_parameters("winding_coil_parameters.json")

    total_turns = params["total_turns"]
    spool_width_mm = params["spool_width_mm"]
    awg_size = params["awg_size"]
    wire_type = params["wire_type"]
    encoder_slots_per_rev = params["encoder_slots_per_rev"]
    motor_duty_start = params["motor_duty_start"]
    speed_control_interval_ms = params["speed_control_interval_ms"]
    speed_control_kp_duty_per_cpm = params["speed_control_kp_duty_per_cpm"]

    wire_diameter_mm = get_awg_diameter(awg_size, wire_type)
    if wire_diameter_mm <= 0:
        raise ValueError("Calculated wire_diameter_mm must be > 0")

    target_encoder_speed_cpm = BASE_ENCODER_SPEED_CPM * (REFERENCE_PITCH_MM / wire_diameter_mm)

    # Assume home already established by winder_homeposition.py
    layers = winding_plan_from_awg(total_turns, spool_width_mm, awg_size, wire_type)
    if not layers:
        raise ValueError("Winding plan returned no layers")

    first_layer_num, first_layer_turns, first_layer_steps = layers[0]
    target_encoder_slots = first_layer_turns * encoder_slots_per_rev
    steps_per_encoder_slot = first_layer_steps / target_encoder_slots

    print("Starting first-layer winding")
    print("Assuming traversal guide is already at home (inside).")
    print("Layer {} target: turns={}, steps={}".format(
        first_layer_num,
        first_layer_turns,
        first_layer_steps,
    ))
    print("Encoder slots/rev: {}".format(encoder_slots_per_rev))
    print("Wire diameter (mm): {:.3f}".format(wire_diameter_mm))
    print("Target encoder speed (cpm): {:.3f}".format(target_encoder_speed_cpm))
    print("Target encoder slots: {}".format(target_encoder_slots))
    print("Traversal step target/slot: {:.6f}".format(steps_per_encoder_slot))

    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)

    stepper = NEMA17Stepper(STEPPER_DIR_PIN, STEPPER_STEP_PIN, STEPPER_EN_PIN)
    stepper.direction = CLOCKWISE
    stepper.enabled = False

    encoder_pin = Pin(IR_SENSOR_ENCODER_PIN, Pin.IN, Pin.PULL_UP)

    encoder_slot_count = 0
    traversal_slots_processed = 0
    traversal_steps_moved = 0
    slot_step_accumulator = 0.0

    last_encoder_edge_ms = time.ticks_ms()
    encoder_in_gap = (encoder_pin.value() == ENCODER_ACTIVE_LEVEL)

    running = True
    stop_requested = False

    def clamp_duty_value(duty_value):
        return max(0, min(MAX_DUTY, int(duty_value)))

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
                if encoder_slot_count >= target_encoder_slots:
                    stop_requested = True
        else:
            encoder_in_gap = False

    async def drive_traversal_from_encoder():
        nonlocal traversal_slots_processed
        nonlocal traversal_steps_moved
        nonlocal slot_step_accumulator

        while running or (traversal_slots_processed < encoder_slot_count):
            pending_slots = encoder_slot_count - traversal_slots_processed
            if pending_slots <= 0:
                await asyncio.sleep_ms(1)
                continue

            while (pending_slots > 0) and (traversal_slots_processed < target_encoder_slots):
                slot_step_accumulator += steps_per_encoder_slot
                requested_steps = int(slot_step_accumulator)
                if requested_steps > 0:
                    slot_step_accumulator -= requested_steps

                remaining_steps = first_layer_steps - traversal_steps_moved
                step_count = min(requested_steps, remaining_steps)

                if step_count > 0:
                    stepper.enabled = True
                    await stepper.step_motor(step_count, STEPPER_DELAY_MS)
                    stepper.enabled = False
                    traversal_steps_moved += step_count

                traversal_slots_processed += 1
                pending_slots -= 1

                if traversal_slots_processed >= target_encoder_slots:
                    break

    irq_trigger = Pin.IRQ_FALLING | Pin.IRQ_RISING
    encoder_pin.irq(trigger=irq_trigger, handler=encoder_irq)

    traversal_task = asyncio.create_task(drive_traversal_from_encoder())

    try:
        duty_value = clamp_duty_value(motor_duty_start)
        motor_pwm.duty_u16(duty_value)

        last_slots = encoder_slot_count
        last_control_ms = time.ticks_ms()

        while not stop_requested:
            await asyncio.sleep_ms(5)

            now_ms = time.ticks_ms()
            elapsed_ms = time.ticks_diff(now_ms, last_control_ms)
            if elapsed_ms < speed_control_interval_ms:
                continue

            current_slots = encoder_slot_count
            slot_delta = current_slots - last_slots
            measured_cps = (slot_delta * 1000.0) / (elapsed_ms * encoder_slots_per_rev)
            measured_cpm = measured_cps * 60.0

            speed_error_cpm = target_encoder_speed_cpm - measured_cpm
            duty_value -= int(speed_error_cpm * speed_control_kp_duty_per_cpm)
            duty_value = clamp_duty_value(duty_value)
            motor_pwm.duty_u16(duty_value)

            last_slots = current_slots
            last_control_ms = now_ms

    finally:
        encoder_pin.irq(handler=None)
        motor_pwm.duty_u16(MAX_DUTY)

        catchup_deadline_ms = time.ticks_add(time.ticks_ms(), 3000)
        while traversal_slots_processed < encoder_slot_count:
            if time.ticks_diff(catchup_deadline_ms, time.ticks_ms()) <= 0:
                break
            await asyncio.sleep_ms(2)

        running = False

        try:
            await traversal_task
        except Exception:
            pass

        remaining_steps = first_layer_steps - traversal_steps_moved
        if remaining_steps > 0:
            stepper.enabled = True
            await stepper.step_motor(remaining_steps, STEPPER_DELAY_MS)
            stepper.enabled = False
            traversal_steps_moved += remaining_steps

        motor_pwm.duty_u16(MAX_DUTY)
        motor_pwm.deinit()
        stepper.enabled = False

    actual_turns = encoder_slot_count / encoder_slots_per_rev
    step_error = first_layer_steps - traversal_steps_moved

    print("First layer complete.")
    print("Expected turns: {}".format(first_layer_turns))
    print("Actual turns: {:.3f}".format(actual_turns))
    print("Expected slots: {}".format(target_encoder_slots))
    print("Actual slots: {}".format(encoder_slot_count))
    print("Expected traversal steps: {}".format(first_layer_steps))
    print("Actual traversal steps: {}".format(traversal_steps_moved))
    print("Step error (expected - actual): {}".format(step_error))


def run_test():
    try:
        asyncio.run(wind_first_layer())
    except KeyboardInterrupt:
        emergency_stop_encoder_motor()
        print("\nFirst-layer winding interrupted by user")
    finally:
        emergency_stop_encoder_motor()


if __name__ == "__main__":
    run_test()
