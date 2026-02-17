from machine import Pin
import uasyncio as asyncio
from nema17 import NEMA17Stepper

# Define pin numbers for stepper motor control
STEPPER_DIR_PIN = 0
STEPPER_STEP_PIN = 1
STEPPER_EN_PIN = 2
DIR_SETUP_MS = 5
CLOCKWISE = 1
COUNTERCLOCKWISE = -1
TOTAL_REVS = 1
STEPS_PER_REV = 200
DELAY_MS = 2  # Delay between steps in milliseconds

# IR sensor pins
IR_SENSOR_INSIDE_PIN = 18
IR_SENSOR_OUTSIDE_PIN = 19

# Create stepper motor instance
stepper = NEMA17Stepper(STEPPER_DIR_PIN, STEPPER_STEP_PIN, STEPPER_EN_PIN)    
# Create IR sensor pins
ir_sensor_inside = Pin(IR_SENSOR_INSIDE_PIN, Pin.IN)
ir_sensor_outside = Pin(IR_SENSOR_OUTSIDE_PIN, Pin.IN)

async def stepper_control():
    inside_triggered = ir_sensor_inside.value() == 0
    outside_triggered = ir_sensor_outside.value() == 0
    revs = 0

    if inside_triggered and not outside_triggered:
        print("Home position detected")
    else:
        stepper.direction = COUNTERCLOCKWISE
        print("Finding home position...")
        while not inside_triggered:
            # Check IR sensor states
            print(f"{revs + 1} counterclockwise revolutions")
            stepper.enabled = True
            await stepper.step_motor(TOTAL_REVS * STEPS_PER_REV, DELAY_MS)
            stepper.enabled = False
            inside_triggered = ir_sensor_inside.value() == 0  # Active low
            revs += 1

    await asyncio.sleep(2)

    direction = CLOCKWISE
    
    while True:
        # Check IR sensor states
        inside_triggered = ir_sensor_inside.value() == 0  # Active low
        outside_triggered = ir_sensor_outside.value() == 0  # Active low
        
        if inside_triggered and not outside_triggered:
            print("Inside sensor triggered, moving clockwise")
            direction = CLOCKWISE
            stepper.direction = CLOCKWISE
            # sleep once when inside triggered in case of overshooting, 
            # prevent multiple sleeps when exiting inside trigger.            if revs != 1: 
            if revs != 1:  
                await asyncio.sleep(2)
            revs = 0
        
        elif outside_triggered and not inside_triggered:
            print("Outside sensor triggered, moving counterclockwise")
            direction = COUNTERCLOCKWISE
            stepper.direction = COUNTERCLOCKWISE
            # sleep once when outside triggered in case of overshooting, 
            # prevent multiple sleeps when exiting outside trigger.
            if revs != 1:  
                await asyncio.sleep(2)
            revs = 0

        if direction == CLOCKWISE:
            print(f"{revs + 1} clockwise revolutions")
        else:
            print(f"{revs + 1} counterclockwise revolutions")
        stepper.enabled = True
        await stepper.step_motor(TOTAL_REVS * STEPS_PER_REV, DELAY_MS)  # Move a certain number of steps
        stepper.enabled = False
        revs += 1

def main():
    try:
        asyncio.run(stepper_control())
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received. Stopping...")
    finally:
        stepper.enabled = False
        print("Stepper motor disabled. Exiting program.")

main()