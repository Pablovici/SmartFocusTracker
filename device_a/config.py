# config.py
# Central configuration file for the M5Stack device.
# All environment-specific values are defined here so that
# redeploying the app on a different network or against a
# different backend only requires changes in this single file.

# --- Middleware ---
# Base URL of the Flask API running on Cloud Run.
# All device HTTP calls are routed through this endpoint.
MIDDLEWARE_URL = "https://your-cloud-run-url"

# --- WiFi ---
# Default credentials loaded at boot. The user can override
# these at runtime via the WiFi settings screen in the UI.
WIFI_SSID     = "your_wifi_name"
WIFI_PASSWORD = "your_wifi_password"

# --- Sensor read interval ---
# How often (in seconds) the device reads sensors and posts
# data to the middleware. 60s is a reasonable balance between
# data granularity and battery/bandwidth usage.
SENSOR_INTERVAL = 60

# --- Weather fetch interval ---
# OpenWeatherMap free tier allows 60 calls/minute.
# Fetching every 10 minutes is well within the limit.
WEATHER_INTERVAL = 600  # 10 minutes in seconds

# --- Focus logic ---
# Time without a break (in minutes) before the device
# triggers a vocal alert recommending a pause.
FOCUS_ALERT_THRESHOLD_MIN = 45

# Minimum time (in seconds) between two PIR-triggered
# announcements. Prevents the device from being annoying.
PIR_ANNOUNCEMENT_COOLDOWN = 3600  # 1 hour in seconds

# --- Alert thresholds ---
# Values beyond these limits trigger local UI alerts
# and vocal warnings via TTS, as required by the project spec.
HUMIDITY_ALERT_MIN =  40    # % — below this, air is too dry
CO2_ALERT_MAX      = 1500   # ppm — above this, air quality is poor
TVOC_ALERT_MAX     = 500    # ppb — above this, VOC level is concerning

# --- Display ---
# Target timezone offset from UTC, used to display local time
# after NTP sync. UTC+2 corresponds to Swiss summer time (CEST).
UTC_OFFSET_HOURS = 2