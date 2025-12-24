import network
import time
from common.config import Config
import common.logging as logging
import ujson
import os
from microdot import Microdot, send_file, Request
import sys
import _thread
# Add parent directory to path for importing stepper_motor
from stepper_motor import StepperMotor28BYJ48

class AP_IF_Wifi:
    def __init__(self, configfilename, ssid='orthocyclic_winder', password='400coils'):
        self.ip_address = ""
        self.config = Config(configfilename)
        self.uart = None
        # AP_IF=Access Point interface of the network module. 
        # Setting used to have your microcontroller act as a Wi-Fi access point, 
        # allowing other devices to connect to it.
        self.wifi = network.WLAN(network.AP_IF)
        self.waittime = 15
        self.ssid = ssid
        self.password = password
        Request.max_content_length = 1024 * 1024  # 1MB (change as needed)
        
        # Initialize stepper motor (adjust GPIO pins as needed)
        self.stepper = StepperMotor28BYJ48(in1_pin=2, in2_pin=3, in3_pin=4, in4_pin=5)
        # Explicitly ensure motor is off
        self.stepper.release()
        
        # Queue processing control
        self.queue_processing = True
        self.queue_thread = None
        
        # Track last status for change detection
        self.last_status = {'queue_length': 0, 'is_executing': False, 'total_steps': 0}

    def __del__(self):
        self.wifi.disconnect()
        time.sleep(1)
    
    def start_wifi(self):
        """
        Start the WiFi access point with the given SSID and password.
        """
        try:
            self.wifi.config(ssid=self.ssid, password=self.password)
            self.wifi.active(True)
            i = 10
            while not self.wifi.active() and i > 0:
                time.sleep(2)
                i -= 1
                logging.info("Waiting for WiFi AP to be active")

            if self.wifi.active():
                self.ip_address = self.wifi.ifconfig()[0]
                logging.info(f'Display wifi is active, IP={self.ip_address}')
            else:
                logging.error("Failed to activate WiFi AP")
        except Exception as e:
            logging.error(f"Exception occurred while starting WiFi: {e}")
            self.ip_address = ""
    
    def _queue_processor_thread(self):
        """Background thread to process stepper command queue."""
        logging.info("Queue processor thread started")
        while self.queue_processing:
            if self.stepper.queue_length() > 0 and not self.stepper.is_executing:
                logging.info(f"Processing queue with {self.stepper.queue_length()} commands")
                self.stepper.execute_queue()
            time.sleep(0.1)  # Check queue every 100ms
        logging.info("Queue processor thread stopped")
    
    def start_queue_processor(self):
        """Start the background queue processing thread."""
        if self.queue_thread is None:
            self.queue_processing = True
            self.queue_thread = _thread.start_new_thread(self._queue_processor_thread, ())
            logging.info("Queue processor started")
    
    def stop_queue_processor(self):
        """Stop the background queue processing thread."""
        self.queue_processing = False
        logging.info("Queue processor stopped")
    
    def shutdownWifi(self):
        logging.info("Shutting down WiFi AP")
        self.stop_queue_processor()
        if self.wifi.isconnected():
            self.wifi.disconnect()
            logging.info("Disconnected from WiFi")
        else:
            logging.warning("WiFi was not connected")
        
        self.wifi.active(False)
        if not self.wifi.active():
            logging.info("WiFi interface deactivated")
        else:
            logging.error("Failed to deactivate WiFi interface")

    def run_server(self):
        app = Microdot()

        @app.route('/')
        async def index(request):
            logging.info("returning stepper page")
            #self.createIndex()
            return send_file('html/stepper.html')

        @app.get('/stepper')
        async def stepper_page(request):
            logging.info('returning stepper motor control page')
            return send_file('html/stepper.html')
        
        @app.post('/stepper/move')
        async def stepper_move(request):
            logging.info('Received stepper motor move command')
            try:
                form = request.body.decode('utf-8')
                data = ujson.loads(form)
                steps = data.get('steps', 1024)
                direction = data.get('direction', 1)
                delay = data.get('delay', None)
                
                logging.info(f'Queueing stepper: steps={steps}, direction={direction}')
                
                # Queue the motor command instead of executing directly
                success = self.stepper.queue_step(steps, direction, delay)
                
                if success:
                    return ujson.dumps({
                        'status': 'success',
                        'message': f'Queued {steps} steps {"forward" if direction == 1 else "backward"}',
                        'queue_length': self.stepper.queue_length()
                    }), 200, {'Content-Type': 'application/json'}
                else:
                    return ujson.dumps({
                        'status': 'error',
                        'message': 'Queue is full',
                        'queue_length': self.stepper.queue_length()
                    }), 503, {'Content-Type': 'application/json'}
            except Exception as e:
                logging.error(f"Error queueing stepper motor command: {e}")
                return ujson.dumps({
                    'status': 'error',
                    'message': str(e)
                }), 500, {'Content-Type': 'application/json'}

        @app.get('/stepper/status')
        async def stepper_status(request):
            try:
                current_status = {
                    'queue_length': self.stepper.queue_length(),
                    'is_executing': self.stepper.is_executing,
                    'total_steps': self.stepper.get_step_count()
                }
                
                # Only log if status has changed
                if current_status != self.last_status:
                    logging.info(f'Status changed: queue={current_status["queue_length"]}, executing={current_status["is_executing"]}, steps={current_status["total_steps"]}')
                    self.last_status = current_status.copy()
                
                response_data = {'status': 'success'}
                response_data.update(current_status)
                return ujson.dumps(response_data), 200, {'Content-Type': 'application/json'}
            except Exception as e:
                logging.error(f"Error getting stepper status: {e}")
                return ujson.dumps({
                    'status': 'error',
                    'message': str(e)
                }), 500, {'Content-Type': 'application/json'}
        
        @app.post('/stepper/clear')
        async def stepper_clear(request):
            logging.info('Clearing stepper command queue')
            try:
                self.stepper.clear_queue()
                return ujson.dumps({
                    'status': 'success',
                    'message': 'Queue cleared'
                }), 200, {'Content-Type': 'application/json'}
            except Exception as e:
                logging.error(f"Error clearing stepper queue: {e}")
                return ujson.dumps({
                    'status': 'error',
                    'message': str(e)
                }), 500, {'Content-Type': 'application/json'}
        
        @app.post('/stepper/reset_counter')
        async def stepper_reset_counter(request):
            logging.info('Resetting stepper step counter')
            try:
                self.stepper.reset_step_count()
                return ujson.dumps({
                    'status': 'success',
                    'message': 'Step counter reset to 0'
                }), 200, {'Content-Type': 'application/json'}
            except Exception as e:
                logging.error(f"Error resetting stepper counter: {e}")
                return ujson.dumps({
                    'status': 'error',
                    'message': str(e)
                }), 500, {'Content-Type': 'application/json'}

        @app.get('/shutdown')
        async def shutdown(request):
            print('shutting down microdot web service')
            logging.info('shutting down microdot web service')
            request.app.shutdown()
            return 'Shutting down', 200

        app.run(host=self.ip_address, port=80)

# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        apifWifi = AP_IF_Wifi("config.json")
        apifWifi.start_wifi()
        if apifWifi.ip_address != "":
            apifWifi.start_queue_processor()  # Start queue processing before server
            apifWifi.run_server()
        apifWifi.shutdownWifi()
    finally:
        logging.info('deleted apifWifi instance')
        time.sleep(1)