# device_b/main.py
# Satellite device — RFID session management with session status display.
# Responsibilities:
#   - Read RFID badge → trigger session start/end via middleware
#   - Button A → pause/resume session
#   - Display session status on screen
# MicroPython — deployed via UIFlow 1.0
# Assigned to: Amir

import gc
import sys
import time
import network
import urequests
import ujson
import unit
from m5stack import lcd, btnA, btnB, btnC

sys.path.append('/flash')
from device_config import KNOWN_NETWORKS, MIDDLEWARE_URL, SENSOR_INTERVAL

# ============================================================
# DISPLAY CONSTANTS
# ============================================================
COLOR_BG        = 0x1a1a2e
COLOR_WHITE     = 0xFFFFFF
COLOR_GREY_SOFT = 0x999999
COLOR_GREY_DIM  = 0x666666
COLOR_DIVIDER   = 0x3a3a5e
COLOR_GOOD      = 0x00CC44
COLOR_WARN      = 0xFFAA00
COLOR_BAD       = 0xFF4444
COLOR_ACCENT    = 0x4fc3f7
COLOR_WIFI      = 0x334455

SCREEN_W = 320
SCREEN_H = 240

# ============================================================
# HARDWARE INITIALIZATION
# ============================================================

# Port A — RFID RC522 via UIFlow unit system.
# Device B serves no purpose without RFID — halt with clear error if not detected.
try:
    rfid = unit.get(unit.RFID, (21, 22))
    print("[RFID] Init OK")
except Exception as e:
    lcd.clear(0x1a1a2e)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("RFID NOT FOUND", 40, 90, 0xFF4444)
    lcd.print("Check Port A cable", 20, 120, 0x999999)
    lcd.print(str(e), 10, 150, 0x666666)
    print("[RFID] Fatal:", e)
    raise SystemExit("RFID required — check Grove cable on Port A")

# ============================================================
# GLOBAL STATE
# ============================================================
state = {
    "session_active": False,
    "session_paused": False,
    "work_seconds":   0,
    "last_card_id":   None,  # Prevents double-reads of same badge
    "wifi_connected": False,
}

