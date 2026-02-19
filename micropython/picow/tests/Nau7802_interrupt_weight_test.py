from nau7802_async import NAU7802, _sleep_ms
from machine import Pin, SoftI2C
import uasyncio as asyncio

# Update these pins to your wiring
SCL_PIN = 13
SDA_PIN = 12
DRDY_PIN = 11  # NAU7802 DRDY pin wired to this GPIO (validated by DRDY pin test)
ONBOARD_LED_PIN = 25

I2C_FREQ = 100000
READ_SAMPLES = 60
TARE_SAMPLES = 300
CAL_SAMPLES = 300
SETTLE_MS = 1500
KNOWN_MASS_G = 249.0
AUTO_TARE_WAIT_MS = 3000
AUTO_CAL_WAIT_MS = 5000

# Print only when weight changes by at least this amount
CHANGE_THRESHOLD_G = 2.0
DRDY_TIMEOUT_MS = 500
I2C_ERROR_BACKOFF_MS = 20
MAX_CONSECUTIVE_I2C_ERRORS = 30
STARTUP_OP_RETRIES = 3


async def blink_for_duration(led, duration_ms, on_ms=120, off_ms=120):
    elapsed = 0
    while elapsed < duration_ms:
        led.value(1)
        await _sleep_ms(on_ms)
        elapsed += on_ms
        if elapsed >= duration_ms:
            break
        led.value(0)
        await _sleep_ms(off_ms)
        elapsed += off_ms
    led.value(0)


async def blink_count(led, count, on_ms=100, off_ms=100):
    for _ in range(count):
        led.value(1)
        await _sleep_ms(on_ms)
        led.value(0)
        await _sleep_ms(off_ms)


async def main():
    i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
    led = Pin(ONBOARD_LED_PIN, Pin.OUT)
    led.value(0)
    scale = NAU7802(i2c=i2c)

    async def run_with_recovery(op_name, coro_factory, retries=STARTUP_OP_RETRIES):
        attempt = 0
        while attempt < retries:
            attempt += 1
            try:
                return await coro_factory()
            except OSError as exc:
                print("WARN: {} failed with I2C error: {} (attempt {}/{})".format(op_name, exc, attempt, retries))
                await _sleep_ms(I2C_ERROR_BACKOFF_MS)
                if await scale.initialize():
                    print("NAU7802 re-initialized after {} error".format(op_name))
                else:
                    print("Re-init failed during {} recovery: {}".format(op_name, scale.last_error))
                await _sleep_ms(150)
        return None

    try:
        ok = await scale.initialize()
        if not ok:
            print("NAU7802 init failed:", scale.last_error)
            await blink_count(led, 6, on_ms=80, off_ms=80)
            return

        await _sleep_ms(SETTLE_MS)

        print("Remove all weight from scale. Taring in {} ms...".format(AUTO_TARE_WAIT_MS))
        await blink_for_duration(led, AUTO_TARE_WAIT_MS, on_ms=250, off_ms=250)
        tare_ok = await run_with_recovery(
            "tare",
            lambda: scale.tare(times=TARE_SAMPLES),
        )
        if not tare_ok:
            print("Tare failed:", scale.last_error)
            await blink_count(led, 6, on_ms=80, off_ms=80)
            return
        print("Tare offset:", scale.offset)
        await blink_count(led, 2, on_ms=180, off_ms=120)

        known_mass = float(KNOWN_MASS_G)
        if known_mass <= 0:
            print("Known mass must be > 0")
            await blink_count(led, 6, on_ms=80, off_ms=80)
            return

        print("Place {} g on the scale. Calibrating in {} ms...".format(known_mass, AUTO_CAL_WAIT_MS))
        await blink_for_duration(led, AUTO_CAL_WAIT_MS, on_ms=100, off_ms=100)

        factor = await run_with_recovery(
            "calibration",
            lambda: scale.calibrate_with_known_mass(known_mass, times=CAL_SAMPLES),
        )
        if factor is None:
            print("Calibration failed:", scale.last_error)
            await blink_count(led, 6, on_ms=80, off_ms=80)
            return

        print("Calibration factor (g/count):", factor)
        await blink_count(led, 3, on_ms=150, off_ms=100)

        scale.zero_deadband = CHANGE_THRESHOLD_G / 2

        last_reported = None
        scale.setup_drdy_interrupt(
            pin_num=DRDY_PIN,
            pull_up=True,
            trigger=NAU7802.DRDY_TRIGGER_RISING,
            hard=False,
            prime_on_high=True,
        )

        print("Listening for weight changes via DRDY interrupt...")
        print("Threshold: +/- {:.2f} g".format(CHANGE_THRESHOLD_G))
        print("DRDY pin {} initial state: {}".format(DRDY_PIN, scale.drdy_stats()["pin_state"]))
        led.value(1)
        total_i2c_errors = 0
        consecutive_i2c_errors = 0

        while True:
            got_interrupt = await scale.wait_for_drdy_interrupt(timeout_ms=DRDY_TIMEOUT_MS)

            if not got_interrupt:
                stats = scale.drdy_stats()
                print(
                    "WARN: No DRDY interrupt seen within {} ms. irq_callback_events={}, schedule_drops={}".format(
                        DRDY_TIMEOUT_MS, stats["irq_count"], stats["schedule_drops"]
                    )
                )
                continue

            try:
                weight = await scale.read_weight(times=READ_SAMPLES, timeout_ms=1000)
                consecutive_i2c_errors = 0
            except OSError as exc:
                total_i2c_errors += 1
                consecutive_i2c_errors += 1
                if total_i2c_errors == 1 or (total_i2c_errors % 10) == 0:
                    print(
                        "WARN: I2C error during weight read: {} (count={}, consecutive={})".format(
                            exc, total_i2c_errors, consecutive_i2c_errors
                        )
                    )
                await _sleep_ms(I2C_ERROR_BACKOFF_MS)
                continue

            if weight is None:
                continue

            if last_reported is None or abs(weight - last_reported) >= CHANGE_THRESHOLD_G:
                print("{:.2f} g".format(weight))
                last_reported = weight
    except KeyboardInterrupt:
        print("Stopping measurement (KeyboardInterrupt).")
    finally:
        try:
            scale.clear_drdy_interrupt()
        except Exception:
            pass
        led.value(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user.")
