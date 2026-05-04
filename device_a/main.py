# device_a/main.py
# Main entry point for M5Stack A (primary device).
# Sections: Hardware → State → WiFi → NTP → Sync → Sensors
#           → Display → Alerts → TTS/STT → Buttons → Boot → Loop
# MicroPython — deployed via UIFlow 1.0

import gc
import time
import network
import ntptime
import urequests
import ujson
from machine import I2C, SoftI2C, Pin
from m5stack import lcd, btnA, btnB, btnC

# TODO: confirm exact UIFlow import names on physical device
from env3 import ENVUnit
from tvoc import TVOCUnit

from config import (
    KNOWN_NETWORKS, MIDDLEWARE_URL,
    NTP_UTC_OFFSET, SENSOR_INTERVAL,
    HUMIDITY_MIN, CO2_HIGH,
    WEATHER_ANNOUNCE_INTERVAL, ALERT_COOLDOWN,
    BREAK_REMINDER_INTERVAL, BREAK_FOLLOWUP_DELAY,
    DRAW_INTERVAL,
    I2C_PORT_A_SCL, I2C_PORT_A_SDA,
    I2C_PORT_C_SCL, I2C_PORT_C_SDA,
    PIR_PIN
)

# ============================================================
# DISPLAY CONSTANTS
# ============================================================
COLOR_BG      = 0x1a1a2e
COLOR_WHITE   = 0xFFFFFF
COLOR_GREY    = 0xAAAAAA
COLOR_DIVIDER = 0x444444
COLOR_GOOD    = 0x00FF00
COLOR_WARN    = 0xFFAA00
COLOR_BAD     = 0xFF0000

# ============================================================
# HARDWARE INITIALIZATION
# ============================================================

# Port A — hardware I2C for ENVIII
i2c_a = I2C(1, scl=Pin(I2C_PORT_A_SCL), sda=Pin(I2C_PORT_A_SDA), freq=100000)
env   = ENVUnit(i2c=i2c_a)

# Port C — software I2C for TVOC
i2c_c = SoftI2C(scl=Pin(I2C_PORT_C_SCL), sda=Pin(I2C_PORT_C_SDA), freq=100000)
tvoc  = TVOCUnit(i2c=i2c_c)

# Port B — GPIO for PIR
pir = Pin(PIR_PIN, Pin.IN)

# ============================================================
# GLOBAL STATE
# Single source of truth for all displayed and posted data.
# Safe defaults ensure the UI never crashes on missing values.
# ============================================================
state = {
    "temperature":       None,
    "humidity":          None,
    "co2_ppm":           None,
    "tvoc_ppb":          None,
    "air_quality_label": "Unknown",
    "motion":            False,
    "weather": {
        "temp":      None,
        "condition": "N/A",
        "icon":      "01d",
        "forecast":  []
    },
    "session_active":   False,
    "session_paused":   False,
    "session_work_sec": 0,
    "time_str":         "--:--",
    "date_str":         "---",
}

# Tracks last announcement time per alert type
alert_times = {
    "weather":     0,
    "humidity":    0,
    "air_quality": 0,
    "break":       0,
}

# 0: main screen  1: session screen  2: wifi screen
current_screen = 0

# ============================================================
# WIFI
# ============================================================

def connect_wifi():
    # Tries each known network in order until one connects.
    # Falls back to manual WiFi screen if all networks fail.
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    for ssid, password in KNOWN_NETWORKS:
        display_message("Connecting to\n{}".format(ssid))
        wlan.connect(ssid, password)
        for _ in range(10):
            if wlan.isconnected():
                display_message("Connected!")
                return True
            time.sleep(1)

    display_message("No WiFi found.\nCheck credentials.")
    show_wifi_screen()
    return wlan.isconnected()

def show_wifi_screen():
    # Displays available network options via physical buttons.
    # TODO: add on-screen keyboard for custom credential entry
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("WiFi Setup",          90,  10, COLOR_WHITE)
    lcd.line(0, 35, 320, 35, COLOR_DIVIDER)
    lcd.print("BtnA: home wifi",     10,  60, COLOR_GREY)
    lcd.print("BtnB: iot-unil",      10,  90, COLOR_GREY)
    lcd.print("BtnC: skip offline",  10, 120, COLOR_GREY)

