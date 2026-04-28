# main.py
# Entry point and main loop for the Smart Focus Tracker device.
# Orchestrates WiFi connection, boot-time sync, sensor reads,
# and data posting to the middleware on a fixed interval.

import time
from wifi_manager import WiFiManager
from sensor_reader import SensorReader
from sync_manager import SyncManager
from config import SENSOR_INTERVAL, MIDDLEWARE_URL
import urequests
import ujson

# --- Module instantiation ---
wifi   = WiFiManager()
sensor = SensorReader()
sync   = SyncManager()

def post_data(payload):
    # Sends sensor readings to the middleware as a JSON POST request.
    # Returns True on success, False if the middleware is unreachable.
    try:
        response = urequests.post(
            MIDDLEWARE_URL + "/data",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload),
            timeout=5
        )
        success = response.status_code == 200
        response.close()
        return success
    except Exception as e:
        print("[MAIN] Failed to post data:", e)
        return False

def boot():
    # Runs once at startup. Establishes WiFi and fetches the latest
    # values from BigQuery so the display is never empty on boot.
    print("[MAIN] Booting...")

    connected = wifi.ensure_connected()

    if connected:
        latest = sync.sync()
        if latest:
            print("[MAIN] Boot sync successful.")
        else:
            print("[MAIN] Boot sync failed — continuing with no cached data.")
    else:
        print("[MAIN] No WiFi — running offline.")

def loop():
    # Main application loop. Reads all sensors every SENSOR_INTERVAL
    # seconds and posts the result to the middleware.
    # If posting fails (e.g. WiFi dropped), the read is logged locally
    # and the loop continues — the device never crashes on network loss.
    while True:
        data = sensor.read_all()
        print("[MAIN] Sensor read:", data)

        if wifi.wlan.isconnected():
            success = post_data(data)
            if not success:
                print("[MAIN] Post failed — data not sent this cycle.")
        else:
            print("[MAIN] Offline — skipping post.")
            # Attempt silent reconnection before next cycle.
            wifi.connect()

        time.sleep(SENSOR_INTERVAL)

# --- Program entry point ---
boot()
loop()