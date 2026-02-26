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
MOTOR_DUTY_START = 61397
REFERENCE_PITCH_MM = 1.25
BASE_ENCODER_SPEED_CPM = 76.0
SPEED_CONTROL_INTERVAL_MS_DEFAULT = 200
SPEED_CONTROL_KP_DUTY_PER_CPM_DEFAULT = 32.7675

# Suggested encoder_speed_scale by AWG (18-36).
# Linear/equitable descent from AWG 18 = 1.00 to AWG 32 = 0.10,
# then clamped at 0.10 for finer wire gauges.
# AWG 18: 1.00
# AWG 19: 0.70
# AWG 20: 0.50
# AWG 21: 0.46
# AWG 22: 0.40
# AWG 23: 0.36
# AWG 24: 0.30
# AWG 25: 0.55
# AWG 26: 0.49
# AWG 27: 0.42
# AWG 28: 0.36
# AWG 29: 0.29
# AWG 30: 0.23
# AWG 31: 0.16
# AWG 32: 0.10
# AWG 33: 0.10
# AWG 34: 0.10
# AWG 35: 0.10
# AWG 36: 0.10

# Encoder configuration
IR_SENSOR_ENCODER_PIN = 17
ENCODER_ACTIVE_LEVEL = 0
ENCODER_DEBOUNCE_MS = 3
ENCODER_SLOTS_PER_REV = 20

# Traversal stepper configuration
STEPPER_DIR_PIN = 0
STEPPER_STEP_PIN = 1
STEPPER_EN_PIN = 2
CLOCKWISE = 1
STEPPER_DELAY_MS = 2
STEPPER_PULSE_WIDTH_US = 300
STEPPER_MIN_INTERVAL_US = 500
STEPPER_MAX_INTERVAL_US = 8000


_active_motor_pwm = None


def emergency_stop_encoder_motor():
    global _active_motor_pwm

    if _active_motor_pwm is not None:
        try:
            _active_motor_pwm.duty_u16(MAX_DUTY)
            return
        except Exception:
            pass

    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)
    motor_pwm.duty_u16(MAX_DUTY)
    _active_motor_pwm = motor_pwm


def emergency_stop_all_motors():
    emergency_stop_encoder_motor()
    stepper_enable_pin = Pin(STEPPER_EN_PIN, Pin.OUT)
    stepper_enable_pin.value(1)


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
        "encoder_speed_scale": float(params.get("encoder_speed_scale", 1.0)),
        "motor_duty_start": int(params.get("motor_duty_start", MOTOR_DUTY_START)),
        "speed_control_interval_ms": int(params.get("speed_control_interval_ms", SPEED_CONTROL_INTERVAL_MS_DEFAULT)),
        "speed_control_kp_duty_per_cpm": float(params.get("speed_control_kp_duty_per_cpm", SPEED_CONTROL_KP_DUTY_PER_CPM_DEFAULT)),
    }

    if loaded["total_turns"] <= 0:
        raise ValueError("total_turns must be > 0")
    if loaded["spool_width_mm"] <= 0:
        raise ValueError("spool_width_mm must be > 0")
    if loaded["encoder_speed_scale"] <= 0:
        raise ValueError("encoder_speed_scale must be > 0")
    if loaded["speed_control_interval_ms"] <= 0:
        raise ValueError("speed_control_interval_ms must be > 0")
    if loaded["speed_control_kp_duty_per_cpm"] <= 0:
        raise ValueError("speed_control_kp_duty_per_cpm must be > 0")

    return loaded


