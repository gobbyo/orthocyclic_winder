import uasyncio as asyncio
from machine import Pin, PWM

PWM_PIN = 5
MAX_SPEED = 100  # percent
MIN_SPEED = 0   # percent

class SpindleMotor:
    def __init__(self, pin, freq=60):  # low frequency
        self.pwm = PWM(Pin(pin))
        self.pwm.freq(freq)
        self.pwm.duty_u16(0)  # Start with 0% duty cycle
        self.current = 0
        self.target = 0
        self.ramp_rate = self.set_ramp_rate(10)  # default ramp rate

    def set_ramp_rate(self, rate):
        self.ramp_rate = int(rate * 655.35)  # Convert 0-100% to 0-65535

    def set_speed(self, duty):
        self.target = int(duty * 655.35)  # Convert 0-100% to 0-65535

    async def run(self):
        while True:
            if self.current < self.target:
                self.current += self.ramp_rate
                if self.current >= int(MAX_SPEED * 655.35):
                    self.current = int(MAX_SPEED * 655.35)
            elif self.current > self.target:
                self.current -= self.ramp_rate
                if self.current <= MIN_SPEED:
                    self.current = MIN_SPEED

            self.pwm.duty_u16(self.current)
            print(f"Current duty cycle: {self.current / 655.35:.1f}%")

            await asyncio.sleep_ms(200)

async def main():
    try:
        spindle = SpindleMotor(pin=PWM_PIN)  # your MOSFET gate pin
        asyncio.create_task(spindle.run())

        # ramp up to full speed to 100
        spindle.set_speed(100) 
        spindle.set_ramp_rate(2)
        await asyncio.sleep(10)

        # ramp down to stop
        spindle.set_speed(0)
        spindle.set_ramp_rate(2)
        await asyncio.sleep(10)
    except KeyboardInterrupt:
        print("Stopping spindle motor and cleaning up")
    finally:
        spindle.pwm.duty_u16(0)

if __name__ == "__main__":
    asyncio.run(main())