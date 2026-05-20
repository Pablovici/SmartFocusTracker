# device_a/main3.py — UX prototype v6  Simulated Liquid Glass
#
# Glass simulation: card color = lerp(background_color, white, 0.5)
# Since we draw the background ourselves, we pre-compute the blend.
# Result is visually identical to real alpha compositing.
# Text: DARK on light glass (iOS style), vivid accent for data values.
#
# Touch via FT6336U I2C direct (confirmed working).

import time
import gc
from machine import I2C, Pin
from m5stack import lcd, btnA, btnB, btnC

# ============================================================
# FAKE DATA
# ============================================================
FAKE = {
    "time":      "14:32",
    "wifi_ssid": "iot-unil",
    "wifi_ok":   True,
    "battery":   72,
    "w_temp":    18,
    "w_cond":    "Cloudy",
    "i_temp":    21.3,
    "i_hum":     48,
    "air":       "Good",
    "session":   True,
    "s_status":  "Active",
    "co2":       742,
    "tvoc":      12,
}

# ============================================================
# PALETTE
# Background: rich indigo.  Glass: lerp(BG, white, 0.5)
#
# BG_TOP  = 0x1C2E82 → glass_top  = lerp(0x1C2E82, 0xFFFFFF, 0.5) = 0x8D96C0
# BG_MID  = 0x142070 → glass_mid  = lerp(0x142070, 0xFFFFFF, 0.5) = 0x8990B7
# border  = lerp(0x1C2E82, 0xFFFFFF, 0.82) = 0xD0D5EE   (brighter edge)
# highlight = lerp(0x1C2E82, 0xFFFFFF, 0.92) = 0xEAECF7  (near-white top strip)
# ============================================================

# Backgrounds (drawn as 3-band gradient)
C_BG1 = 0x1D4883
C_BG2 = 0x173765
C_BG3 = 0x102746

# Frosted glass — Claude Design palette
C_GLASS   = 0x8EA4C1   # card fill
C_GLASS_B = 0xCDD7E4   # border — bright edge (light on glass rim)
C_GLASS_H = 0xEDF0F5   # top 2px highlight — near-white

# Control center
C_CC_BG   = 0x102748   # darker panel overlay
C_CC_TILE = 0x838FA0   # tile glass

# Separators
C_SEP     = 0x2A4A70

# Text ON glass — dark for iOS feel
C_TXT1    = 0x0C1E36   # primary on glass
C_TXT2    = 0x233E65   # secondary on glass
C_TXT3    = 0x4B6D9C   # tertiary / tag on glass

# Text on dark background (status bar, CC bottom text)
C_L1      = 0xFFFFFF
C_L2      = 0xA8C0E0
C_L3      = 0x5070A0

# Vivid accents (on glass — dark saturated)
C_BLUE    = 0x0493F8
C_GREEN   = 0x089744
C_AMBER   = 0xE77706
C_TEAL    = 0x007A90
C_LAVEND  = 0x9333F2
C_GOLD    = 0xAA8800
C_CORAL   = 0xCC2A38

# Lighter versions for status bar / CC (on dark bg)
C_BLUE_L   = 0x65BFFF
C_GREEN_L  = 0x48F38F
C_AMBER_L  = 0xFFAD5B
C_LAVEND_L = 0xC895FB

def wcol(cond):
    c = cond.lower()
    if "thunder" in c or "storm" in c: return C_CORAL
    if "snow"    in c:                 return C_TXT2
    if "rain"    in c or "shower" in c:return C_BLUE
    if "clear"   in c or "sun"    in c:return C_GOLD
    if "cloud"   in c:                 return C_TXT3
    return C_TXT1

def _wfr(cond):
    """French translation for weather condition."""
    c = cond.lower()
    if "cloud" in c:                   return "Nuageux"
    if "clear" in c or "sun" in c:     return "Ensoleille"
    if "rain"  in c or "shower" in c:  return "Pluie"
    if "snow"  in c:                   return "Neige"
    if "thunder" in c or "storm" in c: return "Orage"
    return cond

DEG = chr(176)  # degree symbol °

