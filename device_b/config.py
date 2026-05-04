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
        return [("iot-unil", "4u6uch4hpY9pJ2f9")]

KNOWN_NETWORKS = _load_networks()

# ============================================================
# MIDDLEWARE — Flask API endpoint
# ============================================================
MIDDLEWARE_URL = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"

# ============================================================
# SENSORS — Reading interval in seconds
# ============================================================
SENSOR_INTERVAL = 30  # How often data is read and posted to middleware