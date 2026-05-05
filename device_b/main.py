# device_b/main.py
# Satellite device — RFID session management with session status display.
# Responsibilities:
#   - Read RFID badge → trigger session start/end via middleware
#   - Button A → pause/resume session
#   - Button B → WiFi selection screen (non-blocking)
#   - Display session status on M5Stack Core2 screen
# MicroPython — deployed via UIFlow 1.0
# Assigned to: Amir
#
# BUG FIXES applied in this version:
#   Bug 1 — work_seconds now tracked locally only (not overwritten by fetch_session)
#   Bug 2 — WiFi indicator moved down to y=220/y=236, below bottom bar
#   Bug 3 — WiFi screen handled inline (no more `continue`), timer keeps running
#   Bug 4 — Cooldown of 3s after any button press before fetch_session can overwrite paused state
#   Bug 5 — draw_session_screen() forced immediately on pause/resume event

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
# Known WiFi networks tried in order during boot and manual switch.
# WiFi credentials are hardcoded here (UIFlow single-file constraint).
# They are NOT committed to Git separately.
KNOWN_NETWORKS = [
    ("iPhone de Amir", "toad1234"),
    ("iot-unil",       "4u6uch4hpY9pJ2f9"),
]

# Base URL of the Flask middleware deployed on Cloud Run.
# All session events are sent here.
MIDDLEWARE_URL = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"

# How often (seconds) we poll /session/current for sync
SESSION_POLL_INTERVAL = 5

# How long (seconds) after a button press before fetch_session() can
# overwrite local paused state. Prevents server lag from un-doing local changes.
# FIX Bug 4
BTN_COOLDOWN = 3

# ============================================================
# DISPLAY CONSTANTS
# ============================================================
# All colors in RGB hex, as expected by the M5Stack lcd module.
COLOR_BG        = 0x1a1a2e   # Dark navy background
COLOR_WHITE     = 0xFFFFFF
COLOR_GREY_SOFT = 0x999999
COLOR_GREY_DIM  = 0x666666
COLOR_DIVIDER   = 0x3a3a5e   # Subtle separator line
COLOR_GOOD      = 0x00CC44   # Green — active/working state
COLOR_WARN      = 0xFFAA00   # Amber — paused state
COLOR_BAD       = 0xFF4444   # Red — error / bad WiFi
COLOR_ACCENT    = 0x4fc3f7   # Light blue — header/accent
COLOR_WIFI      = 0x334455   # Dim blue — WiFi OK label

# Physical pixel width of the M5Stack Core2 screen
SCREEN_W = 320

# ============================================================
# HARDWARE INITIALIZATION — RFID
# ============================================================
# unit.get() initialises the RFID RC522 module attached to Port A (I2C).
# If the module is missing or the cable is loose, we show an error and halt.
# Halting with SystemExit prevents the loop() from running without a sensor.
try:
    rfid = unit.get(unit.RFID, unit.PORTA)
    print("[RFID] Init OK")
except Exception as e:
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("RFID NOT FOUND",     40,  90, COLOR_BAD)
    lcd.print("Check Port A cable", 20, 120, COLOR_GREY_SOFT)
    lcd.print(str(e),               10, 150, COLOR_GREY_DIM)
    print("[RFID] Fatal:", e)
    raise SystemExit("RFID required")

# ============================================================
# GLOBAL STATE
# ============================================================
# Single dict that holds all runtime state.
# Using a dict (instead of global variables) makes it easy to pass around
# and inspect the full device state at once.
state = {
    "session_active":  False,   # Is a focus session currently running?
    "session_paused":  False,   # Is the current session paused?
    "work_seconds":    0,       # Elapsed work time — tracked LOCALLY (Bug 1 fix)
    "active_card_id":  None,    # UID of the card that started the session
    "wifi_connected":  False,   # Are we online?
    "wifi_ssid":       "",      # Name of the connected network
    "screen":          "main",  # Current screen: "main" | "wifi"
    "last_raw_card":   None,    # Last raw UID seen — for de-duplication
    # FIX Bug 4 — timestamp of the last button press, initialised to 0 (epoch)
    "last_btn_press":  0,
}

