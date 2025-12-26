"""
Winder Coordination Test
Simulates coordinated winder motor and stepper motor operation for first layer winding.
Automatically calculates maximum safe winder RPM based on stepper motor limitations.
"""

from micropython.esp32s2.stepper_motor import StepperMotor28BYJ48
import time
import _thread

try:
    import ujson as json
except ImportError:
    import json


class WinderCoordinator:
    """Coordinates winder motor and stepper motor for multi-layer winding."""
    
    def __init__(self, bobbin_length_mm, wire_diameter_mm, num_layers=1, config=None):
        """
        Initialize the winder coordinator.
        
        Args:
            bobbin_length_mm: Length of bobbin to wind (mm)
            wire_diameter_mm: Diameter of wire being wound (mm)
            num_layers: Number of layers to wind (default 1)
            config: Optional config dict with physical constants
        """
        # Load physical constants from config or use defaults
        if config and 'winder' in config:
            winder_config = config['winder']
            self.SLOTS_PER_REV = winder_config.get('slots_per_rev', 16)
            self.LEAD_SCREW_PITCH = winder_config.get('lead_screw_pitch_mm', 1.25)
            self.STEPS_PER_REV = winder_config.get('steps_per_rev', 4096)
            self.MIN_STEP_DELAY = winder_config.get('min_step_delay_ms', 1.0) / 1000.0  # Convert ms to seconds
            self.ramp_start_rpm = winder_config.get('ramp_start_rpm', 5.0)
            self.ramp_duration = winder_config.get('ramp_duration_s', 3.0)
            self.ramp_down_wires = winder_config.get('ramp_down_wires', 3)
            self.ramp_end_rpm = winder_config.get('ramp_end_rpm', 5.0)
            self.ramp_down_duration = winder_config.get('ramp_down_duration_s', 2.0)
        else:
            # Default values
            self.SLOTS_PER_REV = 16
            self.LEAD_SCREW_PITCH = 1.25
            self.STEPS_PER_REV = 4096
            self.MIN_STEP_DELAY = 0.001
            self.ramp_start_rpm = 5.0
            self.ramp_duration = 3.0
            self.ramp_down_wires = 3
            self.ramp_end_rpm = 5.0
            self.ramp_down_duration = 2.0
        
        self.bobbin_length = bobbin_length_mm
        self.wire_diameter = wire_diameter_mm
        self.num_layers = num_layers
        
        # Calculate winding parameters
        self.calculate_parameters()
        
        # Initialize stepper motor
        self.stepper = StepperMotor28BYJ48(
            in1_pin=2,
            in2_pin=3,
            in3_pin=4,
            in4_pin=5
        )
        
        # State tracking
        self.current_layer = 1
        self.current_wire = 0
        self.current_slot = 0
        self.current_direction = 1  # 1 = forward, -1 = reverse
        self.layer_complete = False
        self.all_layers_complete = False
        self.layer_announced = True  # Layer 1 announced at simulation start
        self.queue_processing = [True]
        
        # Track total steps queued to handle fractional steps per slot
        self.total_steps_queued = 0
    
    def calculate_parameters(self):
        """Calculate all timing and motion parameters."""
        # Wire count per layer
        self.wires_per_layer = int(self.bobbin_length / self.wire_diameter)
        self.total_wires = self.wires_per_layer * self.num_layers
        
        # Stepper motion per wire
        self.steps_per_wire = int((self.wire_diameter / self.LEAD_SCREW_PITCH) * self.STEPS_PER_REV)
        self.time_per_wire = self.steps_per_wire * self.MIN_STEP_DELAY  # seconds
        
        # Total stepper motion for all layers
        self.steps_per_layer = self.steps_per_wire * self.wires_per_layer
        self.total_steps = self.steps_per_layer * self.num_layers
        self.total_time = self.total_steps * self.MIN_STEP_DELAY  # seconds
        
        # Calculate maximum safe winder RPM
        # Stepper must move one wire width in the time winder wraps one wire
        # Max stepper linear speed = 1/MIN_STEP_DELAY steps/sec × PITCH/STEPS_PER_REV mm/step
        max_stepper_linear_speed = (1.0 / self.MIN_STEP_DELAY) * (self.LEAD_SCREW_PITCH / self.STEPS_PER_REV)  # mm/s
        
        # Winder RPM needed: one revolution wraps wire_diameter worth of wire
        # Linear speed needed = winder_rpm × wire_diameter
        # So: winder_rpm = max_stepper_linear_speed / wire_diameter (in rev/s)
        max_winder_rps = max_stepper_linear_speed / self.wire_diameter
        self.max_winder_rpm = max_winder_rps * 60.0
        
        # Use 90% of max for safety margin
        self.safe_winder_rpm = self.max_winder_rpm * 0.90
        
        # Calculate slots per wire movement
        # Total slots for one layer
        self.slots_per_layer = self.wires_per_layer * self.SLOTS_PER_REV
        self.total_slots = self.slots_per_layer * self.num_layers
        
        # Steps to move per slot trigger (per layer)
        self.steps_per_slot = self.steps_per_layer / self.slots_per_layer
    
    def print_parameters(self):
        """Print all calculated parameters."""
        print("\n" + "="*70)
        print("WINDER COORDINATION PARAMETERS")
        print("="*70)
        print(f"\nPhysical Setup:")
        print(f"  Bobbin length: {self.bobbin_length}mm")
        print(f"  Wire diameter: {self.wire_diameter}mm")
        print(f"  Lead screw pitch: {self.LEAD_SCREW_PITCH}mm (M8x1.25)")
        print(f"  Optical slots per rev: {self.SLOTS_PER_REV}")
        print(f"  Number of layers: {self.num_layers}")
        
        print(f"\nLayer Calculations:")
        print(f"  Wires per layer: {self.wires_per_layer}")
        print(f"  Total wires (all layers): {self.total_wires}")
        print(f"  Slots per layer: {self.slots_per_layer}")
        print(f"  Total slot triggers: {self.total_slots}")
        
        print(f"\nStepper Motor:")
        print(f"  Steps per wire: {self.steps_per_wire}")
        print(f"  Steps per layer: {self.steps_per_layer}")
        print(f"  Total steps (all layers): {self.total_steps}")
        print(f"  Steps per slot trigger: {self.steps_per_slot:.2f}")
        print(f"  Minimum step delay: {self.MIN_STEP_DELAY*1000}ms")
        print(f"  Time per wire: {self.time_per_wire:.3f}s")
        print(f"  Total time: {self.total_time:.1f}s ({self.total_time/60:.2f} min)")
        
        print(f"\nWinder Motor Speed Limits:")
        print(f"  Maximum theoretical RPM: {self.max_winder_rpm:.2f}")
        print(f"  Safe operating RPM (90%): {self.safe_winder_rpm:.2f}")
        print(f"  Time per revolution: {60.0/self.safe_winder_rpm:.2f}s")
        print("="*70)
    
    def simulate_slot_trigger(self, current_rpm=None):
        """
        Simulate a slot trigger from optical sensor.
        Queue stepper movement for this slot interval.
        
        Args:
            current_rpm: Current winder RPM for calculating appropriate step delay
        """
        if self.all_layers_complete:
            return False
        
        # Announce layer start on first slot of new layer
        if not self.layer_announced:
            direction_str = "forward" if self.current_direction == 1 else "reverse"
            print(f"\n[LAYER {self.current_layer} START] Direction: {direction_str}")
            self.layer_announced = True
        
        # Calculate target position after this slot (relative to current layer start)
        slot_in_layer = self.current_slot % self.slots_per_layer
        target_steps_in_layer = int((slot_in_layer + 1) * self.steps_per_slot)
        
        # Calculate steps already queued in this layer
        layer_start_steps = (self.current_layer - 1) * self.steps_per_layer
        steps_queued_in_layer = self.total_steps_queued - layer_start_steps
        
        # Calculate how many steps to move
        steps_to_move = target_steps_in_layer - steps_queued_in_layer
        
        # Calculate step delay based on current RPM for smooth motion
        if current_rpm and current_rpm < self.safe_winder_rpm:
            # During ramp-up or ramp-down, adjust step delay to match RPM
            # Time available for this slot trigger
            time_per_rev = 60.0 / current_rpm
            time_per_slot = time_per_rev / self.SLOTS_PER_REV
            # Divide by number of steps to get delay per step
            step_delay = time_per_slot / steps_to_move if steps_to_move > 0 else self.MIN_STEP_DELAY
            # Don't go below minimum
            step_delay = max(step_delay, self.MIN_STEP_DELAY)
        else:
            # At full speed, use minimum delay
            step_delay = self.MIN_STEP_DELAY
        
        # Queue the movement (only if steps > 0)
        if steps_to_move > 0:
            success = self.stepper.queue_step(
                steps_to_move,
                direction=self.current_direction,
                delay=step_delay
            )
            
            if not success:
                print(f"[WARNING] Failed to queue steps at slot {self.current_slot}")
                return False
            
            # Update total steps queued
            self.total_steps_queued += steps_to_move
        
        # Update counters
        self.current_slot += 1
        wire_in_layer = (self.current_slot % self.slots_per_layer) // self.SLOTS_PER_REV
        
        # Check if we've moved to next wire position
        if self.current_slot % self.SLOTS_PER_REV == 0:
            self.current_wire += 1
            if wire_in_layer < self.wires_per_layer:
                print(f"[Layer {self.current_layer}] Wire {wire_in_layer}/{self.wires_per_layer} complete")
        
        # Check if current layer queueing is complete
        if self.current_slot % self.slots_per_layer == 0 and self.current_slot > 0:
            self.layer_complete = True
            print(f"\n[QUEUEING COMPLETE - Layer {self.current_layer}] All {steps_queued_in_layer + steps_to_move} steps queued")
            print(f"Queue length: {self.stepper.queue_length()} commands remaining")
            
            # Check if all layers are complete
            if self.current_layer >= self.num_layers:
                self.all_layers_complete = True
                print(f"\n[ALL LAYERS QUEUED] Total {self.total_steps_queued} steps queued")
            else:
                # Start next layer
                self.start_next_layer()
        
        return True
    
    def start_next_layer(self):
        """Start the next layer with reversed direction."""
        self.current_layer += 1
        self.layer_complete = False
        self.current_direction *= -1  # Reverse direction
        self.layer_announced = False  # Will announce on first slot trigger
    
    def queue_processor(self):
        """Background thread to process stepper command queue."""
        print("[QueueProcessor] Thread started")
        while self.queue_processing[0]:
            if self.stepper.queue_length() > 0 and not self.stepper.is_executing_now():
                self.stepper.execute_all_queued()
            time.sleep(0.005)
        print("[QueueProcessor] Thread stopped")
    
    def run_simulation(self):
        """Run the complete multi-layer winding simulation."""
        print("\n" + "="*70)
        print(f"STARTING {self.num_layers}-LAYER WINDING SIMULATION")
        print("="*70)
        
        # Start queue processor thread
        _thread.start_new_thread(self.queue_processor, ())
        time.sleep(0.1)
        
        print(f"\nWinder motor ramp-up: {self.ramp_start_rpm:.1f} RPM → {self.safe_winder_rpm:.2f} RPM over {self.ramp_duration:.1f}s")
        print(f"Ramp-down: Last {self.ramp_down_wires} wires slow to {self.ramp_end_rpm:.1f} RPM over {self.ramp_down_duration:.1f}s")
        print(f"Expected completion time: {self.total_time:.1f}s\n")
        
        start_time = time.ticks_ms()
        last_slot_time = start_time
        last_rpm = self.ramp_start_rpm
        ramp_down_start_time = None
        
        try:
            # Simulate slot triggers with dynamic RPM
            while not self.all_layers_complete:
                current_time = time.ticks_ms()
                elapsed_time = time.ticks_diff(current_time, start_time) / 1000.0  # seconds
                
                # Determine if we should start ramping down
                wires_remaining = self.total_wires - self.current_wire
                in_last_layer = (self.current_layer == self.num_layers)
                should_ramp_down = in_last_layer and wires_remaining <= self.ramp_down_wires
                
                # Calculate current RPM
                if should_ramp_down:
                    # Ramp down to end RPM
                    if ramp_down_start_time is None:
                        ramp_down_start_time = current_time
                        print(f"\n[RAMP DOWN START] {wires_remaining} wires remaining, slowing to {self.ramp_end_rpm:.1f} RPM\n")
                    
                    ramp_down_elapsed = time.ticks_diff(current_time, ramp_down_start_time) / 1000.0
                    if ramp_down_elapsed < self.ramp_down_duration:
                        # Linear ramp from current speed to end RPM
                        ramp_progress = ramp_down_elapsed / self.ramp_down_duration
                        current_rpm = self.safe_winder_rpm - (self.safe_winder_rpm - self.ramp_end_rpm) * ramp_progress
                    else:
                        # At minimum speed
                        current_rpm = self.ramp_end_rpm
                elif elapsed_time < self.ramp_duration:
                    # Linear ramp from start_rpm to safe_winder_rpm
                    ramp_progress = elapsed_time / self.ramp_duration
                    current_rpm = self.ramp_start_rpm + (self.safe_winder_rpm - self.ramp_start_rpm) * ramp_progress
                else:
                    # At full speed
                    current_rpm = self.safe_winder_rpm
                
                # Calculate slot interval based on current RPM
                time_per_revolution = 60.0 / current_rpm
                slot_interval = time_per_revolution / self.SLOTS_PER_REV
                
                # Show RPM changes
                if abs(current_rpm - last_rpm) >= 1.0:  # Log when RPM changes by 1 or more
                    print(f"[Winder RPM: {current_rpm:.1f}] Slot interval: {slot_interval*1000:.2f}ms")
                    last_rpm = current_rpm
                
                # Check if it's time for next slot trigger
                if time.ticks_diff(current_time, last_slot_time) >= slot_interval * 1000:
                    self.simulate_slot_trigger(current_rpm)
                    last_slot_time = current_time
                
                time.sleep(0.001)  # Small sleep to prevent busy waiting
            
            # Wait for all queued commands to complete
            print(f"\nWaiting for stepper motor to execute remaining queued commands...")
            print(f"Commands in queue: {self.stepper.queue_length()}")
            print(f"Steps executed so far: {self.stepper.get_step_count()}/{self.total_steps}")
            
            # Wait until all expected steps are executed
            while True:
                queue_len = self.stepper.queue_length()
                is_exec = self.stepper.is_executing_now()
                steps_done = self.stepper.get_step_count()
                
                # Exit only when queue is empty, not executing, and all steps are done
                if queue_len == 0 and not is_exec and steps_done >= self.total_steps:
                    break
                
                # Also exit if we've been waiting too long (safety timeout)
                elapsed = time.ticks_diff(time.ticks_ms(), start_time) / 1000.0
                if elapsed > self.total_time * 2:  # 2x expected time
                    print(f"\n[WARNING] Timeout waiting for completion!")
                    print(f"Queue: {queue_len}, Executing: {is_exec}, Steps: {steps_done}/{self.total_steps}")
                    break
                
                time.sleep(0.1)
            
            print(f"\n[EXECUTION COMPLETE] All motor movements finished")
            print(f"Final steps executed: {self.stepper.get_step_count()}/{self.total_steps}")
            
            total_elapsed = time.ticks_diff(time.ticks_ms(), start_time) / 1000.0  # Convert to seconds
            
            print("\n" + "="*70)
            print("SIMULATION COMPLETE")
            print("="*70)
            print(f"Total time: {total_elapsed:.2f}s ({total_elapsed/60:.2f} min)")
            print(f"Expected time: {self.total_time:.2f}s")
            print(f"Time difference: {abs(total_elapsed - self.total_time):.2f}s")
            print(f"Total steps executed: {self.stepper.get_step_count()}")
            print(f"Expected steps: {self.total_steps}")
            print("="*70)
            
        except KeyboardInterrupt:
            print("\n\nSimulation interrupted by user")
        except Exception as e:
            print(f"\n\nSimulation failed with error: {e}")
        finally:
            # Stop queue processor thread
            self.queue_processing[0] = False
            time.sleep(0.2)
            
            # Release motor
            self.stepper.release()
            print("\nMotor coils released")