# ============================================================
# NTP
# ============================================================

def sync_ntp():
    # Syncs device clock with NTP server.
    # UTC offset applied manually — MicroPython has no timezone support.
    try:
        ntptime.settime()
        print("[NTP] Synced.")
    except Exception as e:
        print("[NTP] Failed:", e)

def get_time_strings():
    # Returns (time_str, date_str) adjusted for local timezone.
    t      = time.localtime(time.time() + NTP_UTC_OFFSET * 3600)
    days   = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    months = ["Jan","Feb","Mar","Apr","May","Jun",
              "Jul","Aug","Sep","Oct","Nov","Dec"]
    return (
        "{:02d}:{:02d}".format(t[3], t[4]),
        "{} {} {}".format(days[t[6]], t[2], months[t[1]-1])
    )

# ============================================================
# BOOT SYNC
# ============================================================

def boot_sync():
    # Fetches last known values from BigQuery via middleware.
    # Ensures display is never empty after reboot.
    try:
        r = urequests.get(MIDDLEWARE_URL + "/latest", timeout=5)
        if r.status_code == 200:
            state.update(ujson.loads(r.text))
            print("[SYNC] Boot sync OK.")
        r.close()
    except Exception as e:
        print("[SYNC] Failed:", e)
    gc.collect()

# ============================================================
# SENSORS
# ============================================================

def read_sensors():
    # Each sensor is wrapped independently.
    # One failure does not prevent the others from being read.
    try:
        state["temperature"] = env.temperature
        state["humidity"]    = env.humidity
    except Exception as e:
        print("[SENSOR] ENVIII:", e)

    try:
        state["co2_ppm"]           = tvoc.eCO2
        state["tvoc_ppb"]          = tvoc.TVOC
        state["air_quality_label"] = classify_air(state["co2_ppm"])
    except Exception as e:
        print("[SENSOR] TVOC:", e)

    try:
        state["motion"] = bool(pir.value())
    except Exception as e:
        print("[SENSOR] PIR:", e)

def classify_air(co2):
    # Maps CO2 ppm to a human-readable label.
    if co2 is None: return "Unknown"
    if co2 < 800:   return "Good"
    if co2 < 1000:  return "Moderate"
    return "Poor"

def post_indoor_data():
    # POSTs current sensor readings to Flask middleware.
    # Fails silently — device continues running if middleware unreachable.
    payload = {
        "temperature":       state["temperature"],
        "humidity":          state["humidity"],
        "co2_ppm":           state["co2_ppm"],
        "tvoc_ppb":          state["tvoc_ppb"],
        "air_quality_label": state["air_quality_label"],
        "motion_detected":   state["motion"],
    }
    try:
        r = urequests.post(
            MIDDLEWARE_URL + "/data/indoor",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload),
            timeout=5
        )
        r.close()
    except Exception as e:
        print("[POST] Failed:", e)
    gc.collect()

# ============================================================
# WEATHER
# ============================================================

def fetch_weather():
    # Fetches current weather and forecast from middleware.
    # Forecast is displayed only — not stored in BigQuery.
    try:
        r = urequests.get(MIDDLEWARE_URL + "/weather", timeout=5)
        if r.status_code == 200:
            state["weather"] = ujson.loads(r.text)
        r.close()
    except Exception as e:
        print("[WEATHER] Failed:", e)
    gc.collect()

# ============================================================
# DISPLAY HELPERS
# ============================================================

def display_message(msg):
    # Generic message screen — used during boot and errors.
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(msg, 10, 100, COLOR_WHITE)

def air_color(label):
    # Returns color matching air quality label.
    if label == "Good":     return COLOR_GOOD
    if label == "Moderate": return COLOR_WARN
    return COLOR_BAD