# Tracks the last values that were drawn to screen.
# Used by _status_changed() and _time_changed() to decide
# whether a redraw is necessary — avoids unnecessary full redraws.
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
    Attempt to connect to a single WiFi network.
    Polls wlan.isconnected() up to 10 times (1 second each).
    Returns True on success, False on timeout.
    Updates state["wifi_connected"] and state["wifi_ssid"] accordingly.
    """
    wlan = network.WLAN(network.STA_IF)  # STA_IF = station (client) mode
    wlan.active(True)                    # Power on the WiFi radio
    if wlan.isconnected():
        # Disconnect first so we can attempt the new network cleanly
        wlan.disconnect()
        time.sleep(1)
    _draw_boot_msg("Connecting to\n{}...".format(ssid))
    wlan.connect(ssid, password)
    for _ in range(10):          # Try for up to 10 seconds
        if wlan.isconnected():
            state["wifi_connected"] = True
            state["wifi_ssid"]      = ssid
            _draw_boot_msg("Connected!")
            time.sleep(1)
            return True
        time.sleep(1)
    # If we exit the loop without connecting, mark as offline
    state["wifi_connected"] = False
    state["wifi_ssid"]      = ""
    return False

def connect_wifi():
    """
    Try each network in KNOWN_NETWORKS in order.
    Returns True as soon as one succeeds.
    Falls back to offline mode if all fail.
    """
    for ssid, password in KNOWN_NETWORKS:
        if connect_wifi_network(ssid, password):
            return True
    _draw_boot_msg("No WiFi - offline")
    time.sleep(2)
    return False

# ============================================================
# DISPLAY — helpers
# ============================================================

def _draw_boot_msg(msg):
    """
    Clear the screen and show a single status message.
    Used during boot and WiFi connection attempts.
    """
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(msg, 10, 100, COLOR_ACCENT)

def _cx(text, char_w, offset=0):
    """
    Calculate the x-coordinate needed to horizontally centre `text`.
    char_w — approximate pixel width of one character for the current font.
    offset — fine-tune adjustment (compensates for font kerning).
    """
    return max(0, (SCREEN_W - len(text) * char_w) // 2 + offset)

def _draw_header():
    """
    Draws the top title bar and a horizontal divider line below it.
    Called by every full-screen draw function.
    """
    lcd.font(lcd.FONT_DejaVu18)
    header = "- FOCUS TRACKER -"
    lcd.print(header, _cx(header, 11, -4), 10, COLOR_ACCENT)
    lcd.line(0, 32, SCREEN_W, 32, COLOR_DIVIDER)

def _draw_wifi_indicator():
    """
    Draws the WiFi status label at the bottom of the screen.
    FIX Bug 2: moved from y=208/225 to y=220/236 so it no longer
    overlaps the bottom bar divider at y=190 and button labels at y=196.
    """
    lcd.font(lcd.FONT_DejaVu18)
    if state["wifi_connected"]:
        # "WiFi OK" in dim blue — online and happy
        lcd.print("WiFi OK",  _cx("WiFi OK",  11, -4), 220, COLOR_WIFI)
    else:
        # "No WiFi" in red — we are offline
        lcd.print("No WiFi",  _cx("No WiFi",  11, -4), 220, COLOR_BAD)
    # Secondary hint: user can press BtnB to change network
    lcd.print("[change]", _cx("[change]", 11, -4), 236, COLOR_GREY_DIM)

def _draw_bottom_bar(left_text, right_text, left_color, right_color):
    """
    Draws the two-button hint bar at y=190–206.
    A divider line separates it from the main content area.
    left_text  → BtnA action hint
    right_text → RFID action hint (tap to end)
    """
    lcd.line(0, 190, SCREEN_W, 190, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(left_text,  12,  196, left_color)
    lcd.print(right_text, 168, 196, right_color)

def _draw_time_zone(work_str):
    """
    Redraws only the time display rectangle (y=134 to y=174).
    fillRect() erases the old value before printing the new one —
    this avoids text ghosting without clearing the whole screen.
    """
    lcd.fillRect(0, 134, SCREEN_W, 40, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print(work_str, _cx(work_str, 15, -4), 138, COLOR_WHITE)

# ============================================================
# DISPLAY — full screen draws
# ============================================================

def draw_idle_screen():
    """
    Shown when no session is active.
    Big "TAP TO / START" prompt invites the user to badge in.
    """
    lcd.clear(COLOR_BG)
    _draw_header()
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("TAP TO", _cx("TAP TO", 26, -6), 72, COLOR_GREY_SOFT)
    lcd.font(lcd.FONT_DejaVu56)
    lcd.print("START", _cx("START", 34, -8), 130, COLOR_ACCENT)
    _draw_wifi_indicator()
    _update_last_drawn()

def draw_session_screen():
    """
    Shown during an active session (working or paused).
    Displays the status word, the elapsed work timer, and button hints.
    FIX Bug 5: called immediately on pause/resume so the time zone
    always shows the correct accumulated seconds after a full redraw.
    """
    lcd.clear(COLOR_BG)
    _draw_header()
    # Choose status text and colour based on paused flag
    if state["session_paused"]:
        status_text, status_color = "PAUSED",  COLOR_WARN
    else:
        status_text, status_color = "WORKING", COLOR_GOOD
    lcd.font(lcd.FONT_DejaVu56)
    lcd.print(status_text, _cx(status_text, 34, -12), 64, status_color)
    # Draw the time zone with the current accumulated seconds
    _draw_time_zone(format_seconds(state["work_seconds"]))
    # Button hints differ by pause state
    if state["session_paused"]:
        _draw_bottom_bar("RESUME", "TAP TO END", COLOR_WARN, COLOR_GREY_DIM)
    else:
        _draw_bottom_bar("PAUSE",  "TAP TO END", COLOR_WARN, COLOR_GREY_DIM)
    _draw_wifi_indicator()
    _update_last_drawn()

def draw_time_only():
    """
    Lightweight redraw — updates ONLY the time zone rectangle.
    Called every second when the session is active and nothing else changed.
    Avoids the cost of a full lcd.clear() on every tick.
    """
    _draw_time_zone(format_seconds(state["work_seconds"]))
    _last_drawn["work_seconds"] = state["work_seconds"]

def draw_error_screen(message, duration=4):
    """
    Briefly shows an error message (e.g., wrong card tapped),
    then restores the appropriate screen automatically.
    """
    lcd.clear(COLOR_BG)
    _draw_header()
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(message, _cx(message, 11, -4), 100, COLOR_BAD)
    time.sleep(duration)
    # After the error clears, return to whichever screen is appropriate
    draw_session_screen() if state["session_active"] else draw_idle_screen()

def draw_wifi_screen():
    """
    Shows the WiFi selection overlay.
    BtnA → connect to KNOWN_NETWORKS[0]
    BtnC → connect to KNOWN_NETWORKS[1]
    BtnB → cancel and return to main screen
    FIX Bug 3: this is now just a draw function — the main loop
    handles the buttons without blocking (no `continue`).
    """
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("- WiFi Setup -", _cx("- WiFi Setup -", 11, -4), 10, COLOR_ACCENT)
    lcd.line(0, 32, SCREEN_W, 32, COLOR_DIVIDER)
    # Show the two available networks with their assigned button
    lcd.print("BtnA:", 10, 60, COLOR_GREY_SOFT)
    lcd.print(KNOWN_NETWORKS[0][0], 80, 60, COLOR_WHITE)
    lcd.print("BtnC:", 10, 95, COLOR_GREY_SOFT)
    lcd.print(KNOWN_NETWORKS[1][0], 80, 95, COLOR_WHITE)
    lcd.line(0, 130, SCREEN_W, 130, COLOR_DIVIDER)
    # BtnB cancels — clear instruction for the user
    lcd.print("BtnB: back to main", _cx("BtnB: back to main", 11, -4), 140, COLOR_GREY_DIM)
    # Show currently connected network if any
    if state["wifi_connected"]:
        current = "Now: {}".format(state["wifi_ssid"])
        lcd.print(current, _cx(current, 11, -4), 175, COLOR_WIFI)

# ============================================================
# DISPLAY — utilities
# ============================================================

def format_seconds(seconds):
    """
    Converts a raw second count into a human-readable string.
    Examples: 0 → "0s", 90 → "1m 30s", 3661 → "1h 1m 1s"
    Uses integer arithmetic only (no float) — MicroPython friendly.
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
    """
    Snapshot current state into _last_drawn after every full redraw.
    This is the 'previous frame' that _status_changed() compares against.
    """
    _last_drawn["session_active"] = state["session_active"]
    _last_drawn["session_paused"] = state["session_paused"]
    _last_drawn["wifi_connected"] = state["wifi_connected"]
    _last_drawn["work_seconds"]   = state["work_seconds"]

