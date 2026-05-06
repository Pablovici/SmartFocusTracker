# device_b/main.py
# Satellite device — RFID session management with session status display.
# MicroPython — deployed via UIFlow 1.0
# Assigned to: Amir

import gc
import time
import network
import urequests
import ujson
import unit
from m5stack import lcd, btnA, btnB, btnC

# ============================================================
# CONFIGURATION
# ============================================================
KNOWN_NETWORKS = [
    ("iPhone de Amir", "toad1234"),
    ("iot-unil",       "4u6uch4hpY9pJ2f9"),
]
MIDDLEWARE_URL  = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"
SESSION_POLL_MS = 10000   # Server sync every 10s
WIFI_CHECK_MS   = 30000   # WiFi health check every 30s
BTN_DEBOUNCE_MS = 500     # Minimum ms between button events

# ============================================================
# DISPLAY CONSTANTS
# ============================================================
COLOR_BG            = 0x1a1a2e
COLOR_WHITE         = 0xFFFFFF
COLOR_GREY_SOFT     = 0x999999
COLOR_GREY_DIM      = 0x555577
COLOR_DIVIDER       = 0x3a3a5e
COLOR_GOOD          = 0x00CC44
COLOR_WARN          = 0xFFAA00
COLOR_BAD           = 0xFF4444
COLOR_ACCENT        = 0x4fc3f7
COLOR_WIFI          = 0x4fc3f7
COLOR_CARD_ACTIVE   = 0x0d2b1a
COLOR_CARD_INACTIVE = 0x22223a
SCREEN_W            = 320
SCREEN_H            = 240

# ============================================================
# HARDWARE INITIALIZATION
# ============================================================
try:
    rfid = unit.get(unit.RFID, unit.PORTA)
    print("[RFID] Init OK")
except Exception as e:
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("RFID NOT FOUND",     40,  90, COLOR_BAD)
    lcd.print("Check Port A cable", 20, 120, COLOR_GREY_SOFT)
    lcd.print(str(e),               10, 150, COLOR_GREY_DIM)
    raise SystemExit("RFID required")