_last_drawn = {
    "session_active": None,
    "session_paused": None,
    "work_seconds":   -1,
    "wifi_connected": None,
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
        _draw_boot_msg("Connecting...\n{}".format(ssid))
        wlan.connect(ssid, password)
        for _ in range(10):
            if wlan.isconnected():
                state["wifi_connected"] = True
                _draw_boot_msg("Connected!")
                time.sleep(1)
                return True
            time.sleep(1)

    state["wifi_connected"] = False
    _draw_boot_msg("No WiFi - offline")
    time.sleep(2)
    return False

# ============================================================
# DISPLAY HELPERS
# ============================================================

def _draw_boot_msg(msg):
    # Minimal boot screen.
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(msg, 10, 100, COLOR_ACCENT)

def _cx(text, char_w, offset=0):
    # Centers text horizontally with optional drift correction offset.
    return max(0, (SCREEN_W - len(text) * char_w) // 2 + offset)

def _draw_header():
    # Shared header bar — same on both screens.
    lcd.font(lcd.FONT_DejaVu18)
    header = "- FOCUS TRACKER -"
    lcd.print(header, _cx(header, 11, -4), 10, COLOR_ACCENT)
    lcd.line(0, 32, SCREEN_W, 32, COLOR_DIVIDER)

def _draw_wifi_indicator():
    # Subtle WiFi status — only draws attention when disconnected.
    lcd.font(lcd.FONT_DejaVu18)
    if state["wifi_connected"]:
        lcd.print("WiFi OK", _cx("WiFi OK", 11, -4), 220, COLOR_WIFI)
    else:
        lcd.print("No WiFi", _cx("No WiFi", 11, -4), 220, COLOR_BAD)

def _draw_bottom_bar(left_text, right_text, left_color, right_color):
    # Compact bottom action bar — same visual weight as header.
    lcd.line(0, 196, SCREEN_W, 196, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(left_text,  12,  202, left_color)
    lcd.print(right_text, 168, 202, right_color)

# ============================================================
# IDLE SCREEN
# ============================================================

def draw_idle_screen():
    # Shown when no session active.
    # Single bold call to action — nothing else to distract.
    lcd.clear(COLOR_BG)
    _draw_header()

    # "TAP TO" — soft grey, secondary
    lcd.font(lcd.FONT_DejaVu40)
    line1 = "TAP TO"
    lcd.print(line1, _cx(line1, 26, -6), 72, COLOR_GREY_SOFT)

    # "START" — accent blue, dominant action word
    lcd.font(lcd.FONT_DejaVu56)
    line2 = "START"
    lcd.print(line2, _cx(line2, 34, -8), 130, COLOR_ACCENT)

    _draw_wifi_indicator()
    _update_last_drawn()

# ============================================================
# ACTIVE SESSION SCREEN
# ============================================================

def draw_session_screen():
    # Full redraw — called only when status or wifi changes.
    lcd.clear(COLOR_BG)
    _draw_header()

    # Status — DejaVu56, vertically centered in available space
    if state["session_paused"]:
        status_text  = "PAUSED"
        status_color = COLOR_WARN
    else:
        status_text  = "WORKING"
        status_color = COLOR_GOOD

    lcd.font(lcd.FONT_DejaVu56)
    lcd.print(status_text, _cx(status_text, 34, -12), 64, status_color)

    # Work time — DejaVu24, below status
    _draw_time_zone(format_seconds(state["work_seconds"]))

    # Bottom bar
    if state["session_paused"]:
        _draw_bottom_bar("RESUME", "TAP TO END", COLOR_WARN, COLOR_GREY_DIM)
    else:
        _draw_bottom_bar("PAUSE",  "TAP TO END", COLOR_WARN, COLOR_GREY_DIM)

    _draw_wifi_indicator()
    _update_last_drawn()

def _draw_time_zone(work_str):
    # Partial redraw — clears only time zone to prevent flickering.
    lcd.fillRect(0, 134, SCREEN_W, 40, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print(work_str, _cx(work_str, 15, -4), 138, COLOR_WHITE)

def draw_time_only():
    # Called every second — partial update, no flicker.
    _draw_time_zone(format_seconds(state["work_seconds"]))
    _last_drawn["work_seconds"] = state["work_seconds"]

def format_seconds(seconds):
    # Converts seconds to "Xh Ym Zs", "Ym Zs" or "Zs".
    if not seconds: return "0s"
    s = int(seconds) % 60
    m = int(seconds) // 60
    h = m // 60
    m = m % 60
    if h > 0: return "{}h {}m {}s".format(h, m, s)
    if m > 0: return "{}m {}s".format(m, s)
    return "{}s".format(s)

def _update_last_drawn():
    _last_drawn["session_active"] = state["session_active"]
    _last_drawn["session_paused"] = state["session_paused"]
    _last_drawn["wifi_connected"] = state["wifi_connected"]
    _last_drawn["work_seconds"]   = state["work_seconds"]

def _status_changed():
    return (
        state["session_active"] != _last_drawn["session_active"] or
        state["session_paused"] != _last_drawn["session_paused"] or
        state["wifi_connected"] != _last_drawn["wifi_connected"]
    )

def _time_changed():
    return state["work_seconds"] != _last_drawn["work_seconds"]

# ============================================================
# RFID
# ============================================================

def read_rfid():
    # Returns card UID string if a new card is detected, None otherwise.
    # Filters repeated reads — card must be removed before re-reading.
    try:
        if rfid.isNewCardPresent():
            if rfid.readCardSerial():
                card_id = rfid.getCardUID()
                if card_id != state["last_card_id"]:
                    state["last_card_id"] = card_id
                    return card_id
    except Exception as e:
        print("[RFID] Read failed:", e)

    state["last_card_id"] = None
    return None

def handle_rfid(card_id):
    # Toggle logic: first tap starts session, second tap ends it.
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
    # Button A — pause/resume active session only.
    # Ignored if no session is active.
    if btnA.wasPressed():
        if not state["session_active"]:
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
    # Posts session lifecycle event to middleware.
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
    # Keeps local state in sync with server.
    try:
        r = urequests.get(
            MIDDLEWARE_URL + "/session/current",
            timeout=5
        )
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
    # Ensures device B reflects correct state after reboot.
    fetch_session()
    print("[SYNC] Session restored:", state["session_active"])

# ============================================================
# BOOT
# ============================================================

def boot():
    # Sequence: splash → WiFi → sync → first draw
    _draw_boot_msg("Booting...")
    time.sleep(1)

    connect_wifi()
    if state["wifi_connected"]:
        boot_sync()

    if state["session_active"]:
        draw_session_screen()
    else:
        draw_idle_screen()

    print("[BOOT] Device B ready.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    # Full redraw on status change.
    # Partial time-only redraw every second when active.
    # No redraw when idle and nothing changed.
    last_session     = 0
    SESSION_INTERVAL = 5

    while True:
        now = time.time()

        # Check for RFID tap — immediate redraw on detection
        card_id = read_rfid()
        if card_id:
            handle_rfid(card_id)

        # Check pause/resume button
        handle_buttons()

        # Poll session state from middleware every 5 seconds
        if now - last_session >= SESSION_INTERVAL:
            fetch_session()
            last_session = now

        # Increment work time when active and not paused
        if state["session_active"] and not state["session_paused"]:
            state["work_seconds"] = (state["work_seconds"] or 0) + 1

        # Smart redraw — full on status change, partial on time change
        if _status_changed():
            if state["session_active"]:
                draw_session_screen()
            else:
                draw_idle_screen()
        elif state["session_active"] and _time_changed():
            draw_time_only()

        gc.collect()
        time.sleep(1)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()