# ============================================================
# TOUCH — FT6336U I2C direct
# ============================================================
try:
    _i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
except:
    _i2c = None

def read_xy():
    if _i2c is None: return None
    try:
        d = _i2c.readfrom_mem(0x38, 0x02, 5)
        if d[0] & 0x0F == 0: return None
        x = ((d[1] & 0x0F) << 8) | d[2]
        y = ((d[3] & 0x0F) << 8) | d[4]
        return (x, y)
    except: return None

# ============================================================
# STATE
# ============================================================
screen     = 0
panel_open = False
t_start    = None
t_done     = False

# ============================================================
# HELPERS
# ============================================================
def _cx(text, fw, x, w):
    return x + max(0, (w - len(text) * fw) // 2)

def _bold(text, x, y, col):
    """Simulated bold: print twice with 1px x-offset."""
    lcd.print(text, x,     y, col)
    lcd.print(text, x + 1, y, col)

def _draw_bg():
    """Rich indigo 3-band gradient — gives depth for the glass to float over."""
    lcd.fillRect(0,   0, 320,  80, C_BG1)
    lcd.fillRect(0,  80, 320,  80, C_BG2)
    lcd.fillRect(0, 160, 320,  80, C_BG3)

# ============================================================
# STATUS BAR  (on dark BG → light text)
# ============================================================
def _wifi_bars(x, y, ok):
    for i in range(4):
        h = 3 + i * 3
        lcd.fillRect(x + i * 5, y - h, 3, h, C_L1 if (ok and i < 3) else C_L3)

def _batt(x, y, pct):
    col = C_GREEN_L if pct > 30 else C_AMBER_L if pct > 10 else C_CORAL
    lcd.drawRect(x, y, 22, 11, C_L2)
    lcd.fillRect(x + 22, y + 3, 2, 5, C_L2)
    fw = max(0, min(18, pct * 18 // 100))
    if fw: lcd.fillRect(x + 2, y + 2, fw, 7, col)

def draw_statusbar():
    lcd.fillRect(0, 0, 320, 26, C_BG1)
    lcd.fillRect(0, 26, 320, 1, C_SEP)
    lcd.font(lcd.FONT_Default)
    t  = FAKE["time"]
    lcd.print(t, _cx(t, 6, 0, 320), 9, C_L1)
    _wifi_bars(10, 21, FAKE["wifi_ok"])
    ssid = FAKE["wifi_ssid"] if FAKE["wifi_ok"] else "No WiFi"
    lcd.print(ssid[:10], 34, 9, C_L2 if FAKE["wifi_ok"] else C_CORAL)
    lcd.print("{}%".format(FAKE["battery"]), 242, 9, C_L3)
    _batt(272, 8, FAKE["battery"])

# ============================================================
# GLASS CARD BASE (used by detail screens)
# ============================================================
def _card_base(x, y, w, h):
    lcd.fillRoundRect(x, y, w, h, 10, C_GLASS)
    lcd.drawRoundRect(x, y, w, h, 10, C_GLASS_B)
    lcd.fillRect(x + 5, y + 1, w - 10, 2, C_GLASS_H)

def _tag(x, y, text):
    lcd.font(lcd.FONT_Default)
    _bold(text, x + 8, y + 8, C_TXT2)

# ============================================================
# HOME SCREEN — custom layout per card (matches mockup)
# ============================================================
CX1, CX2 = 5, 163
CY1, CY2 = 30, 135
CW,  CH  = 152, 102

def _home_outdoor(x, y, w, h):
    _card_base(x, y, w, h)
    _tag(x, y, "OUTDOOR")
    col = wcol(FAKE["w_cond"])
    # City
    lcd.font(lcd.FONT_Default)
    lcd.print("Lausanne", x + 8, y + 24, C_TXT2)
    # Temperature large
    lcd.font(lcd.FONT_DejaVu24)
    temp_str = "{}{}".format(FAKE["w_temp"], DEG)
    lcd.print(temp_str, x + 8, y + 40, C_TXT1)
    # Weather icon dot (colored circle)
    lcd.fillCircle(x + 8 + len(temp_str) * 14 + 10, y + 52, 6, col)
    # Condition
    lcd.font(lcd.FONT_Default)
    lcd.print(_wfr(FAKE["w_cond"]), x + 8, y + 74, C_TXT3)

def _home_indoor(x, y, w, h):
    _card_base(x, y, w, h)
    _tag(x, y, "INDOOR")
    # Temperature large
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{}{}".format(int(FAKE["i_temp"]), DEG), x + 8, y + 24, C_TXT1)
    # Humidity with blue drop dot
    lcd.fillCircle(x + 10, y + 65, 5, C_BLUE)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("{}%".format(FAKE["i_hum"]), x + 22, y + 56, C_TXT2)

def _home_session(x, y, w, h):
    _card_base(x, y, w, h)
    _tag(x, y, "SESSION")
    if FAKE["session"]:
        s    = FAKE["s_status"]
        scol = C_GREEN if s == "Active" else C_AMBER if s == "Paused" else C_TXT3
        # Pill badge: border + bullet dot + label
        bw = len(s) * 11 + 34
        bx = x + 8; by = y + 40
        lcd.drawRoundRect(bx, by, bw, 26, 8, scol)
        lcd.fillCircle(bx + 12, by + 13, 4, scol)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print(s, bx + 22, by + 4, scol)
    else:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("Idle", x + 8, y + 46, C_TXT3)

def _home_voice(x, y, w, h):
    _card_base(x, y, w, h)
    _tag(x, y, "VOICE")
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Ask anything...", x + 8, y + 46, C_TXT1)
    # Underline accent bar
    lcd.fillRoundRect(x + 8, y + 72, w - 24, 3, 1, C_LAVEND)

def draw_home():
    _draw_bg()
    draw_statusbar()
    _home_outdoor(CX1, CY1, CW, CH)
    _home_indoor(CX2, CY1, CW, CH)
    _home_session(CX1, CY2, CW, CH)
    _home_voice(CX2, CY2, CW, CH)
    # iOS swipe-down pill handle
    lcd.fillRoundRect(140, 237, 40, 3, 1, C_GLASS_B)

# ============================================================
# DETAIL SCREENS
# ============================================================
def _detail_top(back, title, accent):
    _draw_bg()
    draw_statusbar()
    # Nav bar — glass panel
    lcd.fillRect(0, 26, 320, 32, C_GLASS)
    lcd.fillRect(0, 57, 320, 1, C_GLASS_B)
    lcd.font(lcd.FONT_Default)
    _bold("< {}".format(back), 10, 36, C_TXT1)
    lcd.font(lcd.FONT_DejaVu18)
    tw = len(title) * 11
    lcd.print(title, (320 - tw) // 2, 32, accent)

def _detail_row(x, y, label, val, vcol):
    lcd.font(lcd.FONT_Default)
    lcd.print(label, x, y, C_L2)
    vx = 312 - len(val) * 6
    lcd.print(val, vx, y, vcol)
    lcd.fillRect(x, y + 14, 296, 1, C_SEP)

def draw_weather():
    _detail_top("Home", "Outdoor", wcol(FAKE["w_cond"]))
    col = wcol(FAKE["w_cond"])
    _card_base(12, 64, 296, 100)
    lcd.font(lcd.FONT_Default)
    lcd.print("Lausanne", 24, 72, C_TXT3)
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("{}{}".format(FAKE["w_temp"], DEG), 24, 86, col)
    lcd.fillCircle(24 + len(str(FAKE["w_temp"])) * 24 + 30, 107, 8, col)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(_wfr(FAKE["w_cond"]), 24, 132, C_TXT2)
    lcd.fillRect(12, 172, 296, 1, C_SEP)
    lcd.font(lcd.FONT_Default)
    lcd.print("Forecast  coming soon", 20, 182, C_L3)

def draw_sensors():
    _detail_top("Home", "Indoor", C_TEAL)
    _card_base(12, 64, 296, 100)
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("{}{}".format(int(FAKE["i_temp"]), DEG), 20, 76, C_TXT1)
    lcd.fillCircle(190, 107, 8, C_BLUE)
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{}%".format(FAKE["i_hum"]), 206, 92, C_TXT2)
    acol_l = C_GREEN_L if FAKE["air"] == "Good" else C_AMBER_L
    _detail_row(20, 172, "CO2",  "{} ppm".format(FAKE["co2"]),  acol_l)
    _detail_row(20, 192, "TVOC", "{} ppb".format(FAKE["tvoc"]), C_L2)
    _detail_row(20, 212, "Air",  FAKE["air"],                    acol_l)

def draw_session():
    _detail_top("Home", "Session", C_GREEN_L)
    _card_base(12, 64, 296, 100)
    if FAKE["session"]:
        s    = FAKE["s_status"]
        scol = C_GREEN if s == "Active" else C_AMBER if s == "Paused" else C_TXT3
        bw = len(s) * 11 + 34
        lcd.drawRoundRect(24, 82, bw, 34, 10, scol)
        lcd.fillCircle(38, 99, 5, scol)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print(s, 50, 89, scol)
    else:
        lcd.font(lcd.FONT_DejaVu24)
        lcd.print("No session", 30, 100, C_TXT3)

def draw_voice():
    _detail_top("Home", "Voice", C_LAVEND_L)
    _card_base(12, 64, 296, 100)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Press B to speak", _cx("Press B to speak", 11, 12, 296), 96, C_LAVEND)
    lcd.fillRoundRect(20, 126, 272, 3, 1, C_LAVEND)
    lcd.font(lcd.FONT_Default)
    lcd.print("Voice pipeline active",
              _cx("Voice pipeline active", 6, 12, 296), 138, C_TXT3)

# ============================================================
# CONTROL CENTER — darker panel, same glass tiles
# ============================================================
def draw_panel():
    lcd.fillRect(0, 0, 320, 204, C_CC_BG)
    # Handle pill
    lcd.fillRoundRect(140, 7, 40, 4, 2, C_GLASS_B)
    lcd.fillRect(0, 16, 320, 1, C_SEP)
    # Status row: "wifi · iot-unil"  +  "72% [====]"
    lcd.font(lcd.FONT_Default)
    status_str = "wifi  {}  {}".format(chr(183), FAKE["wifi_ssid"])
    lcd.print(status_str, 12, 26, C_L1)
    pct_str = "{}%".format(FAKE["battery"])
    lcd.print(pct_str, 248, 26, C_L3)
    _batt(278, 25, FAKE["battery"])
    lcd.fillRect(0, 42, 320, 1, C_SEP)
    # 3 glass tiles with icons
    _cc_tile(8,   50, 96, 80, "WiFi",     C_BLUE_L,  "wifi")
    _cc_tile(112, 50, 96, 80, "Sensors",  C_AMBER_L, "sensors")
    _cc_tile(216, 50, 96, 80, "Settings", C_L2,      "settings")
    lcd.fillRect(0, 138, 320, 1, C_SEP)
    comfort = "Good environment" if FAKE["air"] == "Good" else "Air getting stale"
    ccol    = C_GREEN_L if FAKE["air"] == "Good" else C_AMBER_L
    lcd.font(lcd.FONT_Default)
    lcd.print(comfort, _cx(comfort, 6, 0, 320), 150, ccol)
    lcd.fillRect(0, 168, 320, 1, C_SEP)
    hint = "Swipe up  or  [A] to close"
    lcd.print(hint, _cx(hint, 6, 0, 320), 180, C_L3)
    lcd.fillRect(0, 203, 320, 1, C_GLASS_B)

def _cc_tile(x, y, w, h, label, col, icon):
    # Glass tile
    lcd.fillRoundRect(x, y, w, h, 12, C_CC_TILE)
    lcd.drawRoundRect(x, y, w, h, 12, C_GLASS_B)
    lcd.fillRect(x + 5, y + 1, w - 10, 2, C_GLASS_H)
    cx = x + w // 2
    cy = y + 30
    # Icon drawn as simple shapes
    if icon == "wifi":
        # Triangle (signal/wifi arrow up)
        lcd.line(cx, cy - 12, cx - 10, cy + 6, col)
        lcd.line(cx, cy - 12, cx + 10, cy + 6, col)
        lcd.line(cx - 10, cy + 6, cx + 10, cy + 6, col)
        lcd.line(cx - 5,  cy + 1, cx + 5,  cy + 1, col)
    elif icon == "sensors":
        # Concentric circles (target)
        lcd.drawRoundRect(cx - 10, cy - 10, 20, 20, 10, col)
        lcd.fillCircle(cx, cy, 4, col)
    elif icon == "settings":
        # Gear approximation: circle + 4 teeth
        lcd.drawRoundRect(cx - 8, cy - 8, 16, 16, 8, col)
        lcd.fillRect(cx - 2, cy - 12, 4, 5, col)
        lcd.fillRect(cx - 2, cy + 7,  4, 5, col)
        lcd.fillRect(cx - 12, cy - 2, 5, 4, col)
        lcd.fillRect(cx + 7,  cy - 2, 5, 4, col)
    # Label
    lcd.font(lcd.FONT_Default)
    lw = len(label) * 6
    lcd.print(label, cx - lw // 2, y + 58, col)

# ============================================================
# TOUCH HANDLER
# ============================================================
SWIPE_DOWN = 35
SWIPE_UP   = 30

def handle_touch():
    global screen, panel_open, t_start, t_done
    xy = read_xy()
    if xy:
        x, y = xy
        if t_start is None:
            t_start = (x, y); t_done = False
        if not t_done:
            dy = y - t_start[1]
            if not panel_open and dy >= SWIPE_DOWN:
                t_done = True; t_start = None
                panel_open = True; draw_panel()
            elif panel_open and dy <= -SWIPE_UP:
                t_done = True; t_start = None
                panel_open = False; _redraw()
    else:
        if t_start is not None and not t_done:
            sx, sy = t_start
            if panel_open:
                if 48 <= sy <= 130:
                    if   8   <= sx <= 104: _panel_action("wifi")
                    elif 112 <= sx <= 208: _panel_action("sensors")
                    elif 216 <= sx <= 312: _panel_action("settings")
                    else: panel_open = False; _redraw()
                else:
                    panel_open = False; _redraw()
            elif screen == 0:
                mid_x = 160; mid_y = 134
                screen = (1 if sx < mid_x else 2) if sy < mid_y else (3 if sx < mid_x else 4)
                _redraw()
            elif screen in (1, 2, 3, 4):
                screen = 0; _redraw()
        t_start = None; t_done = False

def _panel_action(action):
    global panel_open, screen
    panel_open = False
    if   action == "wifi":     screen = 5
    elif action == "sensors":  screen = 6
    elif action == "settings": screen = 7
    _redraw()

def _redraw():
    if   screen == 0: draw_home()
    elif screen == 1: draw_weather()
    elif screen == 2: draw_sensors()
    elif screen == 3: draw_session()
    elif screen == 4: draw_voice()
    else:
        labels  = {5: "WiFi", 6: "Sensors", 7: "Settings"}
        accents = {5: C_BLUE_L, 6: C_AMBER_L, 7: C_L2}
        _detail_top("Home", labels.get(screen, "?"), accents.get(screen, C_L1))
        lcd.font(lcd.FONT_Default)
        lcd.print("Coming soon", _cx("Coming soon", 6, 0, 320), 130, C_L3)

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    global screen, panel_open, t_start, t_done
    draw_home()
    while True:
        handle_touch()
        if btnA.wasPressed():
            t_start = None; t_done = False
            if panel_open or screen != 0:
                panel_open = False; screen = 0; _redraw()
        if btnB.wasPressed() and screen == 4:
            t_start = None; t_done = False
            lcd.font(lcd.FONT_Default)
            lcd.print("Listening...", _cx("Listening...", 6, 0, 320), 176, C_BLUE_L)
        if btnC.wasPressed():
            t_start = None; t_done = False
            panel_open = True; draw_panel()
        gc.collect()
        time.sleep_ms(20)

main()
