# device_b/main.py
# Satellite device — RFID session management with session status display.
# Responsibilities:
#   - Read RFID badge → trigger session start/end
#   - Button A → pause/resume session
#   - Display session status on screen
# MicroPython — deployed via UIFlow 1.0

import gc
import time
import network
import urequests
import ujson
from machine import I2C, Pin
from m5stack import lcd, btnA, btnB, btnC

# TODO: confirm exact UIFlow import name for RFID unit on physical device
from rfid import RFIDUnit

from config import (
    KNOWN_NETWORKS, MIDDLEWARE_URL,
    SENSOR_INTERVAL,
    I2C_PORT_A_SCL, I2C_PORT_A_SDA
)

# ============================================================
# DISPLAY CONSTANTS
# ============================================================
COLOR_BG       = 0x1a1a2e
COLOR_WHITE    = 0xFFFFFF
COLOR_GREY     = 0xAAAAAA
COLOR_DIVIDER  = 0x444444
COLOR_GOOD     = 0x00CC44
COLOR_WARN     = 0xFFAA00
COLOR_BAD      = 0xFF4444
COLOR_ACCENT   = 0x4fc3f7

# ============================================================
# HARDWARE INITIALIZATION
# ============================================================

# Port A — hardware I2C for RFID (no SoftI2C needed on device B)
i2c_a = I2C(1, scl=Pin(I2C_PORT_A_SCL), sda=Pin(I2C_PORT_A_SDA), freq=100000)
rfid  = RFIDUnit(i2c=i2c_a)

# ============================================================
# GLOBAL STATE
# ============================================================
state = {
    "session_active": False,
    "session_paused": False,
    "work_seconds":   0,
    "last_card_id":   None,
    "wifi_connected": False,
}

# ============================================================
# WIFI
# ============================================================

def connect_wifi():
    # Tries each known network in order.
    # Shows connection progress on screen.
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    for ssid, password in KNOWN_NETWORKS:
        draw_status_screen("Connecting to\n{}...".format(ssid), COLOR_WARN)
        wlan.connect(ssid, password)
        for _ in range(10):
            if wlan.isconnected():
                state["wifi_connected"] = True
                draw_status_screen("WiFi Connected!", COLOR_GOOD)
                time.sleep(1)
                return True
            time.sleep(1)

    state["wifi_connected"] = False
    draw_status_screen("No WiFi.\nOffline mode.", COLOR_BAD)
    time.sleep(2)
    return False

# ============================================================
# DISPLAY
# ============================================================

def draw_status_screen(message, color=0xFFFFFF):
    # Generic centered message screen.
    # Used during boot, WiFi connection and errors.
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(message, 10, 100, color)

def draw_session_screen():
    # Main screen showing session status.
    # Clean, minimal layout with clear visual feedback.
    lcd.clear(COLOR_BG)

    # --- Header ---
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("FOCUS TRACKER", 70, 10, COLOR_ACCENT)
    lcd.line(0, 35, 320, 35, COLOR_DIVIDER)

    # --- Session status badge ---
    if state["session_active"] and not state["session_paused"]:
        status_text  = "WORKING"
        status_color = COLOR_GOOD
        icon         = "▶"
    elif state["session_paused"]:
        status_text  = "PAUSED"
        status_color = COLOR_WARN
        icon         = "||"
    else:
        status_text  = "NO SESSION"
        status_color = COLOR_GREY
        icon         = "■"

    # Large status indicator
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{} {}".format(icon, status_text), 60, 60, status_color)

    # --- Work time ---
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Work time: {}".format(
        format_seconds(state["work_seconds"])), 10, 110, COLOR_WHITE)

    # --- Divider ---
    lcd.line(0, 140, 320, 140, COLOR_DIVIDER)

    # --- Instructions ---
    lcd.font(lcd.FONT_DejaVu18)
    if not state["session_active"]:
        lcd.print("Badge to start", 70, 155, COLOR_GREY)
    else:
        lcd.print("Badge to end", 80, 155, COLOR_GREY)
        if state["session_paused"]:
            lcd.print("BtnA to resume", 70, 180, COLOR_WARN)
        else:
            lcd.print("BtnA to pause", 75, 180, COLOR_WARN)

    # --- WiFi indicator ---
    wifi_color = COLOR_GOOD if state["wifi_connected"] else COLOR_BAD
    wifi_text  = "WiFi ✓" if state["wifi_connected"] else "WiFi ✗"
    lcd.font(lcd.FONT_DejaVu12)
    lcd.print(wifi_text, 260, 225, wifi_color)

