# device_a/config.py — M5Stack Core2
# Central configuration. Only this file needs to change per deployment.

# ============================================================
# WIFI
# ============================================================
KNOWN_NETWORKS = [
    ("iPhone de Amir", "toad1234"),
    ("iot-unil",       "4u6uch4hpY9pJ2f9"),
]

# ============================================================
# MIDDLEWARE
# ============================================================
MIDDLEWARE_URL = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"

# ============================================================
# NTP
# ============================================================
NTP_UTC_OFFSET = 2  # UTC+2 Switzerland summer time

# ============================================================
# SENSORS
# ============================================================
SENSOR_INTERVAL = 10  # seconds between reads (use 60 in production)

# ============================================================
# ALERT THRESHOLDS
# ============================================================
HUMIDITY_MIN = 40    # % — below this → dry air alert
CO2_HIGH     = 1000  # ppm — above this → poor air quality

# ============================================================
# ALERT TIMING
# ============================================================
WEATHER_ANNOUNCE_INTERVAL = 3600
BREAK_REMINDER_INTERVAL   = 3600
BREAK_FOLLOWUP_DELAY      = 900
ALERT_COOLDOWN            = 3600

# ============================================================
# DISPLAY
# ============================================================
DRAW_INTERVAL = 5

# ============================================================
# I2C PINS — M5Stack Core2
# ============================================================
I2C_PORT_A_SCL = 33  # Port A SCL — ENV3 (SHT30)
I2C_PORT_A_SDA = 32  # Port A SDA — ENV3 (SHT30)
I2C_PORT_C_SCL = 13  # Port C SCL — TVOC (SGP30)
I2C_PORT_C_SDA = 14  # Port C SDA — TVOC (SGP30)
PIR_PIN        = 26  # Port B GPIO — PIR