async def wind_first_layer():
    global _active_motor_pwm

    params = _load_winding_parameters("winding_coil_parameters.json")

    total_turns = params["total_turns"]
    spool_width_mm = params["spool_width_mm"]
    awg_size = params["awg_size"]
    wire_type = params["wire_type"]
    encoder_slots_per_rev = ENCODER_SLOTS_PER_REV
    encoder_speed_scale = params["encoder_speed_scale"]
    motor_duty_start = params["motor_duty_start"]
    speed_control_interval_ms = params["speed_control_interval_ms"]
    speed_control_kp_duty_per_cpm = params["speed_control_kp_duty_per_cpm"]

    wire_diameter_mm = get_awg_diameter(awg_size, wire_type)
    if wire_diameter_mm <= 0:
        raise ValueError("Calculated wire_diameter_mm must be > 0")

    target_encoder_speed_cpm = BASE_ENCODER_SPEED_CPM * (REFERENCE_PITCH_MM / wire_diameter_mm) * encoder_speed_scale

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
    print("Encoder speed scale: {:.3f}".format(encoder_speed_scale))
    print("Target encoder speed (cpm): {:.3f}".format(target_encoder_speed_cpm))
    print("Target encoder slots: {}".format(target_encoder_slots))
    print("Traversal step target/slot: {:.6f}".format(steps_per_encoder_slot))

    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)
    _active_motor_pwm = motor_pwm

    stepper = NEMA17Stepper(STEPPER_DIR_PIN, STEPPER_STEP_PIN, STEPPER_EN_PIN)
    stepper.direction = CLOCKWISE
    stepper.enabled = False

    encoder_pin = Pin(IR_SENSOR_ENCODER_PIN, Pin.IN, Pin.PULL_UP)

    encoder_slot_count = 0
    traversal_steps_moved = 0

    last_encoder_irq_ms = time.ticks_ms()
    last_encoder_slot_ms = last_encoder_irq_ms
    filtered_slot_interval_ms = 0
    encoder_in_gap = (encoder_pin.value() == ENCODER_ACTIVE_LEVEL)

    running = True
    stop_requested = False

    def clamp_duty_value(duty_value):
        return max(0, min(MAX_DUTY, int(duty_value)))

    def encoder_irq(pin):
        nonlocal encoder_slot_count
        nonlocal last_encoder_irq_ms
        nonlocal last_encoder_slot_ms
        nonlocal filtered_slot_interval_ms
        nonlocal encoder_in_gap, stop_requested

        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_encoder_irq_ms) < ENCODER_DEBOUNCE_MS:
            return
        last_encoder_irq_ms = now_ms

        sensor_value = pin.value()
        if sensor_value == ENCODER_ACTIVE_LEVEL:
            if not encoder_in_gap:
                encoder_in_gap = True
                slot_interval_ms = time.ticks_diff(now_ms, last_encoder_slot_ms)
                last_encoder_slot_ms = now_ms
                if slot_interval_ms > 0:
                    if filtered_slot_interval_ms <= 0:
                        filtered_slot_interval_ms = slot_interval_ms
                    else:
                        filtered_slot_interval_ms = ((filtered_slot_interval_ms * 3) + slot_interval_ms) // 4
                encoder_slot_count += 1
                if encoder_slot_count >= target_encoder_slots:
                    stop_requested = True
        else:
            encoder_in_gap = False

    async def drive_traversal_from_encoder():
        nonlocal traversal_steps_moved

        stepper.enabled = True
        stepper.step.value(0)
        await asyncio.sleep_ms(5)
        next_step_us = time.ticks_us()

        while running or (traversal_steps_moved < first_layer_steps):
            effective_encoder_slots = float(encoder_slot_count)
            if running and (encoder_slot_count < target_encoder_slots) and (filtered_slot_interval_ms > 0):
                elapsed_since_slot_ms = time.ticks_diff(time.ticks_ms(), last_encoder_slot_ms)
                if elapsed_since_slot_ms > 0:
                    slot_fraction = elapsed_since_slot_ms / filtered_slot_interval_ms
                    if slot_fraction > 0.98:
                        slot_fraction = 0.98
                    effective_encoder_slots += slot_fraction

            proportional_target_steps = int((effective_encoder_slots * first_layer_steps) / target_encoder_slots)
            if proportional_target_steps > first_layer_steps:
                proportional_target_steps = first_layer_steps

            step_deficit = proportional_target_steps - traversal_steps_moved
            if step_deficit <= 0:
                if not running:
                    break
                await asyncio.sleep_ms(0)
                continue

            if filtered_slot_interval_ms > 0:
                step_interval_us = int((filtered_slot_interval_ms * 1000) / steps_per_encoder_slot)
            else:
                step_interval_us = STEPPER_DELAY_MS * 1000

            if step_interval_us < STEPPER_MIN_INTERVAL_US:
                step_interval_us = STEPPER_MIN_INTERVAL_US
            elif step_interval_us > STEPPER_MAX_INTERVAL_US:
                step_interval_us = STEPPER_MAX_INTERVAL_US

            now_us = time.ticks_us()
            steps_emitted = 0
            while (step_deficit > 0) and (time.ticks_diff(now_us, next_step_us) >= 0) and (steps_emitted < 4):
                stepper.step.value(1)
                time.sleep_us(STEPPER_PULSE_WIDTH_US)
                stepper.step.value(0)

                traversal_steps_moved += 1
                step_deficit -= 1
                steps_emitted += 1

                next_step_us = time.ticks_add(next_step_us, step_interval_us)
                now_us = time.ticks_us()

            if steps_emitted == 0:
                await asyncio.sleep_ms(0)

        stepper.enabled = False

    irq_trigger = Pin.IRQ_FALLING | Pin.IRQ_RISING
    encoder_pin.irq(trigger=irq_trigger, handler=encoder_irq)

    traversal_task = asyncio.create_task(drive_traversal_from_encoder())
    traversal_exception = None
    interrupted = False

    try:
        duty_value = clamp_duty_value(motor_duty_start)
        motor_pwm.duty_u16(duty_value)

        last_slots = encoder_slot_count
        last_control_ms = time.ticks_ms()

        while not stop_requested:
            await asyncio.sleep_ms(5)

            if traversal_task.done():
                traversal_exception = traversal_task.exception()
                if traversal_exception is not None:
                    raise traversal_exception

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

    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        stop_requested = True
        motor_pwm.duty_u16(MAX_DUTY)
        raise

    finally:
        running = False
        encoder_pin.irq(handler=None)
        motor_pwm.duty_u16(MAX_DUTY)

        if not interrupted:
            catchup_deadline_ms = time.ticks_add(time.ticks_ms(), 3000)
            while traversal_steps_moved < first_layer_steps:
                if time.ticks_diff(catchup_deadline_ms, time.ticks_ms()) <= 0:
                    break
                await asyncio.sleep_ms(2)

        try:
            await traversal_task
        except Exception as exc:
            if traversal_exception is None:
                traversal_exception = exc

        remaining_steps = first_layer_steps - traversal_steps_moved
        if (remaining_steps > 0) and (traversal_exception is None) and (not interrupted):
            stepper.enabled = True
            await stepper.step_motor(remaining_steps, STEPPER_DELAY_MS)
            stepper.enabled = False
            traversal_steps_moved += remaining_steps

        motor_pwm.duty_u16(MAX_DUTY)
        _active_motor_pwm = None
        motor_pwm.deinit()
        Pin(BJT_GATE_PIN, Pin.OUT).value(1)
        stepper.enabled = False

        if traversal_exception is not None:
            raise traversal_exception

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
        emergency_stop_all_motors()
        print("\nFirst-layer winding interrupted by user")
    except Exception as exc:
        emergency_stop_all_motors()
        print("\nFirst-layer winding failed: {}".format(exc))
    finally:
        emergency_stop_all_motors()


if __name__ == "__main__":
    run_test()