def load_config():
    """Load complete configuration from config file."""
    try:
        with open('test/test_winder_coordination.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load test_winder_coordination.json: {e}")
        return None


def load_wire_specs():
    """Load wire specifications from config file."""
    config = load_config()
    if config and 'wire_types' in config:
        return config['wire_types']
    
    # Return defaults if config not available
    return {
        'AWG_20': {'diameter_mm': 0.812},
        'AWG_22': {'diameter_mm': 0.644}
    }


def main():
    """Main test function."""
    print("\n" + "="*70)
    print("WINDER COORDINATION TEST")
    print("Multi-Layer Winding Simulation")
    print("="*70)
    
    # Load configuration
    config = load_config()
    wire_specs = load_wire_specs()
    
    # Get parameters from config or use defaults
    bobbin_length = 10.0  # Default
    num_layers = 2  # Default
    if config and 'winder' in config:
        bobbin_length = config['winder'].get('bobbin_length_mm', 10.0)
        num_layers = config['winder'].get('num_layers', 2)
    
    # Calculate parameters for both wire types
    print("\n" + "="*70)
    print("COMPARING WIRE TYPES")
    print("="*70)
    
    coordinators = {}
    for wire_type in ['AWG_20', 'AWG_22']:
        if wire_type in wire_specs and 'diameter_mm' in wire_specs[wire_type]:
            wire_diameter = wire_specs[wire_type]['diameter_mm']
        else:
            # Fallback values if config missing
            wire_diameter = 0.812 if wire_type == 'AWG_20' else 0.644
        
        print(f"\n{wire_type} ({wire_diameter}mm):")
        
        coordinator = WinderCoordinator(bobbin_length, wire_diameter, num_layers, config)
        coordinators[wire_type] = coordinator
        coordinator.print_parameters()
    
    # Ask user which wire to simulate
    print("\n" + "="*70)
    print("SELECT WIRE TYPE TO SIMULATE")
    print("="*70)
    
    # Get wire diameters for display
    awg20_dia = wire_specs['AWG_20']['diameter_mm'] if 'AWG_20' in wire_specs and 'diameter_mm' in wire_specs['AWG_20'] else 0.812
    awg22_dia = wire_specs['AWG_22']['diameter_mm'] if 'AWG_22' in wire_specs and 'diameter_mm' in wire_specs['AWG_22'] else 0.644
    
    print(f"1. AWG_20 ({awg20_dia}mm)")
    print(f"2. AWG_22 ({awg22_dia}mm)")
    print("3. Exit")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == '1':
        wire_type = 'AWG_20'
    elif choice == '2':
        wire_type = 'AWG_22'
    else:
        print("Exiting...")
        return
    
    print(f"\nStarting simulation with {wire_type}...")
    print("Press Ctrl+C to stop at any time.\n")
    
    # Run simulation for selected wire
    coordinators[wire_type].run_simulation()


if __name__ == "__main__":
    main()
