from machine import Pin
import time
from collections import deque

class StepperMotor28BYJ48:
    """
    Driver for 28BYJ-48 stepper motor with ULN2003 driver board.
    This motor has 2048 steps per revolution (with gear reduction).
    """
    
    # 8-step sequence for smoother operation and better torque
    FULL_STEP_SEQUENCE = [
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1],
        [1, 0, 0, 1]
    ]
    
    STEPS_PER_REV = 4096  # With gear reduction and 8-step sequence
    MIN_DELAY_S = 0.00125  # Minimum delay between steps for this motor (1.25ms)  
    
    def __init__(self, in1_pin, in2_pin, in3_pin, in4_pin, logger=None):
        """
        Initialize the stepper motor.
        
        Args:
            in1_pin, in2_pin, in3_pin, in4_pin: GPIO pin numbers for motor control
            logger: Optional logging function to call with log messages
        """
        self.pins = [
            Pin(in1_pin, Pin.OUT, value=0),
            Pin(in2_pin, Pin.OUT, value=0),
            Pin(in3_pin, Pin.OUT, value=0),
            Pin(in4_pin, Pin.OUT, value=0)
        ]
        
        # Use 8-step sequence
        self.sequence = self.FULL_STEP_SEQUENCE
            
        self.current_step = 0
        self.step_delay = self.MIN_DELAY_S  # Default delay between steps (1.25ms)
        
        # Command queue
        self.command_queue = deque((), 100)  # Max 100 commands in queue
        self.is_executing = False
        
        # Step counter (total steps performed)
        self.total_steps = 0
        
        # Logger callback
        self.logger = logger
        
        # Ensure motor is off after initialization
        self.release()
    
    def _set_step(self, step):
        """Set the motor pins according to the step sequence."""
        for i in range(4):
            self.pins[i].value(self.sequence[step][i])
    
    def step(self, steps, direction=1, delay=None, release_after=True):
        """
        Move the motor a specified number of steps.
        
        Args:
            steps: Number of steps to move
            direction: 1 for clockwise, -1 for counter-clockwise
            delay: Delay between steps in seconds (uses default if None)
            release_after: Whether to de-energize coils after movement (default True)
        """
        if delay is None:
            delay = self.step_delay
        
        steps_to_perform = abs(steps)
        for _ in range(steps_to_perform):
            self._set_step(self.current_step)
            self.current_step = (self.current_step + direction) % len(self.sequence)
            time.sleep(delay)
        
        # Update counter once after all steps complete (atomic write)
        self.total_steps += steps_to_perform
        
        # Optionally de-energize coils after completing movement
        if release_after:
            self.release()
    
    def release(self):
        """Turn off all motor coils to save power and prevent heating."""
        for pin in self.pins:
            pin.value(0)
    
    def queue_step(self, steps, direction=1, delay=None):
        """
        Add a step command to the queue.
        
        Args:
            steps: Number of steps to move
            direction: 1 for clockwise, -1 for counter-clockwise
            delay: Delay between steps in seconds (uses default if None)
        
        Returns:
            bool: True if added successfully, False if queue is full
        """
        if len(self.command_queue) >= 100:
            return False
        
        self.command_queue.append({
            'type': 'step',
            'steps': steps,
            'direction': direction,
            'delay': delay
        })
        return True
    
    def execute_queue(self):
        """
        Execute one command from the queue.
        This allows new commands to be processed more responsively.
        """
        # Check if already executing (atomic read)
        if self.is_executing:
            return False
        
        # Check if queue has commands
        if not self.command_queue:
            return False
        
        # Set executing flag (atomic write)
        self.is_executing = True
        
        # Get command from queue (popleft is atomic)
        command = self.command_queue.popleft()
        
        # Execute without any locks to ensure smooth motion
        try:
            if command['type'] == 'step':
                # Always execute without releasing to maintain smooth motion
                self.step(
                    command['steps'],
                    command['direction'],
                    command['delay'],
                    release_after=False
                )
        finally:
            # Clear executing flag (atomic write)
            self.is_executing = False
        
        return True
    
    def execute_all_queued(self):
        """
        Execute all commands in the queue continuously.
        Keeps processing until queue is empty.
        Release coils only when completely done.
        """
        if not self.command_queue:
            return
        
        # Set executing flag once for the entire batch
        self.is_executing = True
        
        try:
            # Process all commands without releasing executing flag
            while self.command_queue:
                command = self.command_queue.popleft()
                
                if command['type'] == 'step':
                    # Log command details before execution
                    direction_str = "forward" if command['direction'] == 1 else "backward"
                    queue_remaining = len(self.command_queue) + 1  # Include current command
                    log_msg = f"Executing: {command['steps']} steps {direction_str} (queue: {queue_remaining})"
                    if self.logger:
                        self.logger(log_msg)
                    else:
                        print(log_msg)
                    
                    # Execute without releasing coils or changing executing flag
                    self.step(
                        command['steps'],
                        command['direction'],
                        command['delay'],
                        release_after=False
                    )
        finally:
            # Clear executing flag only after all commands complete
            self.is_executing = False
            
            # Check if new commands were added during execution
            if not self.command_queue:
                time.sleep(0.05)  # Small delay before checking again
                if not self.command_queue:  # Double-check queue is still empty
                    self.release()
    
    def clear_queue(self):
        """Clear all commands from the queue."""
        while self.command_queue:
            self.command_queue.popleft()
    
    def queue_length(self):
        """Return the number of commands in the queue."""
        return len(self.command_queue)
    
    def is_executing_now(self):
        """Check if motor is currently executing (atomic read, no lock)."""
        return self.is_executing
    
    def get_step_count(self):
        """Return the total number of steps performed (atomic read)."""
        return self.total_steps
    
    def reset_step_count(self):
        """Reset the step counter to zero."""
        self.total_steps = 0


