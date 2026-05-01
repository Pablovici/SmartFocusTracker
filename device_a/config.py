# device_a/config.py
# Central configuration file for M5Stack A (main device).
# All environment-specific values are defined here.
# To redeploy on a different network or backend,
# only this file needs to be modified.

# ============================================================
# WIFI — Known networks, tried in order on boot
# ============================================================
KNOWN_NETWORKS = [
    ("iPhone de Amir", "toad1234"),   # Home network
    ("iot-unil", ""),                  # TODO: add iot-unil password when available
]

# ============================================================
# MIDDLEWARE — Flask API endpoint
# ============================================================
MIDDLEWARE_URL = "http://localhost:8080"  # TODO: replace with Cloud Run URL after deployment

# ============================================================
# NTP — Time synchronization
# ============================================================
NTP_UTC_OFFSET = 2      # UTC+2 for Switzerland (summer time)
                         # TODO: change to 1 in winter (UTC+1)

# ============================================================
# SENSORS — Reading intervals in seconds
# ============================================================
SENSOR_INTERVAL = 60    # How often sensors are read and posted to middleware

# ============================================================
# ALERT THRESHOLDS — Values that trigger TTS announcements
# ============================================================
HUMIDITY_MIN     = 40   # Below this % → dry air alert
CO2_HIGH         = 1000 # Above this ppm → poor air quality alert
TVOC_HIGH        = 150  # Above this ppb → poor air quality alert

# ============================================================
# ALERT TIMING — Cooldowns to avoid spamming announcements
# ============================================================
WEATHER_ANNOUNCE_INTERVAL = 3600  # Minimum seconds between weather announcements (1 hour)
BREAK_REMINDER_INTERVAL   = 3600  # Remind break after 1 hour of continuous work
BREAK_FOLLOWUP_DELAY      = 900   # Re-alert if no break taken after 15 minutes
ALERT_COOLDOWN            = 3600  # Cooldown for humidity and air quality alerts (1 hour)

# ============================================================
# I2C — Hardware pin configuration
# ============================================================
# Port A (hardware I2C) — ENVIII sensor
I2C_PORT_A_SCL = 22
I2C_PORT_A_SDA = 21

# Port C (software I2C) — TVOC/eCO2 sensor
I2C_PORT_C_SCL = 13
I2C_PORT_C_SDA = 14

# Port B (GPIO) — PIR motion sensor
PIR_PIN = 26