def format_seconds(seconds):
    # Converts seconds to "Xh Ym" or "Ymin" string.
    if not seconds: return "0min"
    m = int(seconds // 60)
    h = int(m // 60)
    m = m % 60
    return "{}h {}m".format(h, m) if h > 0 else "{}min".format(m)

def draw_main_screen():
    # Layout: top bar (time) | weather | divider | indoor | session status | nav
    lcd.clear(COLOR_BG)

    # Top bar
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(state["time_str"], 10,  8, COLOR_WHITE)
    lcd.print(state["date_str"], 180, 8, COLOR_GREY)

    # Outdoor weather
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{}°C".format(
        state["weather"].get("temp", "--")), 10, 40, COLOR_WHITE)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(state["weather"].get("condition", "N/A"), 10, 72, COLOR_GREY)

    # Divider
    lcd.line(0, 100, 320, 100, COLOR_DIVIDER)

    # Indoor data
    t = state["temperature"]
    h = state["humidity"]
    lcd.print("In: {}°C  {}%".format(
        "--" if t is None else round(t, 1),
        "--" if h is None else round(h, 1)
    ), 10, 110, COLOR_WHITE)

    aq = state["air_quality_label"]
    lcd.print("Air: {}".format(aq), 10, 140, air_color(aq))

    # Session status
    if state["session_active"]:
        label = "Paused" if state["session_paused"] \
            else format_seconds(state["session_work_sec"])
        color = COLOR_WARN if state["session_paused"] else COLOR_GOOD
    else:
        label = "No session"
        color = COLOR_GREY
    lcd.print("Session: {}".format(label), 10, 170, color)

    # Button hints
    lcd.font(lcd.FONT_DejaVu12)
    lcd.print("[Session]", 10,  220, COLOR_GREY)
    lcd.print("[Ask]",     130, 220, COLOR_GREY)
    lcd.print("[WiFi]",    240, 220, COLOR_GREY)

def draw_session_screen():
    # Shows session status and elapsed work time.
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Work Session", 80, 10, COLOR_WHITE)
    lcd.line(0, 35, 320, 35, COLOR_DIVIDER)

    if state["session_active"]:
        status = "PAUSED" if state["session_paused"] else "ACTIVE"
        color  = COLOR_WARN if state["session_paused"] else COLOR_GOOD
        lcd.print("Status: {}".format(status), 10, 60, color)
        lcd.print("Work: {}".format(
            format_seconds(state["session_work_sec"])), 10, 95, COLOR_WHITE)
        lcd.print("Badge to end", 10, 130, COLOR_GREY)
    else:
        lcd.print("No active session", 10, 80,  COLOR_GREY)
        lcd.print("Badge to start",    10, 110, COLOR_GREY)

    lcd.font(lcd.FONT_DejaVu12)
    lcd.print("[Back]", 10, 220, COLOR_GREY)

# ============================================================
# ALERTS
# ============================================================

def check_alerts():
    # PIR presence required for all alerts.
    # Each alert type has its own cooldown in alert_times.
    if not state["motion"]:
        return

    now = time.time()

    # Weather — once per hour maximum
    if now - alert_times["weather"] > WEATHER_ANNOUNCE_INTERVAL:
        cond = state["weather"].get("condition", "unknown")
        temp = state["weather"].get("temp", "--")
        speak("Current weather: {}, {} degrees.".format(cond, temp))
        alert_times["weather"] = now

    # Humidity alert
    h = state["humidity"]
    if h is not None and h < HUMIDITY_MIN:
        if now - alert_times["humidity"] > ALERT_COOLDOWN:
            speak("Humidity is low at {}%. Consider using a humidifier.".format(
                round(h, 1)))
            alert_times["humidity"] = now

    # Air quality — initial + followup after 15min if still poor
    if state["air_quality_label"] == "Poor":
        time_since = now - alert_times["air_quality"]
        if time_since > ALERT_COOLDOWN:
            speak("Air quality is poor. Please open a window.")
            alert_times["air_quality"] = now
        elif time_since > BREAK_FOLLOWUP_DELAY:
            speak("Air quality is still poor. Please ventilate now.")
            # Reset so next full cooldown applies
            alert_times["air_quality"] = now - ALERT_COOLDOWN + BREAK_FOLLOWUP_DELAY

    # Break reminder — uses server-tracked work time, correctly excludes pauses
    if state["session_active"] and not state["session_paused"]:
        if state["session_work_sec"] > BREAK_REMINDER_INTERVAL:
            time_since = now - alert_times["break"]
            if time_since > ALERT_COOLDOWN:
                speak("You have been working for over an hour. Time for a break!")
                alert_times["break"] = now
            elif time_since > BREAK_FOLLOWUP_DELAY:
                speak("Please take a break. Your focus will improve.")
                alert_times["break"] = now - ALERT_COOLDOWN + BREAK_FOLLOWUP_DELAY

