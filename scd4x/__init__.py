import struct
import time

from smbus2 import SMBus, i2c_msg

from scd4x.crc import crc8

__version__ = "0.0.1"


SOFT_RESET = 0x3646
FACTORY_RESET = 0x3632
FORCE_RECALIBRATION = 0x362F
SELF_TEST = 0x3639
DATA_READY = 0xE4B8
STOP_PERIODIC_MEASUREMENT = 0x3F86
START_PERIODIC_MEASUREMENT = 0x21B1
START_LOW_POWER_PERIODIC_MEASUREMENT = 0x21AC
READ_MEASUREMENT = 0xEC05
SERIAL_NUMBER = 0x3682
GET_TEMP_OFFSET = 0x2318
SET_TEMP_OFFSET = 0x241D
GET_ALTITUDE = 0x2322
SET_ALTITUDE = 0x2427
SET_PRESSURE = 0xE000
PERSIST_SETTINGS = 0x3615
GET_ASCE = 0x2313
SET_ASCE = 0x2416


DEFAULT_I2C_ADDRESS = 0x62


MSG_COMMAND_VALUE = struct.Struct(">HHB")
MSG_COMMAND = struct.Struct(">H")


class SCD4X:
    def __init__(self, address=None, quiet=True):
        self.co2 = 0
        self.temperature = 0
        self.relative_humidity = 0

        if address is None:
            address = DEFAULT_I2C_ADDRESS
        self.address = address

        self.bus = SMBus(1)

        self.stop_periodic_measurement()

        serial = self.get_serial_number()

        if not quiet:
            print(f"SCD4X, Serial: {serial:06x}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.bus.close()

    def rdwr(self, command, value=None, response_length=0, delay=0):
        if value is not None:
            msg_w = i2c_msg.write(self.address, MSG_COMMAND_VALUE.pack(command, value, self.crc8(value)))
        else:
            msg_w = i2c_msg.write(self.address, MSG_COMMAND.pack(command))

        self.bus.i2c_rdwr(msg_w)

        time.sleep(delay / 1000.0)

        response_length *= 3

        if response_length > 0:
            msg_r = i2c_msg.read(self.address, response_length)
            self.bus.i2c_rdwr(msg_r)

            result = bytes(msg_r)
            data = []
            for chunk in range(0, len(result), 3):
                if self.crc8(result[chunk : chunk + 2]) != result[chunk + 2]:
                    raise ValueError("ICP10125: Invalid CRC8 in response.")
                data.append(int.from_bytes(result[chunk : chunk + 2], "big"))
            if len(data) == 1:
                return data[0]
            else:
                return data

        return []

    def reset(self):
        """Resets to user settings from EEPROM"""
        self.rdwr(SOFT_RESET, delay=20)

    def factory_reset(self):
        """Reset to factory fresh condition.

        Resets user config in EEPROM.

        """
        self.stop_periodic_measurement()
        self.rdwr(FACTORY_RESET, delay=1200)

    def self_test(self):
        self.stop_periodic_measurement()
        response = self.rdwr(SELF_TEST, response_length=1, delay=10000)
        if response > 0:
            raise RuntimeError("Self test failed!")

    def measure(self, blocking=True, timeout=10):
        t_start = time.perf_counter()
        while not self.data_ready():
            if not blocking:
                return
            if time.perf_counter() - t_start > timeout:
                raise RuntimeError("Timeout waiting for data ready.")
            time.sleep(0.1)

        response = self.rdwr(READ_MEASUREMENT, response_length=3, delay=1)
        self.co2 = response[0]
        self.temperature = -45 + 175.0 * response[1] / (1 << 16)
        self.relative_humidity = 100.0 * response[2] / (1 << 16)

        return self.co2, self.temperature, self.relative_humidity

    def data_ready(self):
        response = self.rdwr(DATA_READY, response_length=1, delay=1)
        return response & 0x07FF

    def get_serial_number(self):
        response = self.rdwr(SERIAL_NUMBER, response_length=3, delay=1)
        return (response[0] << 32) | (response[1] << 16) | response[2]

    def start_periodic_measurement(self, low_power=False):
        if low_power:
            self.rdwr(START_LOW_POWER_PERIODIC_MEASUREMENT)
        else:
            self.rdwr(START_PERIODIC_MEASUREMENT)

    def stop_periodic_measurement(self):
        self.rdwr(STOP_PERIODIC_MEASUREMENT, delay=500)

    def set_ambient_pressure(self, ambient_pressure):
        self.rdwr(SET_PRESSURE, value=ambient_pressure)

    def set_temperature_offset(self, temperature_offset):
        if temperature_offset > 374:
            raise ValueError("Temperature offset must be <= 374c")
        offset = int(temperature_offset * (1 << 16) / 175)
        self.rdwr(SET_TEMP_OFFSET, value=offset)

    def get_temperature_offset(self):
        response = self.rdwr(GET_TEMP_OFFSET, response_length=1, delay=1)
        return 175.0 * response / (1 << 16)

    def set_altitude(self, altitude):
        self.rdwr(SET_ALTITUDE, value=altitude, delay=1)

    def get_altitude(self):
        return self.rdwr(GET_ALTITUDE, response_length=1, delay=1)

    def set_automatic_self_calibration_enabled(self, value):
        self.rdwr(SET_ASCE, value=int(value))

    def get_automatic_self_calibration_enabled(self):
        return bool(self.rdwr(GET_ASCE, response_length=1, delay=1))

    def persist_settings(self):
        self.rdwr(PERSIST_SETTINGS, delay=800)

    @staticmethod
    def crc8(data, polynomial=0x31):
        if isinstance(data, int):
            data = (data & 0xFFFF).to_bytes(2, "big")
        return crc8(data, polynomial)
