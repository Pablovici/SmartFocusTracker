# display_manager.py
# Manages all screen rendering for the M5Stack Core2 (320x240px).
# Organized into 3 pages navigated by touch: Focus, Weather, Air Quality.
# Each page has a clear visual hierarchy — one primary metric per screen
# to maximize readability on the small display.

from m5stack import *
from m5stack_ui import *
from uiflow import *
import time

# --- Color palette ---
# Consistent semantic colors used across all pages.
COLOR_BG       = 0x000000  # Black background — high contrast, modern look
COLOR_WHITE    = 0xFFFFFF  # Primary text
COLOR_GRAY     = 0x888888  # Secondary text / labels
COLOR_GREEN    = 0x00CC66  # Good / active state
COLOR_ORANGE   = 0xFF8800  # Warning state
COLOR_RED      = 0xFF3333  # Alert / critical state
COLOR_BLUE     = 0x3399FF  # Accent (weather, info)
COLOR_DARK     = 0x1A1A1A  # Card backgrounds

# --- Screen dimensions ---
SCREEN_W = 320
SCREEN_H = 240

# --- Page indices ---
PAGE_FOCUS   = 0
PAGE_WEATHER = 1
PAGE_AIR     = 2
TOTAL_PAGES  = 3


class DisplayManager:
    """
    Controls all UI rendering. Call update() with fresh data every cycle.
    The current page persists between updates so the display doesn't flicker.
    """

    def __init__(self):
        lcd.clear(COLOR_BG)
        lcd.setBrightness(80)  # Comfortable brightness, not blinding

        # Start on the Focus page — the most relevant view at boot.
        self.current_page = PAGE_FOCUS

        # Touch zones for page navigation dots (bottom center).
        # Each zone is a 40x30px tap target.
        self.nav_zones = [
            (120, 220, 160, 240),  # dot 1 → Focus
            (150, 220, 190, 240),  # dot 2 → Weather
            (180, 220, 220, 240),  # dot 3 → Air Quality
        ]

    # ----------------------------------------------------------
    # NAVIGATION
    # ----------------------------------------------------------

    def handle_touch(self, x, y):
        # Checks if a touch event falls on a navigation dot.
        # Returns True if the page changed (triggers a redraw).
        for i, (x1, y1, x2, y2) in enumerate(self.nav_zones):
            if x1 <= x <= x2 and y1 <= y <= y2:
                if self.current_page != i:
                    self.current_page = i
                    return True
        return False

    def next_page(self):
        # Cycles to the next page — can be bound to a swipe gesture.
        self.current_page = (self.current_page + 1) % TOTAL_PAGES

    # ----------------------------------------------------------
    # SHARED UI ELEMENTS
    # ----------------------------------------------------------

    def _draw_nav_dots(self):
        # Draws 3 navigation dots at the bottom of the screen.
        # The active page dot is white; inactive dots are gray.
        positions = [130, 158, 186]
        for i, x in enumerate(positions):
            color = COLOR_WHITE if i == self.current_page else COLOR_GRAY
            lcd.fillCircle(x, 230, 4, color)

    def _draw_status_bar(self, time_str, date_str):
        # Thin top bar showing time and date on every page.
        lcd.fillRect(0, 0, SCREEN_W, 28, COLOR_DARK)
        lcd.setTextColor(COLOR_WHITE)
        lcd.setTextSize(1)
        lcd.setCursor(10, 8)
        lcd.print(time_str)
        lcd.setTextColor(COLOR_GRAY)
        lcd.setCursor(SCREEN_W - 90, 8)
        lcd.print(date_str)

    def _color_for_value(self, value, warn_threshold, alert_threshold):
        # Returns a semantic color based on how far a value is from safe limits.
        # Used for CO2, TVOC, and humidity indicators.
        if value is None:
            return COLOR_GRAY
        if value >= alert_threshold:
            return COLOR_RED
        if value >= warn_threshold:
            return COLOR_ORANGE
        return COLOR_GREEN

    def _draw_bar(self, x, y, w, h, value, max_value, color):
        # Draws a horizontal progress bar representing a sensor value.
        # Background track is dark gray; fill color is semantic.
        lcd.fillRect(x, y, w, h, COLOR_DARK)
        if value is not None:
            fill_w = int((min(value, max_value) / max_value) * w)
            lcd.fillRect(x, y, fill_w, h, color)

    # ----------------------------------------------------------
    # PAGE 1 — FOCUS
    # ----------------------------------------------------------

    def _draw_focus_page(self, data):
        # Primary page shown at boot. Displays focus status, session timer,
        # and a compact sensor summary. Action buttons at the bottom.
        lcd.clear(COLOR_BG)
        self._draw_status_bar(data.get("time", "--:--"), data.get("date", "---"))

        focus_status  = data.get("focus_status", "focus")
        session_time  = data.get("session_time", "0min")
        temperature   = data.get("temperature")
        humidity      = data.get("humidity")
        co2           = data.get("co2_ppm")

        # --- Focus status indicator ---
        # Large colored dot + status label as the primary visual anchor.
        status_color = COLOR_GREEN if focus_status == "focus" else COLOR_ORANGE
        lcd.fillCircle(40, 100, 14, status_color)

        lcd.setTextColor(status_color)
        lcd.setTextSize(3)
        lcd.setCursor(65, 85)
        lcd.print("FOCUSING" if focus_status == "focus" else "ON BREAK")

        # --- Session timer ---
        lcd.setTextColor(COLOR_GRAY)
        lcd.setTextSize(1)
        lcd.setCursor(65, 120)
        lcd.print("Session: " + session_time)

        # --- Compact sensor row ---
        # Three key metrics displayed in a single line at y=160.
        lcd.setTextSize(1)
        lcd.setTextColor(COLOR_WHITE)

        temp_str = "{:.1f}C".format(temperature) if temperature is not None else "--"
        hum_str  = "{}%".format(int(humidity))   if humidity    is not None else "--"
        co2_str  = "{}ppm".format(co2)           if co2         is not None else "--"

        lcd.setCursor(10,  160); lcd.setTextColor(COLOR_BLUE);   lcd.print("TEMP")
        lcd.setCursor(10,  175); lcd.setTextColor(COLOR_WHITE);  lcd.print(temp_str)

        lcd.setCursor(110, 160); lcd.setTextColor(COLOR_BLUE);   lcd.print("HUM")
        lcd.setCursor(110, 175); lcd.setTextColor(COLOR_WHITE);  lcd.print(hum_str)

        lcd.setCursor(210, 160); lcd.setTextColor(COLOR_BLUE);   lcd.print("CO2")
        lcd.setCursor(210, 175); lcd.setTextColor(COLOR_WHITE);  lcd.print(co2_str)

        # --- Action buttons ---
        # PAUSE and ASK are the two primary interactions on this device.
        lcd.fillRoundRect(10,  198, 130, 30, 6, COLOR_DARK)
        lcd.fillRoundRect(170, 198, 130, 30, 6, COLOR_DARK)
        lcd.setTextColor(COLOR_WHITE)
        lcd.setTextSize(1)
        lcd.setCursor(50,  210); lcd.print("PAUSE")
        lcd.setCursor(215, 210); lcd.print("ASK")

        self._draw_nav_dots()

    # ----------------------------------------------------------
    # PAGE 2 — WEATHER
    # ----------------------------------------------------------

    def _draw_weather_page(self, data):
        # Displays current outdoor conditions and a 5-day forecast strip.
        lcd.clear(COLOR_BG)
        self._draw_status_bar(data.get("time", "--:--"), data.get("date", "---"))

        weather     = data.get("weather", {})
        city        = weather.get("city", "Lausanne")
        temp_out    = weather.get("temp_out")
        description = weather.get("description", "")
        humidity    = weather.get("humidity_out")
        wind        = weather.get("wind_speed")
        forecast    = weather.get("forecast", [])

        # --- City and current temperature ---
        lcd.setTextColor(COLOR_WHITE)
        lcd.setTextSize(2)
        lcd.setCursor(10, 38)
        lcd.print(city)

        temp_str = "{:.0f}C".format(temp_out) if temp_out is not None else "--"
        lcd.setTextSize(3)
        lcd.setCursor(200, 35)
        lcd.print(temp_str)

        # --- Weather description ---
        lcd.setTextColor(COLOR_GRAY)
        lcd.setTextSize(1)
        lcd.setCursor(10, 68)
        lcd.print(description.capitalize())

        # --- Humidity and wind ---
        lcd.setTextColor(COLOR_BLUE)
        lcd.setCursor(10, 90)
        hum_str  = "Humidity {}%".format(int(humidity)) if humidity is not None else "Humidity --"
        wind_str = "Wind {} km/h".format(int(wind))     if wind     is not None else "Wind --"
        lcd.print(hum_str + "   " + wind_str)

        # --- 5-day forecast strip ---
        # Each day occupies a 60px wide column in the bottom half.
        lcd.fillRect(0, 110, SCREEN_W, 1, COLOR_GRAY)  # Separator line

        for i, day in enumerate(forecast[:5]):
            col_x = 10 + i * 62
            lcd.setTextColor(COLOR_GRAY)
            lcd.setTextSize(1)
            lcd.setCursor(col_x, 118)
            lcd.print(day.get("day", "")[:3])  # Mon, Tue, Wed...

            # Min/max temperature
            lcd.setTextColor(COLOR_WHITE)
            lcd.setCursor(col_x, 140)
            min_t = "{:.0f}".format(day.get("min", 0))
            max_t = "{:.0f}".format(day.get("max", 0))
            lcd.print(max_t + "/" + min_t)

        self._draw_nav_dots()

    # ----------------------------------------------------------
    # PAGE 3 — AIR QUALITY
    # ----------------------------------------------------------

    def _draw_air_page(self, data):
        # Displays CO2, TVOC and humidity as labeled progress bars.
        # Color coding gives an immediate sense of air quality level.
        lcd.clear(COLOR_BG)
        self._draw_status_bar(data.get("time", "--:--"), data.get("date", "---"))

        co2      = data.get("co2_ppm")
        tvoc     = data.get("tvoc_ppb")
        humidity = data.get("humidity")

        # Thresholds defined by air quality standards:
        # CO2  : warn at 1000ppm, alert at 1500ppm (WHO indoor guidelines)
        # TVOC : warn at 300ppb,  alert at 500ppb
        # Humidity : below 40% triggers a dryness alert per project spec
        metrics = [
            {
                "label":     "CO2",
                "value":     co2,
                "unit":      "ppm",
                "max":       2000,
                "warn":      1000,
                "alert":     1500,
                "y":         50
            },
            {
                "label":     "TVOC",
                "value":     tvoc,
                "unit":      "ppb",
                "max":       600,
                "warn":      300,
                "alert":     500,
                "y":         115
            },
            {
                "label":     "Humidity",
                "value":     humidity,
                "unit":      "%",
                "max":       100,
                "warn":      40,   # Below 40% = too dry (project requirement)
                "alert":     25,
                "y":         180
            },
        ]

        for m in metrics:
            color = self._color_for_value(m["value"], m["warn"], m["alert"])

            # Label
            lcd.setTextColor(COLOR_GRAY)
            lcd.setTextSize(1)
            lcd.setCursor(10, m["y"])
            lcd.print(m["label"])

            # Value
            val_str = "{} {}".format(int(m["value"]), m["unit"]) \
                      if m["value"] is not None else "-- " + m["unit"]
            lcd.setTextColor(color)
            lcd.setCursor(200, m["y"])
            lcd.print(val_str)

            # Progress bar
            self._draw_bar(10, m["y"] + 16, 280, 12, m["value"], m["max"], color)

            # Status label below the bar
            if m["value"] is not None:
                if m["value"] >= m["alert"]:
                    status = "ALERT"
                elif m["value"] >= m["warn"]:
                    status = "WARNING"
                else:
                    status = "GOOD"
                lcd.setTextColor(color)
                lcd.setTextSize(1)
                lcd.setCursor(10, m["y"] + 34)
                lcd.print(status)

        self._draw_nav_dots()

    # ----------------------------------------------------------
    # MAIN UPDATE ENTRY POINT
    # ----------------------------------------------------------

    def update(self, data):
        # Called by main.py every cycle with fresh sensor + weather data.
        # Redraws only the current page to avoid unnecessary full clears.
        if self.current_page == PAGE_FOCUS:
            self._draw_focus_page(data)
        elif self.current_page == PAGE_WEATHER:
            self._draw_weather_page(data)
        elif self.current_page == PAGE_AIR:
            self._draw_air_page(data)

    def show_boot_screen(self):
        # Displayed during the boot sequence while WiFi connects and
        # BigQuery sync runs. Gives the user visual feedback that the
        # device is not frozen.
        lcd.clear(COLOR_BG)
        lcd.setTextColor(COLOR_WHITE)
        lcd.setTextSize(2)
        lcd.setCursor(60, 90)
        lcd.print("Focus Tracker")
        lcd.setTextColor(COLOR_GRAY)
        lcd.setTextSize(1)
        lcd.setCursor(90, 120)
        lcd.print("Connecting...")

    def show_offline_banner(self):
        # Overlays a small red banner when the device loses WiFi.
        # Does not clear the page — just adds a warning on top.
        lcd.fillRect(0, 0, SCREEN_W, 18, COLOR_RED)
        lcd.setTextColor(COLOR_WHITE)
        lcd.setTextSize(1)
        lcd.setCursor(90, 4)
        lcd.print("NO CONNECTION")