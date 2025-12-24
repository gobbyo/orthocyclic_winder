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
    
    # 4-step sequence (wave drive - lower power consumption)
    WAVE_STEP_SEQUENCE = [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
    ]
    
    STEPS_PER_REV = 2048  # With gear reduction (64 * 32 = 2048)
    
    def __init__(self, in1_pin, in2_pin, in3_pin, in4_pin, sequence='full'):
        """
        Initialize the stepper motor.
        
        Args:
            in1_pin, in2_pin, in3_pin, in4_pin: GPIO pin numbers for motor control
            sequence: 'full' for 8-step sequence or 'wave' for 4-step sequence
        """
        self.pins = [
            Pin(in1_pin, Pin.OUT),
            Pin(in2_pin, Pin.OUT),
            Pin(in3_pin, Pin.OUT),
            Pin(in4_pin, Pin.OUT)
        ]
        
        # Turn off all coils immediately to prevent unintended movement
        for pin in self.pins:
            pin.value(0)
        
        # Select step sequence
        if sequence == 'wave':
            self.sequence = self.WAVE_STEP_SEQUENCE
        else:
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
    
    def step(self, steps, direction=1, delay=None):
        """
        Move the motor a specified number of steps.
        
        Args:
            steps: Number of steps to move
            direction: 1 for clockwise, -1 for counter-clockwise
            delay: Delay between steps in seconds (uses default if None)
        """
        if delay is None:
            delay = self.step_delay
            
        for _ in range(abs(steps)):
            self._set_step(self.current_step)
            self.current_step = (self.current_step + direction) % len(self.sequence)
            self.total_steps += 1  # Increment step counter
            time.sleep(delay)
        
        # De-energize coils after completing movement
        self.release()
    
    def rotate(self, degrees, direction=1, delay=None):
        """
        Rotate the motor by a specified number of degrees.
        
        Args:
            degrees: Number of degrees to rotate
            direction: 1 for clockwise, -1 for counter-clockwise
            delay: Delay between steps in seconds
        """
        steps = int((degrees / 360.0) * self.STEPS_PER_REV)
        self.step(steps, direction, delay)
    
    def rotate_continuously(self, direction=1, rpm=10):
        """
        Rotate the motor continuously at a specified RPM.
        Call release() to stop.
        
        Args:
            direction: 1 for clockwise, -1 for counter-clockwise
            rpm: Rotations per minute
        """
        # Calculate delay based on RPM
        delay = 60.0 / (rpm * self.STEPS_PER_REV * len(self.sequence) / 8)
        
        try:
            while True:
                self._set_step(self.current_step)
                self.current_step = (self.current_step + direction) % len(self.sequence)
                time.sleep(delay)
        except KeyboardInterrupt:
            self.release()
    
    def set_speed(self, rpm):
        """
        Set the motor speed in RPM.
        
        Args:
            rpm: Rotations per minute
        """
        self.step_delay = 60.0 / (rpm * self.STEPS_PER_REV * len(self.sequence) / 8)
    
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
    
    def queue_rotate(self, degrees, direction=1, delay=None):
        """
        Add a rotate command to the queue.
        
        Args:
            degrees: Number of degrees to rotate
            direction: 1 for clockwise, -1 for counter-clockwise
            delay: Delay between steps in seconds
        
        Returns:
            bool: True if added successfully, False if queue is full
        """
        steps = int((degrees / 360.0) * self.STEPS_PER_REV)
        return self.queue_step(steps, direction, delay)
    
    def execute_queue(self):
        """
        Execute all commands in the queue sequentially.
        """
        if self.is_executing:
            return False
        
        self.is_executing = True
        
        try:
            while self.command_queue:
                command = self.command_queue.popleft()
                
                if command['type'] == 'step':
                    self.step(
                        command['steps'],
                        command['direction'],
                        command['delay']
                    )
        finally:
            self.is_executing = False
        
        return True
    
    def clear_queue(self):
        """Clear all commands from the queue."""
        self.command_queue.clear()
    
    def queue_length(self):
        """Return the number of commands in the queue."""
        return len(self.command_queue)
    
    def get_step_count(self):
        """Return the total number of steps performed."""
        return self.total_steps
    
    def reset_step_count(self):
        """Reset the step counter to zero."""
        self.total_steps = 0


# Example usage
if __name__ == "__main__":
    # Initialize motor with GPIO pins (adjust these to your wiring)
    motor = StepperMotor28BYJ48(in1_pin=2, in2_pin=3, in3_pin=4, in4_pin=5)

    motor.step(4096, direction=1)  # Step clockwise
    time.sleep(1)
    motor.step(2048, direction=-1)  # Step counter clockwise
    time.sleep(1)
    motor.step(1024, direction=-1)  # Step counter clockwise
    time.sleep(1)
    motor.step(512, direction=-1)  # Step counter clockwise
    time.sleep(1)
    motor.step(512, direction=-1)  # Step counter clockwise
    time.sleep(1)

    for i in range(512):
        motor.step(1, direction=1)  # Step clockwise
        time.sleep(0.05)

    #print("Rotating 360 degrees clockwise...")
    #motor.rotate(360, direction=1)
    #time.sleep(1)
    
    #print("Rotating 360 degrees counter-clockwise...")
    #motor.rotate(360, direction=-1)
    #time.sleep(1)
    
    #print("Rotating at 15 RPM for 5 seconds...")
    #motor.set_speed(15)
    #start_time = time.time()
    #while time.time() - start_time < 5:
    #    motor.step(1, direction=1)
    
    print("Done!")
    motor.release()
