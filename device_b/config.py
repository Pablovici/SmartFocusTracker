# device_b/config.py
# Configuration for M5Stack B (satellite device).
# Handles RFID badge reading and posts session events to middleware.

# ============================================================
# WIFI — Same logic as device_a, tried in order on boot
# ============================================================
KNOWN_NETWORKS = [
    ("iPhone de Amir", "toad1234"),  # Home network
    ("iot-unil", ""),                 # TODO: add iot-unil password when available
]

# ============================================================
# MIDDLEWARE — Flask API endpoint
# ============================================================
MIDDLEWARE_URL = "http://localhost:8080"  # TODO: replace with Cloud Run URL after deployment

# ============================================================
# SENSORS — Reading interval in seconds
# ============================================================
SENSOR_INTERVAL = 60  # How often TVOC is read and posted

# ============================================================
# I2C — Hardware pin configuration
# ============================================================
# Port A (hardware I2C) — RFID reader
I2C_PORT_A_SCL = 22
I2C_PORT_A_SDA = 21