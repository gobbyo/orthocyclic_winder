"""
Simple Stepper Motor Queue Test
Tests stepper motor with queued commands and no delay.
"""

from micropython.esp32s2.stepper_motor import StepperMotor28BYJ48
import time
import _thread

MIN_DELAY_S = 0.00125  # Minimum delay between steps in seconds

def test_queued_rotation():
    """Test motor with 4096 steps using queue method with no delay."""
    print("\n" + "="*60)
    print("STEPPER MOTOR QUEUE TEST - 1MS DELAY")
    print("="*60)
    
    # Initialize motor
    print("\nInitializing stepper motor on pins 2, 3, 4, 5...")
    motor = StepperMotor28BYJ48(
        in1_pin=2,
        in2_pin=3,
        in3_pin=4,
        in4_pin=5
    )
    
    # Queue processor thread
    queue_processing = [True]
    
    def queue_processor():
        """Background thread to process stepper command queue."""
        print("[QueueProcessor] Thread started")
        while queue_processing[0]:
            if motor.queue_length() > 0 and not motor.is_executing_now():
                motor.execute_all_queued()
            time.sleep(0.005)
        print("[QueueProcessor] Thread stopped")
    
    try:
        TOTAL_REVS = 5
        print("\nQueueing one full rotation (4096 steps) with 1ms delay per step...")
        
        # Start queue processor thread
        _thread.start_new_thread(queue_processor, ())
        time.sleep(0.1)
        
        start_time = time.ticks_ms()
        
        dir = 1  # Clockwise direction
        for t in range(TOTAL_REVS):
        # Queue the full rotation with 1ms delay
            if t % 2 == 0:
                print(f"\nIteration {t+1}: Clockwise rotation")
                dir = 1
            else:
                print(f"\nIteration {t+1}: Counter-clockwise rotation")
                dir = -1
            
            success = motor.queue_step(4096, direction=dir, delay=MIN_DELAY_S)
            if success:
                print(f"Command queued successfully")
                print(f"Queue length: {motor.queue_length()}")
            else:
                print("ERROR: Failed to queue command")
                return
            
            print("\nWaiting for motor to complete...")
        
        # Wait for completion
        while motor.queue_length() > 0 or motor.is_executing_now():
            time.sleep(0.1)
        
        total_elapsed = time.ticks_diff(time.ticks_ms(), start_time)
        
        print(f"\n" + "="*60)
        print(f"ROTATION COMPLETE")
        print(f"="*60)
        print(f"Total time: {total_elapsed}ms")
        print(f"Total steps: {motor.get_step_count()}")
        print(f"Average time per step: {total_elapsed/(4096*TOTAL_REVS):.2f}ms")
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
    finally:
        # Stop queue processor thread
        queue_processing[0] = False
        time.sleep(0.2)
        
        # Always release motor coils when done
        motor.release()
        print("\nMotor coils released")


if __name__ == "__main__":
    test_queued_rotation()
