"""
Asynchronous PWM motor control via MOSFET gate.
Ramps a 103 brushed motor from 0% to 100% and back down to 0%.
PWM frequency set to 60Hz.
"""

from machine import Pin, PWM
import uasyncio as asyncio
import time

# Configuration
BJT_GATE_PIN = 4  # GPIO pin connected to BJT gate (adjust as needed)
PWM_FREQUENCY = 60    # Hz
RAMP_STEP = 1         # Increase/decrease PWM by 1% per step
STEP_DELAY_MS = 100   # Delay between steps in milliseconds
MAX_DUTY = 65535     # Maximum duty cycle value for 16-bit resolution
IR_SENSOR_ENCODER_PIN = 17  # GPIO pin for encoder sensor (optional, can be used for feedback)
ENCODER_SLOTS_PER_REV = 20  # Encoder slots per full revolution
ENCODER_ACTIVE_LEVEL = 0    # Typical IR modules are active-low
ENCODER_DEBOUNCE_MS = 3     # Debounce/noise filter for encoder transitions

async def ramp_motor():
    """
    Ramp motor speed from 0% to 100% and back down to 0%.
    """

    # Initialize PWM on BJT gate pin
    motor_pwm = PWM(Pin(BJT_GATE_PIN))
    motor_pwm.freq(PWM_FREQUENCY)

    # Initialize encoder sensor pin
    encoder_pin = Pin(IR_SENSOR_ENCODER_PIN, Pin.IN, Pin.PULL_UP)
    encoder_count = 0
    last_encoder_edge_ms = time.ticks_ms()
    encoder_in_gap = (encoder_pin.value() == ENCODER_ACTIVE_LEVEL)

    def encoder_irq(pin):
        nonlocal encoder_count, last_encoder_edge_ms, encoder_in_gap
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_encoder_edge_ms) < ENCODER_DEBOUNCE_MS:
            return
        last_encoder_edge_ms = now_ms

        sensor_value = pin.value()
        if sensor_value == ENCODER_ACTIVE_LEVEL:
            if not encoder_in_gap:
                encoder_in_gap = True
                encoder_count += 1
        else:
            encoder_in_gap = False

    async def report_encoder_counts():
        last_reported_revs = 0
        while True:
            revolutions = encoder_count // ENCODER_SLOTS_PER_REV
            while last_reported_revs < revolutions:
                last_reported_revs += 1
                print(f"Revolutions: {last_reported_revs}")
            await asyncio.sleep_ms(5)

    irq_trigger = Pin.IRQ_FALLING | Pin.IRQ_RISING
    encoder_pin.irq(trigger=irq_trigger, handler=encoder_irq)
    encoder_report_task = asyncio.create_task(report_encoder_counts())
    
    print(f"Starting asynchronous motor ramp test")
    print(f"PWM Frequency: {PWM_FREQUENCY}Hz")
    print(f"BJT Gate Pin: GPIO{BJT_GATE_PIN}")
    print(f"IR Encoder Pin: GPIO{IR_SENSOR_ENCODER_PIN}")
    print(f"Encoder Slots/Rev: {ENCODER_SLOTS_PER_REV}")
    
    
    try:
        # RAMP UP: 0% to 100%
        print("Ramping UP from 0% to 100%...")
        
        for duty_pct in range(0, 101, RAMP_STEP):
            # Set PWM
            duty_value = MAX_DUTY - int((duty_pct / 100) * MAX_DUTY)
            motor_pwm.duty_u16(duty_value)
            
            # Print progress every 10%
            if duty_pct % 10 == 0:
                print(f"  PWM: {duty_pct}%")
            
            await asyncio.sleep_ms(STEP_DELAY_MS)
        
        print("  PWM: 100% (maximum)")
        print()
        
        # Hold at 100% for a moment
        await asyncio.sleep_ms(1000)
        
        # RAMP DOWN: 100% to 0%
        print("Ramping DOWN from 100% to 0%...")
        
        for duty_pct in range(100, -1, -RAMP_STEP):
            # Set PWM
            duty_value = MAX_DUTY - int((duty_pct / 100) * MAX_DUTY)
            motor_pwm.duty_u16(duty_value)
            
            # Print progress every 10%
            if duty_pct % 10 == 0:
                print(f"  PWM: {duty_pct}%")
            
            await asyncio.sleep_ms(STEP_DELAY_MS)
        
        print("  PWM: 0% (stopped)")
        print()
        
    except Exception as e:
        print(f"Error during motor ramp: {e}")
    
    finally:
        encoder_pin.irq(handler=None)
        encoder_report_task.cancel()
        try:
            await encoder_report_task
        except asyncio.CancelledError:
            pass

        # Ensure motor is stopped
        motor_pwm.duty_u16(MAX_DUTY)
        motor_pwm.deinit()
        print(f"Final encoder slot count: {encoder_count}")
        print("Motor stopped and PWM disabled.")


def run_test():
    """Run the asynchronous motor ramp test."""
    try:
        asyncio.run(ramp_motor())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed: {e}")


if __name__ == '__main__':
    run_test()