# Simple test function
def test_stepper_motor():
    """
    Simple test to verify stepper motor functionality.
    Tests forward rotation, backward rotation, and queued commands.
    """
    print("\n" + "="*60)
    print("STEPPER MOTOR TEST")
    print("="*60)
    
    # Initialize motor
    print("\nInitializing stepper motor on pins 2, 3, 4, 5...")
    motor = StepperMotor28BYJ48(
        in1_pin=2,
        in2_pin=3,
        in3_pin=4,
        in4_pin=5
    )
    
    try:
        # Test 1: Forward rotation
        print("\n--- Test 1: Forward Rotation, half turn ---")
        motor.step(int(StepperMotor28BYJ48.STEPS_PER_REV/2), direction=1, delay=0.002)
        print(f"Total steps: {motor.get_step_count()}")
        time.sleep(1)
        
        # Test 2: Backward rotation
        print("\n--- Test 2: Backward Rotation, half turn ---")
        motor.step(int(StepperMotor28BYJ48.STEPS_PER_REV/2), direction=-1, delay=0.002)
        print(f"Total steps: {motor.get_step_count()}")
        time.sleep(1)
        
        # Test 3: Full rotation
        print("\n--- Test 3: Full Rotation ---")
        motor.step(StepperMotor28BYJ48.STEPS_PER_REV, direction=1, delay=0.001)
        print(f"Total steps: {motor.get_step_count()}")
        time.sleep(1)
        
        # Test 4: Queue commands
        print("\n--- Test 4: Queued Commands, half rotations ---")
        print("Queueing 3 commands...")
        motor.queue_step(int(StepperMotor28BYJ48.STEPS_PER_REV/2), direction=1, delay=0.002)
        motor.queue_step(int(StepperMotor28BYJ48.STEPS_PER_REV/2), direction=-1, delay=0.002)
        motor.queue_step(int(StepperMotor28BYJ48.STEPS_PER_REV/2), direction=1, delay=0.002)
        print(f"Queue length: {motor.queue_length()}")
        
        print("Executing queued commands...")
        motor.execute_all_queued()
        print(f"Total steps: {motor.get_step_count()}")
        print(f"Queue length: {motor.queue_length()}")
        
        print("\n" + "="*60)
        print("TEST COMPLETE - All tests passed!")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
    finally:
        # Always release motor coils when done
        motor.release()
        print("\nMotor coils released")


if __name__ == "__main__":
    test_stepper_motor()