def _status_changed():
    """
    Returns True if any major state value differs from what was last drawn.
    A True result triggers a full draw_session_screen() / draw_idle_screen().
    """
    return (
        state["session_active"] != _last_drawn["session_active"] or
        state["session_paused"] != _last_drawn["session_paused"] or
        state["wifi_connected"] != _last_drawn["wifi_connected"]
    )

def _time_changed():
    """
    Returns True if work_seconds has advanced since the last draw.
    Used to trigger a lightweight draw_time_only() redraw each second.
    """
    return state["work_seconds"] != _last_drawn["work_seconds"]

# ============================================================
# RFID
# ============================================================

def read_rfid():
    """
    Polls the RFID reader for a card.
    De-duplication logic: returns a card UID only on a FRESH tap —
    i.e., the card must have been absent (isCardOn() == False) before
    this reading. This prevents one long tap from firing multiple events.
    Returns the UID string, or None if no new card is detected.
    """
    try:
        if rfid.isCardOn():
            card_id = str(rfid.readUid())
            # Only fire if this UID is different from the last seen one
            if card_id != state.get("last_raw_card"):
                state["last_raw_card"] = card_id
                return card_id
        else:
            # Card has been removed — reset so the next tap fires correctly
            state["last_raw_card"] = None
    except Exception as e:
        print("[RFID] Read failed:", e)
    return None

