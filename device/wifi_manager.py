# wifi_manager.py
# Manages WiFi connectivity and provides a simple on-screen
# interface to update credentials when needed (e.g. classroom demo).
# Credentials are persisted locally so the device reconnects
# automatically to known networks on reboot.

import network
import ujson
import time
from m5stack import *
from m5stack_ui import *

CREDENTIALS_FILE = "wifi_credentials.json"
CONNECTION_TIMEOUT = 15


class WiFiManager:

    def __init__(self):
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.ssid, self.password = self._load_credentials()

    def _load_credentials(self):
        # Load saved credentials from filesystem if available.
        # Falls back to the last network known by the firmware.
        try:
            with open(CREDENTIALS_FILE, "r") as f:
                data = ujson.load(f)
                return data["ssid"], data["password"]
        except:
            return None, None

    def _save_credentials(self, ssid, password):
        # Persist new credentials so they survive reboots.
        try:
            with open(CREDENTIALS_FILE, "w") as f:
                ujson.dump({"ssid": ssid, "password": password}, f)
        except Exception as e:
            print("[WiFi] Failed to save credentials:", e)

    def connect(self):
        # If already connected (common after soft reset), skip.
        if self.wlan.isconnected():
            print("[WiFi] Already connected:", self.wlan.ifconfig()[0])
            return True

        # MicroPython automatically attempts to reconnect to the
        # last known network at boot — no explicit connect() call
        # needed if credentials haven't changed.
        if self.ssid:
            self.wlan.connect(self.ssid, self.password)

        # Poll until connected or timeout reached.
        elapsed = 0
        while not self.wlan.isconnected() and elapsed < CONNECTION_TIMEOUT:
            time.sleep(0.5)
            elapsed += 0.5

        if self.wlan.isconnected():
            print("[WiFi] Connected. IP:", self.wlan.ifconfig()[0])
            return True

        print("[WiFi] Connection failed.")
        return False

    def show_config_screen(self):
        # Minimal UI to update WiFi credentials from the touchscreen.
        # Triggered automatically if connection fails, or manually
        # from the settings button in the main UI.
        lcd.clear()
        lcd.setCursor(10, 10)
        lcd.setTextSize(2)
        lcd.setTextColor(lcd.WHITE)
        lcd.print("WiFi Setup")

        lcd.setTextSize(1)
        lcd.setCursor(10, 50)
        lcd.print("SSID:")
        new_ssid = keyboard.readline()

        lcd.setCursor(10, 80)
        lcd.print("Password:")
        new_password = keyboard.readline()

        if new_ssid and new_password:
            self._save_credentials(new_ssid, new_password)
            self.ssid     = new_ssid
            self.password = new_password
            self.wlan.disconnect()
            time.sleep(1)
            success = self.connect()

            lcd.clear()
            lcd.setCursor(10, 100)
            if success:
                lcd.setTextColor(lcd.GREEN)
                lcd.print("Connected to " + new_ssid)
            else:
                lcd.setTextColor(lcd.RED)
                lcd.print("Failed — check credentials.")
            time.sleep(2)

        lcd.clear()

    def ensure_connected(self):
        # Single entry point for main.py.
        # On first boot or network change, opens the config screen.
        # On subsequent boots with known credentials, connects silently.
        success = self.connect()
        if not success:
            self.show_config_screen()
        return self.wlan.isconnected()