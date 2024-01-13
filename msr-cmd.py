import time
import usb.core
import usb.util
import threading
import queue


class MSRDevice:
    def __init__(self, vendor_id=0x0801, product_id=0x0003):
        self.dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if self.dev is None:
            raise ValueError('Device not found')

        # Detach kernel driver and claim interface
        if self.dev.is_kernel_driver_active(0):
            self.dev.detach_kernel_driver(0)
        usb.util.claim_interface(self.dev, 0)

        self.endpoint_address = 0x81  # Endpoint 1 IN
        self.size = 64  # Endpoint size in bytes

        self.running = True
        self.exit_event = threading.Event()
        self.data_queue = queue.Queue()
        self.read_thread = threading.Thread(target=self._read_thread)
        self.read_thread.start()

    def _read_thread(self):
        """ Continuously read data from the device. """
        while not self.exit_event.is_set():
            try:
                data = self.dev.read(self.endpoint_address, self.size, timeout=5000)
                self.data_queue.put(data)
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as err:
                if err.errno == 19:
                    break
                else:
                    raise

    def send_command(self, command):
        """ Send a command to the MSR device using control transfer. """
        bmRequestType = 0x21  # Host to device | Class | Interface
        bRequest = 9  # SET_REPORT
        wValue = 0x300  # Feature
        wIndex = 0  # Interface
        command = self._extend(command)
        self.dev.ctrl_transfer(bmRequestType, bRequest, wValue, wIndex, command)

    @staticmethod
    def _extend(command, length=64):
        """ add padding to cmd bytes to match the endpoint size """
        return command + [0x00] * (length - len(command))

    def get_response(self):
        """ Get the next response from the device. """
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        """ Release the interface and close connection"""
        self.exit_event.set()
        self.read_thread.join()
        usb.util.release_interface(self.dev, 0)
        usb.util.dispose_resources(self.dev)


msr = None

try:
    msr = MSRDevice()
    msr.send_command([0xC5, 0x1B, 0x6d])  # read raw data

    while True:
        response = msr.get_response()
        if response is not None:
            print("Response:", response)
            msr.send_command([0xC5, 0x1B, 0x6d])
        time.sleep(0.5)
except usb.core.USBError as e:
    print("USB Error:", e)
except ValueError as e:
    print("Error:", e)

except KeyboardInterrupt:
    print("Ctrl+C pressed. Stopping...")

finally:
    if msr is not None:
        msr.send_command([0xC2, 0x1B, 0x61])  # reset
        msr.close()
        print("Device closed. Exiting.")
    else:
        print("No device was initialized.")