def handle_rfid(card_id):
    """
    Decides whether a card tap starts or ends the session:
    - No active session   → start a new session for this card
    - Active session + same card → end the session
    - Active session + different card → show error, do nothing
    Local state is updated immediately so the UI responds without waiting
    for the next fetch_session() poll.
    """
    if not state["session_active"]:
        # Start a new session
        post_session_event("start", card_id)
        state["session_active"] = True
        state["session_paused"] = False
        state["work_seconds"]   = 0       # Reset local timer
        state["active_card_id"] = card_id
        print("[RFID] Session started:", card_id)
    else:
        if card_id != state["active_card_id"]:
            # Someone else's card — reject with a visual warning
            print("[RFID] Wrong card:", card_id)
            draw_error_screen("Wrong card!", duration=3)
            return
        # Same card again → end the session
        post_session_event("end", card_id)
        state["session_active"] = False
        state["session_paused"] = False
        state["work_seconds"]   = 0       # Reset local timer
        state["active_card_id"] = None
        print("[RFID] Session ended:", card_id)

# ============================================================
# BUTTONS
# ============================================================

def handle_buttons():
    """
    Processes physical button presses each loop iteration.

    FIX Bug 3 — WiFi screen buttons are handled HERE (not in a separate
    blocking sub-loop with `continue`). The main loop no longer calls
    `continue` when screen == "wifi", so the timer keeps incrementing.

    FIX Bug 4 — After any BtnA press we record state["last_btn_press"].
    fetch_session() checks this timestamp and skips overwriting
    session_paused for BTN_COOLDOWN seconds after a press.

    FIX Bug 5 — draw_session_screen() is called immediately after
    toggling session_paused so the time zone shows the correct value.
    """
    # --- WiFi screen buttons ---
    if state["screen"] == "wifi":
        if btnA.wasPressed():
            # Connect to the first known network
            ssid, pwd = KNOWN_NETWORKS[0]
            connect_wifi_network(ssid, pwd)
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        elif btnC.wasPressed():
            # Connect to the second known network
            ssid, pwd = KNOWN_NETWORKS[1]
            connect_wifi_network(ssid, pwd)
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        elif btnB.wasPressed():
            # Cancel — go back without changing network
            state["screen"] = "main"
            draw_session_screen() if state["session_active"] else draw_idle_screen()
        # In WiFi screen mode we skip session buttons (return early)
        return

    # --- Main screen buttons ---
    if btnA.wasPressed():
        if not state["session_active"]:
            return   # BtnA does nothing without an active session
        # Record the button press timestamp for the fetch cooldown (Bug 4 fix)
        state["last_btn_press"] = time.time()
        if state["session_paused"]:
            post_session_event("resume", None)
            state["session_paused"] = False
        else:
            post_session_event("pause", None)
            state["session_paused"] = True
        # FIX Bug 5: force an immediate full redraw so the time zone
        # shows the accumulated seconds right after pause/resume toggle.
        draw_session_screen()

    if btnB.wasPressed():
        # Switch to the WiFi selection overlay
        state["screen"] = "wifi"
        draw_wifi_screen()

# ============================================================
# DATA — posting and fetching
# ============================================================

def post_session_event(event_type, card_id):
    """
    Sends a POST request to the middleware for a session lifecycle event.
    event_type: "start" | "pause" | "resume" | "end"
    card_id: the RFID UID string (None for pause/resume)
    urequests has no `timeout` parameter in MicroPython — we rely on
    the server responding promptly.
    gc.collect() is called after every network operation to reclaim memory.
    """
    payload = {"event": event_type, "card_id": card_id}
    try:
        r = urequests.post(
            MIDDLEWARE_URL + "/session/{}".format(event_type),
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload)
        )
        r.close()   # Always close the response to free the socket
        print("[SESSION] Posted:", event_type)
    except Exception as e:
        print("[SESSION] Post failed:", e)
    gc.collect()

