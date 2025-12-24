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
    
    STEPS_PER_REV = 2048  # With gear reduction (64 * 32 = 2048)
    
    def __init__(self, in1_pin, in2_pin, in3_pin, in4_pin):
        """
        Initialize the stepper motor.
        
        Args:
            in1_pin, in2_pin, in3_pin, in4_pin: GPIO pin numbers for motor control
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
        self.step_delay = 0.002  # Default delay between steps (2ms)
        
        # Command queue
        self.command_queue = deque((), 100)  # Max 100 commands in queue
        self.is_executing = False
        
        # Step counter (total steps performed)
        self.total_steps = 0
        
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
        executed_any = False
        while self.command_queue:
            if self.execute_queue():
                executed_any = True
        
        # Only release coils after ALL commands are done
        if executed_any:
            time.sleep(0.05)  # Small delay before checking if truly done
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
