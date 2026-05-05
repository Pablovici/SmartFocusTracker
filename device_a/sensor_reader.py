# device_a/sensor_reader.py — M5Stack Core2
# Direct I2C drivers for SHT30 (ENV3) and SGP30 (TVOC).
# No UIFlow libraries needed.

from machine import I2C, Pin
import time
from config import (
    I2C_PORT_A_SCL, I2C_PORT_A_SDA,
    I2C_PORT_C_SCL, I2C_PORT_C_SDA,
    PIR_PIN
)

# ============================================================
# SHT30 — Temperature & Humidity (ENV3, Port A)
# ============================================================
class SHT30:
    def __init__(self, i2c, addr=0x44):
        self.i2c  = i2c
        self.addr = addr

    @property
    def temperature(self):
        self.i2c.writeto(self.addr, bytes([0x2C, 0x06]))
        time.sleep_ms(50)
        data = self.i2c.readfrom(self.addr, 6)
        return -45 + (175 * ((data[0] << 8) | data[1]) / 65535.0)

    @property
    def humidity(self):
        self.i2c.writeto(self.addr, bytes([0x2C, 0x06]))
        time.sleep_ms(50)
        data = self.i2c.readfrom(self.addr, 6)
        return 100 * ((data[3] << 8) | data[4]) / 65535.0

# ============================================================
# SGP30 — CO2 & TVOC (Port C)
# ============================================================
class SGP30:
    def __init__(self, i2c, addr=0x58):
        self.i2c  = i2c
        self.addr = addr
        self.i2c.writeto(self.addr, bytes([0x20, 0x03]))
        time.sleep_ms(10)

    @property
    def eCO2(self):
        self.i2c.writeto(self.addr, bytes([0x20, 0x08]))
        time.sleep_ms(12)
        data = self.i2c.readfrom(self.addr, 6)
        return (data[0] << 8) | data[1]

    @property
    def TVOC(self):
        self.i2c.writeto(self.addr, bytes([0x20, 0x08]))
        time.sleep_ms(12)
        data = self.i2c.readfrom(self.addr, 6)
        return (data[3] << 8) | data[4]

# ============================================================
# SensorReader — interface principale pour main.py
# ============================================================
class SensorReader:
    def __init__(self):
        i2c_a = I2C(1, scl=Pin(I2C_PORT_A_SCL), sda=Pin(I2C_PORT_A_SDA), freq=100000)
        i2c_c = I2C(scl=Pin(I2C_PORT_C_SCL), sda=Pin(I2C_PORT_C_SDA), freq=100000)
        self.env = SHT30(i2c_a)
        self.tvoc = SGP30(i2c_c)
        self.pir = Pin(PIR_PIN, Pin.IN)

    def read_all(self):
        result = {
            "temperature": None,
            "humidity":    None,
            "co2_ppm":     None,
            "tvoc_ppb":    None,
            "motion":      False
        }
        try:
            result["temperature"] = round(self.env.temperature, 1)
            result["humidity"]    = round(self.env.humidity, 1)
        except Exception as e:
            print("[SENSOR] ENV:", e)
        try:
            result["co2_ppm"]  = self.tvoc.eCO2
            result["tvoc_ppb"] = self.tvoc.TVOC
        except Exception as e:
            print("[SENSOR] TVOC:", e)
        try:
            result["motion"] = bool(self.pir.value())
        except Exception as e:
            print("[SENSOR] PIR:", e)
        return result
