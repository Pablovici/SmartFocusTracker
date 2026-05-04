# device_a/config.py
# Central configuration for M5Stack A (main device).
# To redeploy on a different setup, only this file needs to be modified.
# WiFi credentials are loaded from wifi_networks.json (not committed to Git).

import ujson

# ============================================================
# WIFI — Loaded from external file for security
# ============================================================

def _load_networks():
    # Reads WiFi credentials from a local JSON file excluded from Git.
    # Falls back to iot-unil if file is not found.
    try:
        with open("wifi_networks.json") as f:
            return ujson.load(f)
    except:
        return [("iot-unil", "")]  # TODO: add iot-unil password when available

KNOWN_NETWORKS = _load_networks()

# ============================================================
# MIDDLEWARE — Flask API endpoint
# ============================================================
MIDDLEWARE_URL = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"

# ============================================================
# NTP — Time synchronization
# ============================================================
NTP_UTC_OFFSET = 2  # UTC+2 Switzerland summer time — TODO: change to 1 in winter

# ============================================================
# SENSORS — Reading interval in seconds
# ============================================================
SENSOR_INTERVAL = 60  # How often sensors are read and posted to middleware

# ============================================================
# ALERT THRESHOLDS
# ============================================================
HUMIDITY_MIN = 40    # Below this % → dry air alert
CO2_HIGH     = 1000  # Above this ppm → poor air quality alert
TVOC_HIGH    = 150   # Above this ppb → poor air quality alert

# ============================================================
# ALERT TIMING — Cooldowns in seconds
# ============================================================
WEATHER_ANNOUNCE_INTERVAL = 3600  # Max once per hour for weather announcements
BREAK_REMINDER_INTERVAL   = 3600  # Remind break after 1 hour of work
BREAK_FOLLOWUP_DELAY      = 900   # Re-alert if no break taken after 15 minutes
ALERT_COOLDOWN            = 3600  # Cooldown for humidity and air quality alerts

# ============================================================
# DISPLAY — Redraw interval
# ============================================================
DRAW_INTERVAL = 5  # Redraw screen every 5 seconds to prevent flickering

# ============================================================
# I2C — Hardware pin configuration
# ============================================================
I2C_PORT_A_SCL = 22  # Port A SCL — ENVIII
I2C_PORT_A_SDA = 21  # Port A SDA — ENVIII
I2C_PORT_C_SCL = 13  # Port C SCL — TVOC (SoftI2C)
I2C_PORT_C_SDA = 14  # Port C SDA — TVOC (SoftI2C)
PIR_PIN        = 26  # Port B GPIO — PIR motion sensor