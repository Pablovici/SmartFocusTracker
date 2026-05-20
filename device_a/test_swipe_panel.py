# device_a/test_swipe_panel.py  v9 — I2C direct FT6336U
# Touch via I2C(0, scl=22, sda=21) addr=0x38, registre 0x02

import time
import gc
from m5stack import lcd, btnA
from machine import I2C, Pin

COLOR_BG    = 0x1a1a2e
COLOR_WHITE = 0xFFFFFF
COLOR_GREY  = 0xAAAAAA
COLOR_ACCENT= 0x00BCD4
COLOR_GOOD  = 0x00FF00
COLOR_WARN  = 0xFFAA00
COLOR_BAD   = 0xFF0000
COLOR_PANEL = 0x0a0a18

SWIPE_DOWN = 35
SWIPE_UP   = 30

# I2C direct vers FT6336U
_i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)

def read_xy():
    """Retourne (x,y) si touché, None sinon (n=0)."""
    try:
        data = _i2c.readfrom_mem(0x38, 0x02, 5)
        n = data[0] & 0x0F
        if n == 0:
            return None
        x = ((data[1] & 0x0F) << 8) | data[2]
        y = ((data[3] & 0x0F) << 8) | data[4]
        return (x, y)
    except:
        return None

panel_open   = False
swipe_start  = None
gesture_done = False

def draw_main():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Swipe DOWN to open", 58, 30, COLOR_ACCENT)
    lcd.font(lcd.FONT_Default)
    lcd.print("Le point rouge suit le doigt", 44, 60, COLOR_GREY)
    lcd.line(0, 78, 320, 78, 0x333355)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Main Screen", 95, 120, COLOR_WHITE)
    lcd.fillRect(0, 210, 320, 30, 0x111122)
    lcd.print("[A] Ouvrir panel", 85, 218, COLOR_ACCENT)

def draw_panel():
    lcd.fillRect(0, 0, 320, 185, COLOR_PANEL)
    lcd.line(0, 185, 320, 185, COLOR_ACCENT)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Control Center", 72, 10, COLOR_ACCENT)
    lcd.line(0, 34, 320, 34, 0x333355)
    for i, (label, col) in enumerate([
        ("WiFi",     COLOR_GOOD),
        ("Voice",    COLOR_ACCENT),
        ("Forecast", COLOR_WARN),
        ("Settings", COLOR_GREY),
    ]):
        x = 10 + i * 78
        lcd.fillRect(x, 44, 70, 60, 0x101828)
        lcd.line(x, 44, x + 70, 44, col)
        lcd.font(lcd.FONT_Default)
        tw = len(label) * 6
        lcd.print(label, x + (70 - tw) // 2, 70, col)
    lcd.font(lcd.FONT_Default)
    lcd.print("^ Swipe UP or [A] to close", 52, 155, COLOR_GREY)

def main():
    global panel_open, swipe_start, gesture_done
    draw_main()
    last_dot = 0

    while True:
        xy = read_xy()

        if xy:
            x, y = xy
            if swipe_start is None:
                swipe_start  = (x, y)
                gesture_done = False
            if not gesture_done:
                sx, sy = swipe_start
                dy = y - sy
                if not panel_open and dy >= SWIPE_DOWN:
                    gesture_done = True
                    panel_open   = True
                    swipe_start  = None
                    draw_panel()
                elif panel_open and dy <= -SWIPE_UP:
                    gesture_done = True
                    panel_open   = False
                    swipe_start  = None
                    draw_main()
            # point rouge live
            now = time.ticks_ms()
            if not panel_open and time.ticks_diff(now, last_dot) > 50:
                lcd.fillCircle(min(x, 319), min(y, 235), 5, COLOR_BAD)
                last_dot = now
        else:
            swipe_start  = None
            gesture_done = False

        if btnA.wasPressed():
            if panel_open:
                panel_open = False
                draw_main()
            else:
                panel_open = True
                draw_panel()

        gc.collect()
        time.sleep_ms(20)

main()
