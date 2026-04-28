# sensor_reader.py
# Abstraction layer for all physical sensors on the M5Stack Core2.
# Provides a single read_all() interface to main.py, isolating
# hardware-specific logic from the rest of the application.

from m5stack import *
from m5stack_ui import *
from uiflow import *
import unit
from machine import Pin
import time

# Sensors are initialized at module level since they map directly
# to physical ports and only need to be instantiated once at boot.
# Re-instantiating them on every read would be wasteful and unstable.
env_sensor  = unit.get(unit.ENV3, unit.PORTA)  # ENVIII  → Port A (SDA=32, SCL=33)
tvoc_sensor = unit.get(unit.TVOC, unit.PORTC)  # CO2/TVOC → Port C (SDA=13, SCL=14)
pir_pin     = Pin(26, Pin.IN)                   # PIR      → Port B, digital input


class SensorReader:
    """
    Handles all sensor reads. Returns a dict on success, None on failure.
    Failures are caught per sensor so one bad read never crashes the loop.
    """

    def read_enviii(self):
        # Reads temperature (°C) and humidity (%) from the ENVIII sensor.
        # Values are rounded to 1 decimal place — raw float precision
        # (e.g. 21.348291) is unnecessary for environmental monitoring
        # and would waste storage in BigQuery over thousands of rows.
        try:
            return {
                "temperature": round(env_sensor.temperature, 1),
                "humidity":    round(env_sensor.humidity, 1)
            }
        except Exception as e:
            print("[ENVIII] Read failed:", e)
            return None

    def read_air_quality(self):
        # Reads eCO2 (equivalent CO2, in ppm) and TVOC (Total Volatile
        # Organic Compounds, in ppb) from the air quality sensor.
        # Normal indoor CO2 is ~400-1000 ppm. Above 1500 ppm impacts focus.
        # Alert thresholds are evaluated downstream in focus_logic.py.
        try:
            return {
                "co2_ppm":  tvoc_sensor.eCO2,
                "tvoc_ppb": tvoc_sensor.TVOC
            }
        except Exception as e:
            print("[TVOC] Read failed:", e)
            return None

    def read_motion(self):
        # PIR outputs a binary digital signal: HIGH (1) = motion detected.
        # bool() ensures a clean True/False regardless of the raw integer
        # returned by pin.value(), which avoids type inconsistencies
        # when serializing the payload sent to the middleware.
        try:
            return bool(pir_pin.value())
        except Exception as e:
            print("[PIR] Read failed:", e)
            return False

    def read_all(self):
        # Single entry point called by main.py every 60 seconds.
        # Each sensor is read independently — if one fails and returns None,
        # the others are unaffected. The conditional "if env else None"
        # propagates the failure cleanly without raising a KeyError,
        # allowing main.py to decide how to handle missing values.
        env    = self.read_enviii()
        air    = self.read_air_quality()
        motion = self.read_motion()

        return {
            "temperature": env["temperature"] if env else None,
            "humidity":    env["humidity"]    if env else None,
            "co2_ppm":     air["co2_ppm"]     if air else None,
            "tvoc_ppb":    air["tvoc_ppb"]    if air else None,
            "motion":      motion
        }