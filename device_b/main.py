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
MIDDLEWARE_URL      = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"
SESSION_POLL_MS     = 10000   # Poll server every 10s (was 5s — reduces HTTP blocking)
WIFI_CHECK_MS       = 30000   # Check WiFi alive every 30s
BTN_DEBOUNCE_MS     = 500     # Minimum ms between two button events

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
COLOR_WIFI      = 0x4fc3f7   # Same as accent — WiFi OK reads as positive
SCREEN_W        = 320
SCREEN_H        = 240

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
    "session_active":    False,
    "session_paused":    False,
    "work_seconds":      0,       # Computed from ticks — never overwritten by server
    "active_card_id":    None,
    "wifi_connected":    False,
    "wifi_ssid":         "",
    "screen":            "main",
    "last_raw_card":     None,
    "last_btn_ms":       0,

    # FIX TIMER — real-time elapsed tracking
    # session_start_ms: ticks_ms() at session start or last resume
    # base_work_seconds: seconds accumulated before the current run (before pauses)
    # Together they allow: work_seconds = base + (now - start) / 1000
    # This means even if the loop blocks for 1s (HTTP), the timer catches up instantly.
    "session_start_ms":  0,
    "base_work_seconds": 0,
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
    Connects to a single WiFi network.
    Polls wlan.isconnected() up to 10 times (1s each).
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
    """Try each known network in order. Fall back to offline on all failure."""
    for ssid, password in KNOWN_NETWORKS:
        if connect_wifi_network(ssid, password):
            return True
    _draw_boot_msg("No WiFi - offline")
    time.sleep(2)
    return False

