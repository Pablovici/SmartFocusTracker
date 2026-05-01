# main.py
# Entry point and main loop for the Smart Focus Tracker device.
# Boot sequence: WiFi → NTP sync → BigQuery sync → main loop.
# The main loop handles sensor reads, display updates, focus tracking,
# touch input, and data posting to the middleware.

import time
import ntptime
from m5stack import *
from m5stack_ui import *
from uiflow import *

from wifi_manager import WiFiManager
from sensor_reader import SensorReader
from display_manager import DisplayManager
from focus_tracker import FocusTracker
from sync_manager import fetch_latest
from device_a.config import (
    SENSOR_INTERVAL,
    MIDDLEWARE_URL,
    UTC_OFFSET_HOURS,
    PIR_ANNOUNCEMENT_COOLDOWN
)
import urequests
import ujson

# --- Module instantiation ---
wifi    = WiFiManager()
sensor  = SensorReader()
display = DisplayManager()
focus   = FocusTracker()

# --- Runtime state ---
current_data = {
    "temperature":  None,
    "humidity":     None,
    "co2_ppm":      None,
    "tvoc_ppb":     None,
    "motion":       False,
    "focus_status": "focus",
    "session_time": "0min",
    "pauses_count": 0,
    "time":         "--:--",
    "date":         "---",
    "weather":      {}
}

# Tracks the last time a TTS announcement was made via PIR.
# Prevents the device from announcing more than once per cooldown period.
last_announcement_time = 0


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
# HTTP HELPERS
# ----------------------------------------------------------

def post_data(payload):
    # Sends sensor readings to the middleware as a JSON POST request.
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

def post_session():
    # Sends the completed focus session record to the middleware.
    # Called when the device is about to reboot or session ends.
    try:
        payload = focus.get_session_payload()
        response = urequests.post(
            MIDDLEWARE_URL + "/session",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload),
            timeout=5
        )
        response.close()
    except Exception as e:
        print("[MAIN] Session post failed:", e)


# ----------------------------------------------------------
# TOUCH INPUT
# ----------------------------------------------------------

# Touch zones matching the buttons drawn in display_manager.py.
# Each tuple is (x1, y1, x2, y2) in screen pixels.
TOUCH_PAUSE = (10,  198, 140, 228)
TOUCH_ASK   = (170, 198, 300, 228)

def handle_touch(x, y):
    # Determines which UI element was tapped and triggers the appropriate action.
    # Navigation dots are handled by display_manager directly.
    x1, y1, x2, y2 = TOUCH_PAUSE
    if x1 <= x <= x2 and y1 <= y <= y2:
        focus.toggle_pause()
        return "pause"

    x1, y1, x2, y2 = TOUCH_ASK
    if x1 <= x <= x2 and y1 <= y <= y2:
        return "ask"

    # Pass touch to display manager for page navigation
    display.handle_touch(x, y)
    return None


# ----------------------------------------------------------
# PIR ANNOUNCEMENTS
# ----------------------------------------------------------

def maybe_announce(tts_callback):
    # Triggers a TTS announcement when the user is present,
    # but no more than once per PIR_ANNOUNCEMENT_COOLDOWN seconds.
    # tts_callback is a function that takes a text string and speaks it.
    global last_announcement_time

    if not current_data.get("motion"):
        return

    now = time.time()
    if now - last_announcement_time < PIR_ANNOUNCEMENT_COOLDOWN:
        return

    # Build a contextual announcement based on current conditions.
    messages = []

    if focus.should_alert():
        messages.append("You have been focusing for a while. Consider taking a short break.")

    humidity = current_data.get("humidity")
    if humidity is not None and humidity < 40:
        messages.append("Indoor humidity is low at {} percent. Stay hydrated.".format(int(humidity)))

    co2 = current_data.get("co2_ppm")
    if co2 is not None and co2 > 1500:
        messages.append("CO2 levels are high at {} ppm. Consider ventilating the room.".format(co2))

    if messages:
        tts_callback(" ".join(messages))
        last_announcement_time = now


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

def loop(tts_callback=None):
    # tts_callback is injected by main once the speech service is available.
    # Passing None disables TTS announcements without breaking the loop.
    global current_data

    last_post_time    = 0
    last_display_time = 0

    while True:
        now = time.time()

        # --- Clock update ---
        current_data["time"], current_data["date"] = get_time_strings()

        # --- Focus tracker update ---
        # Merge the latest focus state into current_data so the
        # display and middleware always have the current session info.
        focus.update_motion(current_data.get("motion", False))
        current_data.update(focus.get_state())

        # --- PIR announcement ---
        if tts_callback:
            maybe_announce(tts_callback)

        # --- Sensor read and data post ---
        if now - last_post_time >= SENSOR_INTERVAL:
            readings = sensor.read_all()
            current_data.update(readings)

            if wifi.wlan.isconnected():
                post_data(current_data)
            else:
                print("[MAIN] Offline — attempting reconnect.")
                display.show_offline_banner()
                wifi.connect()

            last_post_time = now

        # --- Display refresh ---
        if now - last_display_time >= 5:
            display.update(current_data)
            last_display_time = now

        # --- Touch input ---
        try:
            touched, x, y = lcd.getTouchPoint()
            if touched:
                action = handle_touch(x, y)

                if action == "ask" and tts_callback:
                    # Push-to-Talk — handled in Sprint 4
                    # Placeholder until speech_service is integrated
                    print("[MAIN] ASK button pressed — PTT not yet implemented.")

                # Force immediate display refresh on any interaction
                display.update(current_data)
                last_display_time = now
        except:
            pass

        time.sleep(1)


# --- Program entry point ---
boot()
loop()