def fetch_session(boot_sync=False):
    """
    GETs /session/current from the middleware to sync remote state.

    FIX Bug 1:
    - work_seconds is NEVER overwritten from the server during normal operation.
      The device tracks elapsed time locally in the main loop.
    - Exception: if boot_sync=True (called once at startup) we DO sync
      work_seconds so the device starts from the server's known value.

    FIX Bug 4:
    - session_paused is only overwritten from the server if more than
      BTN_COOLDOWN seconds have passed since the last button press.
      This prevents the server's stale state from un-doing a local toggle.
    """
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current")
        if r.status_code == 200:
            data = ujson.loads(r.text)

            # Always sync session_active — safe, user can't toggle this with a button
            state["session_active"] = data.get("active", False)

            # FIX Bug 4 — only sync paused state if we are outside the cooldown window
            now = time.time()
            cooldown_elapsed = (now - state["last_btn_press"]) >= BTN_COOLDOWN
            if cooldown_elapsed:
                state["session_paused"] = data.get("paused", False)

            # FIX Bug 1 — only overwrite work_seconds on boot, not during normal loop
            if boot_sync:
                state["work_seconds"] = data.get("work_seconds", 0)
                print("[SESSION] Boot sync — work_seconds:", state["work_seconds"])

        r.close()
    except Exception as e:
        print("[SESSION] Fetch failed:", e)
    gc.collect()

# ============================================================
# BOOT
# ============================================================

def boot():
    """
    Runs once at startup:
    1. Show a boot splash
    2. Connect to WiFi (tries each KNOWN_NETWORK in order)
    3. Sync session state from middleware (including work_seconds — boot_sync=True)
    4. Draw the correct initial screen
    This satisfies the academic requirement: device re-syncs with the cloud
    on every restart, so it never starts blank even after a power cut.
    """
    _draw_boot_msg("Booting...")
    time.sleep(1)
    connect_wifi()
    if state["wifi_connected"]:
        fetch_session(boot_sync=True)   # Full sync including work_seconds on boot
    draw_session_screen() if state["session_active"] else draw_idle_screen()
    print("[BOOT] Ready.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    """
    The main event loop — runs forever after boot().

    Structure each iteration (approximately 1 second):
    1. handle_buttons() — check all button presses (includes WiFi screen)
    2. read_rfid() — check for badge taps (skipped in WiFi screen mode)
    3. Periodically poll middleware with fetch_session()
    4. Increment work_seconds locally if session is active and not paused
    5. Redraw only what changed — full redraw if status changed,
       lightweight time redraw if only seconds changed

    FIX Bug 3: removed the `if state["screen"] == "wifi": continue` block.
    Button handling for WiFi screen is now inside handle_buttons().
    The timer increments regardless of which screen is shown.
    """
    last_session_poll = 0   # Timestamp of the last fetch_session() call

    while True:
        now = time.time()

        # --- Step 1: handle button presses (works for both screens) ---
        handle_buttons()

        # --- Step 2: check RFID only when on the main screen ---
        # We don't want a badge tap to start a session while the user
        # is navigating the WiFi menu.
        if state["screen"] == "main":
            card_id = read_rfid()
            if card_id:
                handle_rfid(card_id)

        # --- Step 3: periodic server sync ---
        # FIX Bug 1 — fetch_session() no longer overwrites work_seconds
        if now - last_session_poll >= SESSION_POLL_INTERVAL:
            if state["wifi_connected"]:
                fetch_session(boot_sync=False)  # Normal poll — never syncs work_seconds
            last_session_poll = now

        # --- Step 4: increment local work timer ---
        # Only counts up when a session is active AND not paused.
        # This is the sole source of truth for work_seconds (Bug 1 fix).
        if state["session_active"] and not state["session_paused"]:
            state["work_seconds"] = (state["work_seconds"] or 0) + 1

        # --- Step 5: smart redraw ---
        # Only redraw the main screen if we are currently showing it.
        # While the WiFi screen is visible, we skip main-screen redraws.
        if state["screen"] == "main":
            if _status_changed():
                # Major state change (active/paused/wifi) → full redraw
                draw_session_screen() if state["session_active"] else draw_idle_screen()
            elif state["session_active"] and _time_changed():
                # Only the seconds counter changed → cheap partial redraw
                draw_time_only()

        # --- Housekeeping ---
        gc.collect()         # Free memory — important on MicroPython
        time.sleep(1)        # 1-second tick — gives the loop a stable heartbeat

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()