def check_wifi_alive():
    """
    Silent background WiFi health check.
    If connection dropped, tries to reconnect without touching the screen.
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
# TIMER — real-time computation
# ============================================================

def _compute_work_seconds():
    """
    FIX TIMER — computes elapsed work seconds from real ticks, not increments.

    Previous approach: work_seconds += 1 each loop tick.
    Problem: if the loop blocks for 1-2s (HTTP request in fetch_session),
    the increment is skipped → timer jumps irregularly.

    New approach: work_seconds = base_work_seconds + (now - session_start_ms) / 1000
    - base_work_seconds accumulates all time before the current run (pre-pause)
    - session_start_ms is the ticks_ms() when the current run started
    - Result: even if the loop blocks, the next call to _compute_work_seconds()
      catches up instantly because it reads real clock time.
    """
    if not state["session_active"] or state["session_paused"]:
        return state["work_seconds"]   # Return frozen value when paused
    if not state["session_start_ms"]:
        return state["work_seconds"]
    elapsed_ms = time.ticks_diff(time.ticks_ms(), state["session_start_ms"])
    return state["base_work_seconds"] + max(0, elapsed_ms // 1000)

def _start_timer():
    """Called on session start or resume — records the ticks_ms() reference point."""
    state["session_start_ms"] = time.ticks_ms()

def _pause_timer():
    """
    Called on pause — freezes work_seconds at the current real value.
    base_work_seconds absorbs the elapsed time so it's preserved across pauses.
    session_start_ms is zeroed so _compute_work_seconds returns the frozen value.
    """
    state["work_seconds"]      = _compute_work_seconds()
    state["base_work_seconds"] = state["work_seconds"]
    state["session_start_ms"]  = 0

def _reset_timer():
    """Called on session end — resets all timer state."""
    state["work_seconds"]      = 0
    state["base_work_seconds"] = 0
    state["session_start_ms"]  = 0

# ============================================================
# DISPLAY — helpers
# ============================================================

def _draw_boot_msg(msg):
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(msg, 10, 100, COLOR_ACCENT)

def _cx(text, char_w, offset=0):
    """Returns x to horizontally centre text. char_w must match the active font."""
    return max(0, (SCREEN_W - len(text) * char_w) // 2 + offset)

def _rx(text, char_w, margin=10):
    """
    Returns x to right-align text with a given right margin.
    char_w must match the active font.
    Used to place WiFi status at the BtnC (right) position.
    """
    return max(0, SCREEN_W - len(text) * char_w - margin)

def _draw_header():
    lcd.font(lcd.FONT_DejaVu18)
    header = "- FOCUS TRACKER -"
    lcd.print(header, _cx(header, 11, -4), 10, COLOR_ACCENT)
    lcd.line(0, 32, SCREEN_W, 32, COLOR_DIVIDER)

def _draw_time_zone(work_str):
    """
    Partial redraw — erases only the time rectangle before rewriting.
    Avoids screen ghosting without clearing the whole screen.
    """
    lcd.fillRect(0, 134, SCREEN_W, 42, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print(work_str, _cx(work_str, 15, -4), 140, COLOR_WHITE)

def _draw_bottom_bar(pause_label):
    """
    New bottom bar layout:

      y=188: ──────────── divider ────────────
      y=196:      TAP TO END (centred)
      y=216: PAUSE/RESUME          WiFi OK/No WiFi
             ↑ BtnA (left)         ↑ BtnC (right)

    - "TAP TO END" is always centred and at a fixed y — easy to find.
    - PAUSE/RESUME is bottom-left aligned with BtnA physical position.
    - WiFi status is bottom-right aligned with BtnC physical position.
      It doubles as a status indicator and a hint that BtnB opens WiFi settings.

    pause_label: "PAUSE" or "RESUME" depending on current state.
    """
    lcd.line(0, 188, SCREEN_W, 188, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)

    # Row 1: TAP TO END — always centred, always at y=196
    tap = "TAP TO END"
    lcd.print(tap, _cx(tap, 11, -4), 196, COLOR_GREY_SOFT)

    # Row 2 left: PAUSE or RESUME at x=10, y=216 — aligns with BtnA
    lcd.print(pause_label, 10, 218, COLOR_WARN)

    # Row 2 right: WiFi status right-aligned — aligns with BtnC
    if state["wifi_connected"]:
        wifi_text  = "WiFi OK"
        wifi_color = COLOR_WIFI
    else:
        wifi_text  = "No WiFi"
        wifi_color = COLOR_BAD
    lcd.print(wifi_text, _rx(wifi_text, 11, 10), 218, wifi_color)

def _draw_idle_bottom():
    """
    Bottom bar for idle screen (no active session).
    Shows a hint to open WiFi settings, and WiFi status on the right.
    """
    lcd.line(0, 188, SCREEN_W, 188, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    # Left: BtnB hint
    lcd.print("WiFi", 10, 218, COLOR_GREY_DIM)
    # Right: current WiFi status at BtnC position
    if state["wifi_connected"]:
        wifi_text  = "WiFi OK"
        wifi_color = COLOR_WIFI
    else:
        wifi_text  = "No WiFi"
        wifi_color = COLOR_BAD
    lcd.print(wifi_text, _rx(wifi_text, 11, 10), 218, wifi_color)

# ============================================================
# DISPLAY — full screen draws
# ============================================================

def draw_idle_screen():
    """
    Idle screen — shown when no session is active.
    Large "TAP TO / START" prompt invites badge tap.
    """
    lcd.clear(COLOR_BG)
    _draw_header()
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("TAP TO", _cx("TAP TO", 26, -6), 72, COLOR_GREY_SOFT)
    lcd.font(lcd.FONT_DejaVu56)
    lcd.print("START", _cx("START", 34, -8), 128, COLOR_ACCENT)
    _draw_idle_bottom()
    _update_last_drawn()

def draw_session_screen():
    """
    Active session screen (WORKING or PAUSED).
    Calls _compute_work_seconds() so the time zone always shows
    the real elapsed value at draw time, even after HTTP blocking.
    """
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
    # Compute real work_seconds before drawing
    state["work_seconds"] = _compute_work_seconds()
    _draw_time_zone(format_seconds(state["work_seconds"]))
    _draw_bottom_bar(pause_label)
    _update_last_drawn()

def draw_time_only():
    """
    Lightweight partial redraw — only the time zone.
    Called every second when only work_seconds changed.
    Avoids the cost of lcd.clear() on every tick.
    """
    state["work_seconds"] = _compute_work_seconds()
    _draw_time_zone(format_seconds(state["work_seconds"]))
    _last_drawn["work_seconds"] = state["work_seconds"]

def draw_error_screen(message, duration=3):
    """
    Large centred error screen shown on wrong card tap.

    FIX WRONG CARD POSITION:
    - DejaVu40 on M5Stack Core2 has an actual char width of ~23px
      (not 26 as previously assumed). Using 23 centres the text correctly.
    - y moved from 85 to 100 — vertically more centred between header and middle.
    - Subtitle moved from 145 to 158 to match.
    """
    lcd.clear(COLOR_BG)
    _draw_header()
    lcd.font(lcd.FONT_DejaVu40)
    # char_w=23 for DejaVu40 on M5Stack Core2 (measured empirically)
    x = max(10, (SCREEN_W - len(message) * 23) // 2)
    lcd.print(message, x, 100, COLOR_BAD)
    hint = "Only same card can end"
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(hint, _cx(hint, 11, -4), 158, COLOR_GREY_SOFT)
    time.sleep(duration)
    draw_session_screen() if state["session_active"] else draw_idle_screen()

def draw_wifi_screen():
    """
    WiFi selection overlay.
    BtnA → KNOWN_NETWORKS[0], BtnC → KNOWN_NETWORKS[1], BtnB → cancel.
    Non-blocking: this function only draws — buttons handled in handle_buttons().
    """
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("- WiFi Setup -", _cx("- WiFi Setup -", 11, -4), 10, COLOR_ACCENT)
    lcd.line(0, 32, SCREEN_W, 32, COLOR_DIVIDER)
    lcd.print("BtnA:", 10, 60, COLOR_GREY_SOFT)
    lcd.print(KNOWN_NETWORKS[0][0], 80, 60, COLOR_WHITE)
    lcd.print("BtnC:", 10, 95, COLOR_GREY_SOFT)
    lcd.print(KNOWN_NETWORKS[1][0], 80, 95, COLOR_WHITE)
    lcd.line(0, 130, SCREEN_W, 130, COLOR_DIVIDER)
    lcd.print("BtnB: back", _cx("BtnB: back", 11, -4), 142, COLOR_GREY_DIM)
    if state["wifi_connected"]:
        current = "Now: {}".format(state["wifi_ssid"])
        lcd.print(current, _cx(current, 11, -4), 170, COLOR_WIFI)

# ============================================================
# DISPLAY — utilities
# ============================================================

def format_seconds(seconds):
    """
    Converts raw seconds to a human-readable string.
    Uses integer arithmetic only — no floats (MicroPython safe).
    """
    if not seconds:
        return "0s"
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
    """True if a major state change requires a full screen redraw."""
    return (
        state["session_active"] != _last_drawn["session_active"] or
        state["session_paused"] != _last_drawn["session_paused"] or
        state["wifi_connected"] != _last_drawn["wifi_connected"]
    )

def _time_changed():
    """True if work_seconds advanced — triggers a lightweight time-only redraw."""
    return state["work_seconds"] != _last_drawn["work_seconds"]

# ============================================================
# RFID
# ============================================================

def read_rfid():
    """
    Polls the RFID reader. Returns a UID only on a fresh tap.
    De-duplication: last_raw_card prevents a held card from firing repeatedly.
    Resets to None when card is removed so the next tap fires correctly.
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
    Same card → start if idle, end if active.
    Different card while active → error screen, session continues.
    Timer helpers called here to keep timing accurate.
    """
    if not state["session_active"]:
        post_session_event("start", card_id)
        state["session_active"] = True
        state["session_paused"] = False
        state["active_card_id"] = card_id
        _reset_timer()
        _start_timer()   # Start real-time tracking
        print("[RFID] Session started:", card_id)
    else:
        if card_id != state["active_card_id"]:
            print("[RFID] Wrong card:", card_id)
            draw_error_screen("Wrong card!", duration=3)
            return
        post_session_event("end", card_id)
        state["session_active"] = False
        state["session_paused"] = False
        state["active_card_id"] = None
        _reset_timer()
        print("[RFID] Session ended:", card_id)

# ============================================================
# BUTTONS
# ============================================================

def _btn_allowed():
    """
    Debounce guard — returns True only if BTN_DEBOUNCE_MS
    has elapsed since the last button event.
    Prevents a single physical press from registering multiple times.
    """
    now = time.ticks_ms()
    if time.ticks_diff(now, state["last_btn_ms"]) < BTN_DEBOUNCE_MS:
        return False
    state["last_btn_ms"] = now
    return True

def handle_buttons():
    """
    All button logic in one place — works for both screens.

    WiFi screen: BtnA/BtnC connect, BtnB cancels.
    Main screen: BtnA pauses/resumes, BtnB opens WiFi screen.

    Pause/resume uses _pause_timer() and _start_timer() to ensure
    the real-time elapsed tracking stays accurate across state changes.
    """
    if state["screen"] == "wifi":
        if btnA.wasPressed() and _btn_allowed():
            ssid, pwd = KNOWN_NETWORKS[0]
            connect_wifi_network(ssid, pwd)
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        elif btnC.wasPressed() and _btn_allowed():
            ssid, pwd = KNOWN_NETWORKS[1]
            connect_wifi_network(ssid, pwd)
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        elif btnB.wasPressed() and _btn_allowed():
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        return

    if btnA.wasPressed() and _btn_allowed():
        if not state["session_active"]:
            return
        if state["session_paused"]:
            # Resume: restart the real-time tracking from current base
            post_session_event("resume", None)
            state["session_paused"] = False
            _start_timer()
            print("[BTN] Resumed")
        else:
            # Pause: freeze the timer at current real value
            post_session_event("pause", None)
            _pause_timer()
            state["session_paused"] = True
            print("[BTN] Paused — work_seconds:", state["work_seconds"])
        # Force immediate redraw so the screen reflects the new state
        draw_session_screen()

    if btnB.wasPressed() and _btn_allowed():
        state["screen"] = "wifi"
        draw_wifi_screen()

# ============================================================
# DATA — posting and fetching
# ============================================================

def post_session_event(event_type, card_id):
    """
    POSTs a session lifecycle event to the middleware.
    No timeout parameter — not supported in MicroPython urequests.
    gc.collect() called after every network op to reclaim memory.
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

    What IS synced:
    - session_active: always — it changes only via RFID, safe to follow server.

    What is NEVER synced after boot:
    - session_paused: server state can lag behind local button presses,
      causing the pause to flip by itself. Device is sole source of truth.
    - work_seconds: tracked locally via ticks_ms — server value is unreliable.

    boot_sync=True (only at startup):
    - Also restores session_paused and work_seconds from server.
    - Allows the device to resume a session that was active before a reboot.
    """
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current")
        if r.status_code == 200:
            data = ujson.loads(r.text)

            prev_active           = state["session_active"]
            state["session_active"] = data.get("active", False)

            # If server says session ended while we thought it was active → clean up
            if prev_active and not state["session_active"]:
                state["session_paused"]  = False
                state["active_card_id"]  = None
                _reset_timer()
                print("[SESSION] Server ended session — local reset")

            if boot_sync:
                state["session_paused"]    = data.get("paused", False)
                server_seconds             = int(data.get("work_seconds", 0))
                state["work_seconds"]      = server_seconds
                state["base_work_seconds"] = server_seconds
                # If session is active and not paused, start the local timer
                if state["session_active"] and not state["session_paused"]:
                    _start_timer()
                print("[SESSION] Boot sync OK — work_seconds:", server_seconds)

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
    Main event loop — runs forever at ~100ms per cycle.

    Timer accuracy fix:
    The loop no longer increments work_seconds by +1 per tick.
    Instead, _compute_work_seconds() is called at draw time and
    computes the exact elapsed value from ticks_ms(). This means
    HTTP blocking (fetch_session) no longer causes timer jumps —
    the next draw immediately shows the correct accumulated time.

    Screen redraws:
    - Full redraw: if session_active, session_paused or wifi_connected changed
    - Partial redraw (time zone only): if work_seconds advanced by ≥1 second
    """
    last_poll_ms  = time.ticks_ms()
    last_wifi_ms  = time.ticks_ms()

    while True:
        now_ms = time.ticks_ms()

        # Step 1: buttons (both screens)
        handle_buttons()

        # Step 2: RFID (main screen only — not while navigating WiFi menu)
        if state["screen"] == "main":
            card_id = read_rfid()
            if card_id:
                handle_rfid(card_id)

        # Step 3: periodic server sync
        if time.ticks_diff(now_ms, last_poll_ms) >= SESSION_POLL_MS:
            if state["wifi_connected"]:
                fetch_session(boot_sync=False)
            last_poll_ms = now_ms

        # Step 4: periodic WiFi health check
        if time.ticks_diff(now_ms, last_wifi_ms) >= WIFI_CHECK_MS:
            check_wifi_alive()
            last_wifi_ms = now_ms

        # Step 5: compute current work_seconds from real ticks
        # This runs every loop cycle — cheap (no HTTP, no LCD)
        if state["session_active"] and not state["session_paused"]:
            state["work_seconds"] = _compute_work_seconds()

        # Step 6: smart redraw (main screen only)
        if state["screen"] == "main":
            if _status_changed():
                draw_session_screen() if state["session_active"] else draw_idle_screen()
            elif state["session_active"] and _time_changed():
                draw_time_only()

        gc.collect()
        time.sleep_ms(100)   # 100ms cycle — responsive + CPU-friendly

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()