def format_seconds(seconds):
    # Converts seconds to "Xh Ym" or "Ymin" string.
    if not seconds: return "0min"
    m = int(seconds // 60)
    h = int(m // 60)
    m = m % 60
    return "{}h {}m".format(h, m) if h > 0 else "{}min".format(m)

# ============================================================
# RFID
# ============================================================

def read_rfid():
    # Returns card ID string if a new card is detected, None otherwise.
    # Resets last_card_id when card is removed to allow re-reading.
    try:
        if rfid.isNewCardPresent() and rfid.readCardSerial():
            card_id = str(rfid.uid.uidByte)
            if card_id != state["last_card_id"]:
                state["last_card_id"] = card_id
                return card_id
    except Exception as e:
        print("[RFID] Read failed:", e)

    state["last_card_id"] = None
    return None

def handle_rfid(card_id):
    # Toggle logic: first badge starts session, second badge ends it.
    if not state["session_active"]:
        post_session_event("start", card_id)
        state["session_active"] = True
        state["session_paused"] = False
        state["work_seconds"]   = 0
        print("[RFID] Session started:", card_id)
    else:
        post_session_event("end", card_id)
        state["session_active"] = False
        state["session_paused"] = False
        state["work_seconds"]   = 0
        print("[RFID] Session ended:", card_id)

# ============================================================
# BUTTONS
# ============================================================

def handle_buttons():
    # Button A — pause/resume active session
    # Ignored if no session is active
    if btnA.wasPressed():
        if not state["session_active"]:
            print("[BTN] No active session.")
            return
        if state["session_paused"]:
            post_session_event("resume", None)
            state["session_paused"] = False
            print("[BTN] Resumed.")
        else:
            post_session_event("pause", None)
            state["session_paused"] = True
            print("[BTN] Paused.")

# ============================================================
# DATA POSTING
# ============================================================

def post_session_event(event_type, card_id):
    # Posts a session lifecycle event to middleware.
    # event_type: "start" | "pause" | "resume" | "end"
    payload = {"event": event_type, "card_id": card_id}
    try:
        r = urequests.post(
            MIDDLEWARE_URL + "/session/{}".format(event_type),
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload),
            timeout=5
        )
        r.close()
    except Exception as e:
        print("[SESSION] Post failed:", e)
    gc.collect()

def fetch_session():
    # Polls current session state from middleware.
    # Updates local state so display stays in sync.
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current", timeout=5)
        if r.status_code == 200:
            data = ujson.loads(r.text)
            state["session_active"] = data.get("active", False)
            state["session_paused"] = data.get("paused", False)
            state["work_seconds"]   = data.get("work_seconds", 0)
        r.close()
    except Exception as e:
        print("[SESSION] Fetch failed:", e)
    gc.collect()

# ============================================================
# BOOT SYNC
# ============================================================

def boot_sync():
    # Restores session state from middleware on startup.
    fetch_session()
    print("[SYNC] Session restored:", state["session_active"])

# ============================================================
# BOOT
# ============================================================

def boot():
    # Sequence: splash → WiFi → sync → draw
    draw_status_screen("Booting...", COLOR_ACCENT)
    time.sleep(1)

    connect_wifi()
    if state["wifi_connected"]:
        boot_sync()

    draw_session_screen()
    print("[BOOT] Device B ready.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    # Checks RFID and buttons every second.
    # Polls session state every 5 seconds.
    # Redraws screen every 5 seconds.
    last_session = 0
    last_draw    = 0
    DRAW_INTERVAL    = 5
    SESSION_INTERVAL = 5

    while True:
        now = time.time()

        # Check for RFID badge
        card_id = read_rfid()
        if card_id:
            handle_rfid(card_id)
            draw_session_screen()  # Immediate redraw on badge event

        # Check pause/resume button
        handle_buttons()

        # Poll session state from middleware
        if now - last_session >= SESSION_INTERVAL:
            fetch_session()
            last_session = now

        # Redraw screen on interval
        if now - last_draw >= DRAW_INTERVAL:
            draw_session_screen()
            last_draw = now

        gc.collect()
        time.sleep(1)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()