# device_b/main.py
# Satellite device — no display interface.
# Responsibilities:
#   - Read RFID badge → trigger session start/end
#   - Button A → pause/resume session
#   - Read TVOC/eCO2 → post to middleware every SENSOR_INTERVAL seconds
# MicroPython — deployed via UIFlow 1.0

import gc
import time
import network
import urequests
import ujson
from machine import I2C, SoftI2C, Pin
from m5stack import btnA

# TODO: confirm exact UIFlow import names on physical device
from rfid import RFIDUnit
# from tvoc import TVOCUnit  # TODO: uncomment once confirmed

from config import (
    KNOWN_NETWORKS, MIDDLEWARE_URL,
    SENSOR_INTERVAL,
    I2C_PORT_A_SCL, I2C_PORT_A_SDA
)

# ============================================================
# HARDWARE INITIALIZATION
# ============================================================

# Port A — RFID reader
i2c_a = I2C(1, scl=Pin(I2C_PORT_A_SCL), sda=Pin(I2C_PORT_A_SDA), freq=100000)
rfid  = RFIDUnit(i2c=i2c_a)

# TODO: initialize TVOC once import name confirmed
# tvoc = TVOCUnit(i2c=i2c_a)

# ============================================================
# GLOBAL STATE
# ============================================================
state = {
    "session_active": False,
    "session_paused": False,
    "last_card_id":   None,  # Prevents double-reads of same badge
}

# ============================================================
# WIFI
# ============================================================

def connect_wifi():
    # Tries each known network in order.
    # No display — logs to console only.
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    for ssid, password in KNOWN_NETWORKS:
        print("[WIFI] Trying:", ssid)
        wlan.connect(ssid, password)
        for _ in range(10):
            if wlan.isconnected():
                print("[WIFI] Connected to:", ssid)
                return True
            time.sleep(1)

    print("[WIFI] All networks failed. Running offline.")
    return False

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
        print("[RFID] Session started:", card_id)
    else:
        post_session_event("end", card_id)
        state["session_active"] = False
        state["session_paused"] = False
        print("[RFID] Session ended:", card_id)

# ============================================================
# BUTTONS
# ============================================================

def handle_buttons():
    # Button A toggles pause/resume during an active session.
    # Ignored if no session is active.
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

def post_indoor_data(co2, tvoc_val, label):
    # Posts TVOC/eCO2 readings to middleware.
    payload = {
        "co2_ppm":           co2,
        "tvoc_ppb":          tvoc_val,
        "air_quality_label": label,
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
        print("[ENV] Post failed:", e)
    gc.collect()

def classify_air(co2):
    # Maps CO2 ppm to human-readable label.
    if co2 is None: return "Unknown"
    if co2 < 800:   return "Good"
    if co2 < 1000:  return "Moderate"
    return "Poor"

# ============================================================
# BOOT SYNC
# ============================================================

def boot_sync():
    # Restores session state from middleware on startup.
    # Ensures device B knows if a session was already active.
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current", timeout=5)
        if r.status_code == 200:
            data = ujson.loads(r.text)
            state["session_active"] = data.get("active", False)
            state["session_paused"] = data.get("paused", False)
            print("[SYNC] Session restored:", state["session_active"])
        r.close()
    except Exception as e:
        print("[SYNC] Failed:", e)
    gc.collect()

# ============================================================
# BOOT
# ============================================================

def boot():
    print("[BOOT] Starting device B...")
    connect_wifi()
    boot_sync()
    print("[BOOT] Ready.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    # Checks RFID and buttons every second.
    # Posts environment data every SENSOR_INTERVAL seconds.
    last_sensor = 0

    while True:
        now = time.time()

        # Check for RFID badge
        card_id = read_rfid()
        if card_id:
            handle_rfid(card_id)

        # Check pause/resume button
        handle_buttons()

        # Read and post TVOC data on interval
        if now - last_sensor >= SENSOR_INTERVAL:
            # TODO: uncomment once TVOC import confirmed on physical device
            # try:
            #     co2      = tvoc.eCO2
            #     tvoc_val = tvoc.TVOC
            #     post_indoor_data(co2, tvoc_val, classify_air(co2))
            # except Exception as e:
            #     print("[TVOC] Read failed:", e)
            last_sensor = now

        gc.collect()
        time.sleep(1)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()