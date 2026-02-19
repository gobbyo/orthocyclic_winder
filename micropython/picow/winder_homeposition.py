from machine import Pin

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

from nema17 import NEMA17Stepper
from windingcalculator import get_awg_diameter


# Traversal stepper configuration
STEPPER_DIR_PIN = 0
STEPPER_STEP_PIN = 1
STEPPER_EN_PIN = 2
CLOCKWISE = 1
COUNTERCLOCKWISE = -1
HOMING_STEP_DELAY_MS = 2
HOMING_REFINE_STEP_DELAY_MS = 2
HOMING_CHUNK_STEPS = 25
HOMING_MAX_STEPS = 20000
HOMING_BACKOFF_STEPS = 200
STEPPER_STEPS_PER_REV = 200
TRAVERSAL_LEAD_MM = 1.25

# Traversal limit sensor pins (active low)
IR_SENSOR_INSIDE_PIN = 18


def _steps_per_winder_turn(file_path="winding_coil_parameters.json"):
    try:
        with open(file_path, "r") as file_handle:
            params = json.load(file_handle)
    except Exception:
        return None

    try:
        awg_size = int(params["awg_size"])
        wire_type = params.get("wire_type", "magnet")
        wire_diameter_mm = get_awg_diameter(awg_size, wire_type)
    except Exception:
        return None

    if wire_diameter_mm <= 0:
        return None

    return STEPPER_STEPS_PER_REV * (wire_diameter_mm / TRAVERSAL_LEAD_MM)


async def home_traversal_guide():
    stepper = NEMA17Stepper(STEPPER_DIR_PIN, STEPPER_STEP_PIN, STEPPER_EN_PIN)
    stepper.enabled = False

    ir_sensor_inside = Pin(IR_SENSOR_INSIDE_PIN, Pin.IN)

    already_home = (ir_sensor_inside.value() == 0)
    if already_home:
        print("Traversal already at home (inside sensor active). Running backoff/refine.")
    else:
        print("Homing traversal guide to inside position...")

    stepper.enabled = True
    stepper.direction = COUNTERCLOCKWISE

    steps_taken = 0

    try:
        if not already_home:
            while (ir_sensor_inside.value() != 0) and (steps_taken < HOMING_MAX_STEPS):
                remaining_steps = HOMING_MAX_STEPS - steps_taken
                chunk_steps = min(HOMING_CHUNK_STEPS, remaining_steps)
                await stepper.step_motor(chunk_steps, HOMING_STEP_DELAY_MS)
                steps_taken += chunk_steps

            if ir_sensor_inside.value() != 0:
                raise RuntimeError(
                    "Unable to home traversal guide: inside sensor not reached "
                    "after {} steps".format(steps_taken)
                )

        stepper.direction = CLOCKWISE
        print("Backing off from home by {} steps...".format(HOMING_BACKOFF_STEPS))
        await stepper.step_motor(HOMING_BACKOFF_STEPS, HOMING_STEP_DELAY_MS)

        print("Re-approaching home one step at a time...")

        async def seek_home(direction, max_steps, delay_ms):
            stepper.direction = direction
            steps = 0
            while steps < max_steps:
                if ir_sensor_inside.value() == 0:
                    break
                await stepper.step_motor(1, delay_ms)
                steps += 1
                if ir_sensor_inside.value() == 0:
                    break
            return steps

        refine_steps_primary = await seek_home(
            COUNTERCLOCKWISE,
            HOMING_BACKOFF_STEPS,
            HOMING_REFINE_STEP_DELAY_MS,
        )
        refine_steps_fallback = 0

        if ir_sensor_inside.value() != 0:
            print("Primary refine direction did not hit home; trying opposite direction...")
            refine_steps_fallback = await seek_home(
                CLOCKWISE,
                HOMING_BACKOFF_STEPS * 2,
                HOMING_REFINE_STEP_DELAY_MS,
            )

        refine_steps_taken = refine_steps_primary + refine_steps_fallback

        if ir_sensor_inside.value() != 0:
            print("Refine pass did not reacquire home; running full recovery search...")
            recovery_steps_ccw = await seek_home(
                COUNTERCLOCKWISE,
                HOMING_MAX_STEPS,
                HOMING_REFINE_STEP_DELAY_MS,
            )
            recovery_steps_cw = 0

            if ir_sensor_inside.value() != 0:
                recovery_steps_cw = await seek_home(
                    CLOCKWISE,
                    HOMING_MAX_STEPS,
                    HOMING_REFINE_STEP_DELAY_MS,
                )

            if ir_sensor_inside.value() != 0:
                raise RuntimeError(
                    "Unable to refine home position after backoff "
                    "(refine steps attempted: {}, primary={}, fallback={}, recovery_ccw={}, recovery_cw={})".format(
                        refine_steps_taken,
                        refine_steps_primary,
                        refine_steps_fallback,
                        recovery_steps_ccw,
                        recovery_steps_cw,
                    )
                )
            else:
                print(
                    "Home recovered by fallback search (ccw steps={}, cw steps={}).".format(
                        recovery_steps_ccw,
                        recovery_steps_cw,
                    )
                )

        homed_steps = steps_taken - HOMING_BACKOFF_STEPS + refine_steps_taken
        homing_stepper_revolutions = homed_steps / STEPPER_STEPS_PER_REV
        steps_per_winder_turn = _steps_per_winder_turn()

        if steps_per_winder_turn:
            homing_winder_turns = homed_steps / steps_per_winder_turn
            print(
                "Traversal homed after {} steps (stepper revs {:.3f}, winding turns {:.3f}), backoff {} steps, refine {} steps.".format(
                    homed_steps,
                    homing_stepper_revolutions,
                    homing_winder_turns,
                    HOMING_BACKOFF_STEPS,
                    refine_steps_taken,
                )
            )
        else:
            print(
                "Traversal homed after {} steps (stepper revs {:.3f}), backoff {} steps, refine {} steps.".format(
                    homed_steps,
                    homing_stepper_revolutions,
                    HOMING_BACKOFF_STEPS,
                    refine_steps_taken,
                )
            )

    finally:
        stepper.enabled = False


def run_test():
    try:
        asyncio.run(home_traversal_guide())
    except KeyboardInterrupt:
        print("\nHoming interrupted by user")


if __name__ == "__main__":
    run_test()
