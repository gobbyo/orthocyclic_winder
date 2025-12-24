from machine import Pin, PWM 
import time

PWM_PIN = 5

def demo_pwm(pwm: PWM, freq: float = 60.0):
    """Fade the LED in and out until Ctrl-C."""

    pwm.freq(int(freq))
    pwm.duty_u16(0)  # Start with 0% duty cycle
    # fade up
    print("Fading up...")
    for dc in [x * 0.5 for x in range(0, 100)]:  # 0.0 to 100.0 in 0.5 steps
        pwm.duty_u16(int(dc * 655.35))
        print(f"Duty cycle: {dc:.1f}%")
        time.sleep(0.05)
    # fade down
    print("Fading down...")
    for dc in [x * 0.5 for x in range(100, -1, -1)]:
        pwm.duty_u16(int(dc * 655.35))
        print(f"Duty cycle: {dc:.1f}%")
        time.sleep(0.05)
    # Wait a bit before the next cycle
    time.sleep(1)  

def main():
    try:
        pwm = PWM(Pin(PWM_PIN, Pin.OUT))
        i = 1
        while True:
            print(f"Motor run cycle #{i}")
            demo_pwm(pwm)  # Example usage with BCM pin 18
            i += 1
    except KeyboardInterrupt:
        print("Stopping demo and cleaning up")
    finally:
        pwm.duty_u16(0)

if __name__ == "__main__":      
    main()