# ============================================================
# GLOBAL STATE
# ============================================================
state = {
    "session_active":  False,
    "session_paused":  False,
    "work_seconds":    0,        # Incremented +1 per compensated tick
    "active_card_id":  None,     # Restored from server on boot
    "wifi_connected":  False,
    "wifi_ssid":       "",
    "screen":          "main",
    "last_raw_card":   None,
    "last_btn_ms":     0,
    # Guards against server resurrecting a locally-ended session
    # when /session/end returns 500 (e.g. app.py not yet deployed)
    "session_end_ms":  0,
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

def connect_wifi_network(ssid, password):
    """
    Connects to one WiFi network. Polls for up to 10s.
    Returns True on success, updates state accordingly.
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        wlan.disconnect()
        time.sleep(1)
    _draw_boot_msg("Connecting to\n{}...".format(ssid))
    wlan.connect(ssid, password)
    for _ in range(10):
        if wlan.isconnected():
            state["wifi_connected"] = True
            state["wifi_ssid"]      = ssid
            _draw_boot_msg("Connected!")
            time.sleep(1)
            return True
        time.sleep(1)
    state["wifi_connected"] = False
    state["wifi_ssid"]      = ""
    return False

def connect_wifi():
    """Try each KNOWN_NETWORK in order. Fall back to offline."""
    for ssid, password in KNOWN_NETWORKS:
        if connect_wifi_network(ssid, password):
            return True
    _draw_boot_msg("No WiFi - offline")
    time.sleep(2)
    return False

def check_wifi_alive():
    """
    Silent background reconnect check — does not touch the screen.
    Called every WIFI_CHECK_MS from the main loop.
    """
    wlan = network.WLAN(network.STA_IF)
    if wlan.isconnected():
        state["wifi_connected"] = True
        return
    print("[WiFi] Lost — reconnecting...")
    state["wifi_connected"] = False
    state["wifi_ssid"]      = ""
    wlan.active(True)
    for ssid, password in KNOWN_NETWORKS:
        wlan.connect(ssid, password)
        for _ in range(8):
            if wlan.isconnected():
                state["wifi_connected"] = True
                state["wifi_ssid"]      = ssid
                print("[WiFi] Reconnected:", ssid)
                return
            time.sleep(1)
    print("[WiFi] Reconnect failed")

# ============================================================
# DISPLAY — low-level helpers
# ============================================================

def _draw_boot_msg(msg):
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(msg, 10, 100, COLOR_ACCENT)

def _cx(text, char_w, offset=0):
    """Centres text horizontally. char_w must match the active font."""
    return max(0, (SCREEN_W - len(text) * char_w) // 2 + offset)

def _rx(text, char_w, margin=10):
    """Right-aligns text from the right edge."""
    return max(0, SCREEN_W - len(text) * char_w - margin)

def _split_ssid(ssid, max_chars=11):
    """
    Splits a long SSID into two lines to fit inside a narrow WiFi card.
    Breaks at the last space before max_chars.
    Example: "iPhone de Amir" -> ["iPhone de", "Amir"]
    """
    if len(ssid) <= max_chars:
        return [ssid, ""]
    idx = ssid.rfind(" ", 0, max_chars)
    if idx > 0:
        return [ssid[:idx], ssid[idx + 1:]]
    return [ssid[:max_chars], ssid[max_chars:]]

def _draw_header():
    lcd.font(lcd.FONT_DejaVu18)
    header = "- FOCUS TRACKER -"
    lcd.print(header, _cx(header, 11, -4), 10, COLOR_ACCENT)
    lcd.line(0, 32, SCREEN_W, 32, COLOR_DIVIDER)

def _draw_time_zone(work_str):
    """Partial redraw — erases only the time zone rectangle to avoid ghosting."""
    lcd.fillRect(0, 134, SCREEN_W, 42, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print(work_str, _cx(work_str, 15, -4), 140, COLOR_WHITE)

# ============================================================
# DISPLAY — bottom bars
# ============================================================

def _draw_bottom_bar(pause_label):
    """
    Session screen bottom bar:
      y=188: divider
      y=196: TAP TO END  (centred — constant position)
      y=218: PAUSE/RESUME (left, BtnA) | WiFi OK/No WiFi (right, BtnC)
    """
    lcd.line(0, 188, SCREEN_W, 188, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    tap = "TAP TO END"
    lcd.print(tap,         _cx(tap, 11, -4),     196, COLOR_GREY_SOFT)
    lcd.print(pause_label, 10,                   218, COLOR_WARN)
    wifi_text  = "WiFi OK" if state["wifi_connected"] else "No WiFi"
    wifi_color = COLOR_WIFI if state["wifi_connected"] else COLOR_BAD
    lcd.print(wifi_text, _rx(wifi_text, 11, 10), 218, wifi_color)

def _draw_idle_bottom():
    """
    Idle screen bottom bar.
    WiFi status on the right at BtnC physical position.
    """
    lcd.line(0, 188, SCREEN_W, 188, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    wifi_text  = "WiFi OK" if state["wifi_connected"] else "No WiFi"
    wifi_color = COLOR_WIFI if state["wifi_connected"] else COLOR_BAD
    lcd.print(wifi_text, _rx(wifi_text, 11, 10), 218, wifi_color)

# ============================================================
# DISPLAY — WiFi selection screen
# ============================================================

def _draw_wifi_card(x, y, w, h, ssid):
    """
    Draws one network card for the WiFi selection screen.
    Active network: green-tinted background + green top border.
    Inactive network: dark background + dim border.
    SSID split into two lines via _split_ssid() if too long.
    ASCII-only labels — MicroPython bitmap fonts may not support Unicode.
    """
    is_active = state["wifi_connected"] and state["wifi_ssid"] == ssid
    bg        = COLOR_CARD_ACTIVE if is_active else COLOR_CARD_INACTIVE
    lcd.fillRect(x, y, w, h, bg)

    top_color = COLOR_GOOD if is_active else COLOR_DIVIDER
    lcd.line(x,     y,     x + w, y,     top_color)
    lcd.line(x,     y,     x,     y + h, COLOR_DIVIDER)
    lcd.line(x + w, y,     x + w, y + h, COLOR_DIVIDER)
    lcd.line(x,     y + h, x + w, y + h, COLOR_DIVIDER)

    lines      = _split_ssid(ssid, 11)
    name_color = COLOR_WHITE if is_active else COLOR_GREY_SOFT
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(lines[0], x + 7, y + 10, name_color)
    if lines[1]:
        lcd.print(lines[1], x + 7, y + 30, name_color)

    if is_active:
        lcd.print(">> Active", x + 7, y + 72, COLOR_GOOD)
    else:
        lcd.print("Tap to",   x + 7, y + 68, COLOR_GREY_DIM)
        lcd.print("connect",  x + 7, y + 88, COLOR_GREY_DIM)

def draw_wifi_screen():
    """
    WiFi selection screen with two network cards side by side.
    Button labels use directional arrows — no technical "BtnA/BtnC" jargon.

    BtnA (left)   → "< Connect" → KNOWN_NETWORKS[0]
    BtnB (middle) → "Cancel"    → back without changing
    BtnC (right)  → "Connect >" → KNOWN_NETWORKS[1]
    """
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    title = "WiFi Selection"
    lcd.print(title, _cx(title, 11, -4), 8, COLOR_ACCENT)
    lcd.line(0, 30, SCREEN_W, 30, COLOR_DIVIDER)

    _draw_wifi_card(6,   40, 146, 138, KNOWN_NETWORKS[0][0])
    _draw_wifi_card(168, 40, 146, 138, KNOWN_NETWORKS[1][0])

    lcd.line(0, 188, SCREEN_W, 188, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("< Connect", 10,                        205, COLOR_ACCENT)
    lcd.print("Cancel",    _cx("Cancel", 11, -4),     205, COLOR_GREY_SOFT)
    lcd.print("Connect >", _rx("Connect >", 11, 10),  205, COLOR_ACCENT)

# ============================================================
# DISPLAY — main screens
# ============================================================

def draw_idle_screen():
    lcd.clear(COLOR_BG)
    _draw_header()
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("TAP TO", _cx("TAP TO", 26, -6), 72, COLOR_GREY_SOFT)
    lcd.font(lcd.FONT_DejaVu56)
    lcd.print("START", _cx("START", 34, -8), 128, COLOR_ACCENT)
    _draw_idle_bottom()
    _update_last_drawn()

def draw_session_screen():
    lcd.clear(COLOR_BG)
    _draw_header()
    if state["session_paused"]:
        status_text, status_color = "PAUSED",  COLOR_WARN
        pause_label = "RESUME"
    else:
        status_text, status_color = "WORKING", COLOR_GOOD
        pause_label = "PAUSE"
    lcd.font(lcd.FONT_DejaVu56)
    lcd.print(status_text, _cx(status_text, 34, -12), 62, status_color)
    _draw_time_zone(format_seconds(state["work_seconds"]))
    _draw_bottom_bar(pause_label)
    _update_last_drawn()

def draw_time_only():
    """Lightweight partial redraw — only the time zone rectangle."""
    _draw_time_zone(format_seconds(state["work_seconds"]))
    _last_drawn["work_seconds"] = state["work_seconds"]

def draw_error_screen(message, duration=3):
    """
    Large centred error message with subtitle hint.
    char_w=23 is the empirically correct value for DejaVu40 on M5Stack Core2.
    """
    lcd.clear(COLOR_BG)
    _draw_header()
    lcd.font(lcd.FONT_DejaVu40)
    x = max(10, (SCREEN_W - len(message) * 23) // 2)
    lcd.print(message, x, 100, COLOR_BAD)
    hint = "Only same card can end"
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(hint, _cx(hint, 11, -4), 158, COLOR_GREY_SOFT)
    time.sleep(duration)
    draw_session_screen() if state["session_active"] else draw_idle_screen()

# ============================================================
# DISPLAY — utilities
# ============================================================

def format_seconds(seconds):
    """Human-readable elapsed time. Integer arithmetic only — no floats."""
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
    """
    Returns a UID only on a fresh tap (card was absent before).
    Resets last_raw_card to None when card is removed so the
    next tap fires correctly.
    """
    try:
        if rfid.isCardOn():
            card_id = str(rfid.readUid())
            if card_id != state["last_raw_card"]:
                state["last_raw_card"] = card_id
                return card_id
        else:
            state["last_raw_card"] = None
    except Exception as e:
        print("[RFID] Read failed:", e)
    return None

def handle_rfid(card_id):
    """
    Tap logic:
      No active session → start one.
      Active session + same card → end it.
      Active session + different card → error screen.

    Fallback: if active_card_id is None (not restored after reboot),
    the first card tap claims ownership so the user is never stuck.

    GUARD 1 — draw idle screen BEFORE the HTTP POST so the user
    gets instant visual feedback instead of waiting for the network.

    GUARD 2 — session_end_ms is recorded so fetch_session() can
    ignore the server's stale active=True for 15 seconds after
    a local session end, preventing ghost session resurrection.
    """
    if not state["session_active"]:
        post_session_event("start", card_id)
        state["session_active"] = True
        state["session_paused"] = False
        state["work_seconds"]   = 0
        state["active_card_id"] = card_id
        print("[RFID] Session started:", card_id)
    else:
        if state["active_card_id"] is None:
            # Reboot without card info from server — accept first card
            print("[RFID] active_card_id unknown — claiming:", card_id)
            state["active_card_id"] = card_id

        if card_id != state["active_card_id"]:
            print("[RFID] Wrong card:", card_id)
            draw_error_screen("Wrong card!", duration=3)
            return

        # Update local state immediately — before the HTTP call
        state["session_active"] = False
        state["session_paused"] = False
        state["active_card_id"] = None
        state["work_seconds"]   = 0
        # GUARD 2: timestamp the local end for fetch_session() cooldown
        state["session_end_ms"] = time.ticks_ms()
        # GUARD 1: show idle immediately — user sees response before HTTP
        draw_idle_screen()
        # HTTP POST happens after visual update
        post_session_event("end", card_id)
        print("[RFID] Session ended:", card_id)

# ============================================================
# BUTTONS
# ============================================================

def _btn_allowed():
    """Debounce guard — returns True only if BTN_DEBOUNCE_MS has elapsed."""
    now = time.ticks_ms()
    if time.ticks_diff(now, state["last_btn_ms"]) < BTN_DEBOUNCE_MS:
        return False
    state["last_btn_ms"] = now
    return True

def handle_buttons():
    """
    WiFi screen:
      BtnA (left)   → connect to KNOWN_NETWORKS[0]
      BtnB (middle) → cancel / back
      BtnC (right)  → connect to KNOWN_NETWORKS[1]

    Main screen:
      BtnA (left)   → pause / resume
      BtnC (right)  → open WiFi screen
    """
    if state["screen"] == "wifi":
        if btnA.wasPressed() and _btn_allowed():
            ssid, pwd = KNOWN_NETWORKS[0]
            connect_wifi_network(ssid, pwd)
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        elif btnB.wasPressed() and _btn_allowed():
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        elif btnC.wasPressed() and _btn_allowed():
            ssid, pwd = KNOWN_NETWORKS[1]
            connect_wifi_network(ssid, pwd)
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        return

    if btnA.wasPressed() and _btn_allowed():
        if not state["session_active"]:
            return
        if state["session_paused"]:
            post_session_event("resume", None)
            state["session_paused"] = False
            print("[BTN] Resumed")
        else:
            post_session_event("pause", None)
            state["session_paused"] = True
            print("[BTN] Paused")
        draw_session_screen()

    if btnC.wasPressed() and _btn_allowed():
        state["screen"] = "wifi"
        draw_wifi_screen()

# ============================================================
# DATA
# ============================================================

def post_session_event(event_type, card_id):
    """
    POSTs a session lifecycle event to the middleware.
    No timeout parameter — not supported in MicroPython urequests.
    Errors are caught and logged without crashing the device.
    gc.collect() called after every network op to free memory.
    """
    payload = {"event": event_type, "card_id": card_id}
    try:
        r = urequests.post(
            MIDDLEWARE_URL + "/session/{}".format(event_type),
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload)
        )
        r.close()
        print("[SESSION] Posted:", event_type)
    except Exception as e:
        print("[SESSION] Post failed:", e)
    gc.collect()

def fetch_session(boot_sync=False):
    """
    GETs /session/current from middleware.

    Always syncs: session_active
    Boot only:    session_paused, work_seconds, active_card_id
    Never synced after boot: session_paused, work_seconds
      → device is sole source of truth for those values

    GUARD 2 — if the session was locally ended less than 15 seconds ago,
    we ignore the server returning active=True. This prevents a ghost
    session from reappearing when /session/end returned a 500 error
    (e.g. app.py not yet deployed with the correct bq function calls).
    """
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current")
        if r.status_code == 200:
            data = ujson.loads(r.text)

            server_active = data.get("active", False)

            # GUARD 2: cooldown after local session end
            if not boot_sync and not state["session_active"] and server_active:
                ms_since_end = time.ticks_diff(time.ticks_ms(), state["session_end_ms"])
                if ms_since_end < 15000:
                    print("[SESSION] Ignoring server active=True — end cooldown active")
                    server_active = False

            prev_active             = state["session_active"]
            state["session_active"] = server_active

            # Server confirms session ended → clean up local state
            if prev_active and not state["session_active"]:
                state["session_paused"]  = False
                state["active_card_id"]  = None
                state["work_seconds"]    = 0
                print("[SESSION] Server ended session — local reset")

            if boot_sync:
                state["session_paused"] = data.get("paused", False)
                state["active_card_id"] = (
                    data.get("card_id") or data.get("rfid_card_id")
                )
                state["work_seconds"]   = int(data.get("work_seconds", 0))
                print("[SESSION] Boot sync — active:", state["session_active"],
                      "paused:", state["session_paused"],
                      "card:", state["active_card_id"],
                      "seconds:", state["work_seconds"])

        r.close()
    except Exception as e:
        print("[SESSION] Fetch failed:", e)
    gc.collect()

# ============================================================
# BOOT
# ============================================================

def boot():
    """
    Startup sequence:
    1. Boot splash
    2. WiFi connection
    3. Full session sync from server (boot_sync=True)
       Restores: active, paused, work_seconds, active_card_id
    4. Draw correct initial screen
    """
    _draw_boot_msg("Booting...")
    time.sleep(1)
    connect_wifi()
    if state["wifi_connected"]:
        fetch_session(boot_sync=True)
    draw_session_screen() if state["session_active"] else draw_idle_screen()
    print("[BOOT] Ready.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    """
    1-second tick loop with compensated sleep.

    Each iteration measures its own duration and sleeps only the
    remaining time to reach 1000ms total. This ensures the timer
    increments smoothly at exactly 1 second regardless of how long
    fetch_session() HTTP calls take (normally 300-1500ms).

    Examples:
      Loop body = 50ms   → sleep 950ms → total ~1000ms
      Loop body = 800ms  → sleep 200ms → total ~1000ms
      Loop body = 1200ms → sleep 0ms   → this tick is slightly late (rare)
    """
    last_poll_ms = time.ticks_ms()
    last_wifi_ms = time.ticks_ms()

    while True:
        tick_start_ms = time.ticks_ms()

        # Step 1: buttons (both screens)
        handle_buttons()

        # Step 2: RFID (main screen only)
        if state["screen"] == "main":
            card_id = read_rfid()
            if card_id:
                handle_rfid(card_id)

        # Step 3: periodic server sync (every SESSION_POLL_MS)
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_poll_ms) >= SESSION_POLL_MS:
            if state["wifi_connected"]:
                fetch_session(boot_sync=False)
            last_poll_ms = time.ticks_ms()

        # Step 4: periodic WiFi health check (every WIFI_CHECK_MS)
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_wifi_ms) >= WIFI_CHECK_MS:
            check_wifi_alive()
            last_wifi_ms = time.ticks_ms()

        # Step 5: increment work timer
        if state["session_active"] and not state["session_paused"]:
            state["work_seconds"] = (state["work_seconds"] or 0) + 1

        # Step 6: smart redraw (main screen only)
        if state["screen"] == "main":
            if _status_changed():
                draw_session_screen() if state["session_active"] else draw_idle_screen()
            elif state["session_active"] and _time_changed():
                draw_time_only()

        # Step 7: compensated sleep
        gc.collect()
        elapsed_ms   = time.ticks_diff(time.ticks_ms(), tick_start_ms)
        remaining_ms = max(0, 1000 - elapsed_ms)
        if remaining_ms > 0:
            time.sleep_ms(remaining_ms)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()