# ============================================================
# TTS / STT
# ============================================================

def speak(text):
    # Sends text to middleware TTS endpoint.
    # TODO: implement audio playback on M5Stack speaker once Pablo's endpoint is ready
    print("[TTS] {}".format(text))
    try:
        r = urequests.post(
            MIDDLEWARE_URL + "/speak",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"text": text}),
            timeout=10
        )
        r.close()
    except Exception as e:
        print("[TTS] Failed:", e)
    gc.collect()

def ask_question():
    # Records audio from mic, sends to /ask endpoint.
    # Middleware runs STT → LLM → TTS, returns audio response.
    # TODO: implement M5Stack Core2 microphone recording
    display_message("Listening...")
    gc.collect()

# ============================================================
# SESSION SYNC
# ============================================================

def fetch_session():
    # Polls current session state from middleware.
    # M5Stack B posts session events — M5Stack A reads the result.
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current", timeout=5)
        if r.status_code == 200:
            data = ujson.loads(r.text)
            state["session_active"]   = data.get("active", False)
            state["session_paused"]   = data.get("paused", False)
            state["session_work_sec"] = data.get("work_seconds", 0)
        r.close()
    except Exception as e:
        print("[SESSION] Failed:", e)
    gc.collect()

# ============================================================
# BUTTONS
# ============================================================

def handle_buttons():
    # BtnA: toggle session screen
    # BtnB: trigger STT question
    # BtnC: toggle WiFi screen
    global current_screen

    if btnA.wasPressed():
        current_screen = 1 if current_screen != 1 else 0

    if btnB.wasPressed():
        ask_question()

    if btnC.wasPressed():
        if current_screen != 2:
            current_screen = 2
            show_wifi_screen()
        else:
            current_screen = 0

# ============================================================
# BOOT
# ============================================================

def boot():
    # Sequence: splash → WiFi → NTP → sync → first draw
    display_message("Booting...")
    time.sleep(1)

    if connect_wifi():
        sync_ntp()
        boot_sync()
        fetch_weather()
        fetch_session()

    state["time_str"], state["date_str"] = get_time_strings()
    draw_main_screen()
    print("[BOOT] Complete.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    # Timer-based loop — no threads needed.
    # Each action fires independently on its own interval.
    last_sensor  = 0
    last_weather = 0
    last_session = 0
    last_clock   = 0
    last_draw    = 0

    while True:
        now = time.time()

        # Update clock every second
        if now - last_clock >= 1:
            state["time_str"], state["date_str"] = get_time_strings()
            last_clock = now

        # Read and post sensor data every SENSOR_INTERVAL seconds
        if now - last_sensor >= SENSOR_INTERVAL:
            read_sensors()
            post_indoor_data()
            last_sensor = now

        # Fetch weather every 10 minutes
        if now - last_weather >= 600:
            fetch_weather()
            last_weather = now

        # Poll session state every 5 seconds
        if now - last_session >= 5:
            fetch_session()
            last_session = now

        # Check PIR-triggered alerts every loop
        check_alerts()

        # Handle physical button presses
        handle_buttons()

        # Redraw screen every DRAW_INTERVAL seconds to prevent flickering
        if now - last_draw >= DRAW_INTERVAL:
            if current_screen == 0:
                draw_main_screen()
            elif current_screen == 1:
                draw_session_screen()
            last_draw = now

        gc.collect()
        time.sleep(1)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()