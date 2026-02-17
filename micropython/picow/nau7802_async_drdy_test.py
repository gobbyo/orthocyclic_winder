from machine import Pin, SoftI2C
import uasyncio as asyncio
from time import ticks_ms, ticks_diff
from nau7802_async import NAU7802, _sleep_ms

SCL_PIN = 13
SDA_PIN = 12
DRDY_PIN = 11
I2C_FREQ = 100000
TEST_DURATION_MS = 5000


async def main():
    i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
    scale = NAU7802(i2c=i2c)

    ok = await scale.initialize()
    if not ok:
        print("NAU7802 init failed:", scale.last_error)
        return

    scale.setup_drdy_interrupt(
        pin_num=DRDY_PIN,
        pull_up=True,
        trigger=NAU7802.DRDY_TRIGGER_RISING,
        hard=False,
        prime_on_high=True,
    )

    print("DRDY quick IRQ test start")
    print("GPIO{} rising-edge for {} ms".format(DRDY_PIN, TEST_DURATION_MS))

    start_ms = ticks_ms()

    got_any = False
    while True:
        got_irq = await scale.wait_for_drdy_interrupt(timeout_ms=250)
        stats = scale.drdy_stats()
        if got_irq and stats["irq_count"] > 0:
            got_any = True
            print("IRQ count:", stats["irq_count"], "pin_state:", stats["pin_state"])

        now_ms = ticks_ms()
        elapsed = ticks_diff(now_ms, start_ms)

        if elapsed >= TEST_DURATION_MS:
            break

        await _sleep_ms(10)

    stats = scale.drdy_stats()
    print("Test complete. irq_count={}, rising={}, falling={}, schedule_drops={}".format(
        stats["irq_count"], stats["rising_count"], stats["falling_count"], stats["schedule_drops"]
    ))

    if got_any:
        print("PASS: DRDY rising IRQ detected")
    else:
        print("FAIL: No DRDY rising IRQ detected")

    scale.clear_drdy_interrupt()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user")
