# main.py
# Entry point and main loop for the Smart Focus Tracker device.
# Boot sequence: WiFi → NTP sync → BigQuery sync → main loop.
# The display refreshes every 5 seconds to avoid flickering,
# while the clock updates every second and sensors post every 60s.

import time
import ntptime
from m5stack import *
from m5stack_ui import *
from uiflow import *

from wifi_manager import WiFiManager
from sensor_reader import SensorReader
from display_manager import DisplayManager
from sync_manager import fetch_latest
from config import SENSOR_INTERVAL, MIDDLEWARE_URL, UTC_OFFSET_HOURS
import urequests
import ujson

# --- Module instantiation ---
wifi    = WiFiManager()
sensor  = SensorReader()
display = DisplayManager()

# --- Runtime state ---
# Single source of truth for all data displayed on screen.
# Initialized with safe defaults so the UI never crashes on missing values.
current_data = {
    "temperature":  None,
    "humidity":     None,
    "co2_ppm":      None,
    "tvoc_ppb":     None,
    "motion":       False,
    "focus_status": "focus",
    "session_time": "0min",
    "time":         "--:--",
    "date":         "---",
    "weather":      {}
}


# ----------------------------------------------------------
# NTP TIME SYNC
# ----------------------------------------------------------

def sync_time():
    # Synchronizes the device clock with an NTP server.
    # Without this, the M5Stack clock resets to epoch on every boot.
    try:
        ntptime.settime()
        print("[NTP] Time synchronized.")
    except Exception as e:
        print("[NTP] Sync failed:", e)

def get_time_strings():
    # Returns formatted time and date strings for the status bar.
    # UTC offset is added manually since MicroPython has no timezone support.
    t = time.localtime(time.time() + UTC_OFFSET_HOURS * 3600)
    time_str = "{:02d}:{:02d}".format(t[3], t[4])
    days   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    date_str = "{} {} {}".format(days[t[6]], t[2], months[t[1] - 1])
    return time_str, date_str


# ----------------------------------------------------------
# DATA POSTING
# ----------------------------------------------------------

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
        print("[MAIN] Post failed:", e)
        return False


# ----------------------------------------------------------
# BOOT SEQUENCE
# ----------------------------------------------------------

def boot():
    global current_data
    display.show_boot_screen()

    connected = wifi.ensure_connected()

    if connected:
        sync_time()
        latest = fetch_latest()
        if latest:
            # Populate current_data with BigQuery values immediately
            # so the display is never empty on first render.
            current_data.update(latest)
            print("[MAIN] Boot sync successful.")
        else:
            print("[MAIN] Boot sync failed — displaying defaults.")
    else:
        print("[MAIN] No WiFi — running offline.")
        display.show_offline_banner()


# ----------------------------------------------------------
# MAIN LOOP
# ----------------------------------------------------------

def loop():
    global current_data

    last_post_time    = 0
    last_display_time = 0

    while True:
        now = time.time()

        # Update clock strings on every iteration for a live clock display.
        current_data["time"], current_data["date"] = get_time_strings()

        # --- Sensor read and data post (every SENSOR_INTERVAL seconds) ---
        if now - last_post_time >= SENSOR_INTERVAL:
            readings = sensor.read_all()
            current_data.update(readings)

            if wifi.wlan.isconnected():
                success = post_data(current_data)
                if not success:
                    print("[MAIN] Post failed this cycle.")
            else:
                print("[MAIN] Offline — attempting reconnect.")
                display.show_offline_banner()
                wifi.connect()

            last_post_time = now

        # --- Display refresh (every 5 seconds to avoid flickering) ---
        if now - last_display_time >= 5:
            display.update(current_data)
            last_display_time = now

        # --- Touch input for page navigation ---
        # lcd.getTouchPoint() is the UIFlow 1 touch API.
        # If the API differs on the physical device, only this block needs updating.
        try:
            touched, x, y = lcd.getTouchPoint()
            if touched:
                changed = display.handle_touch(x, y)
                if changed:
                    # Force immediate redraw when the user switches page.
                    display.update(current_data)
                    last_display_time = now
        except:
            pass

        time.sleep(1)


# --- Program entry point ---
boot()
loop()