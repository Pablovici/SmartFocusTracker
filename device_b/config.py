# device_b/config.py
# Central configuration for M5Stack B (satellite device).
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
MIDDLEWARE_URL = "http://localhost:8080"  # TODO: replace with Cloud Run URL after deployment

# ============================================================
# SENSORS — Reading interval in seconds
# ============================================================
SENSOR_INTERVAL = 60  # How often TVOC is read and posted to middleware

# ============================================================
# I2C — Hardware pin configuration
# ============================================================
I2C_PORT_A_SCL = 22  # Port A SCL — RFID reader
I2C_PORT_A_SDA = 21  # Port A SDA — RFID reader