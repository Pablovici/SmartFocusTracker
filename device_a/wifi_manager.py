# device_a/wifi_manager.py
# Manages WiFi connectivity for M5Stack Core2.

import network
import time
from m5stack import lcd
from config import KNOWN_NETWORKS

COLOR_BG    = 0x1a1a2e
COLOR_WHITE = 0xFFFFFF
COLOR_GREY  = 0xAAAAAA

class WiFiManager:
    def __init__(self):
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)

    def connect(self):
        if self.wlan.isconnected():
            return True

        for ssid, password in KNOWN_NETWORKS:
            self._display("Connecting to\n{}".format(ssid))
            self.wlan.connect(ssid, password)
            for _ in range(15):
                if self.wlan.isconnected():
                    self._display("Connected!")
                    return True
                time.sleep(1)

        self._display("No WiFi found.")
        return False

    def _display(self, msg):
        lcd.clear(COLOR_BG)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print(msg, 10, 100, COLOR_WHITE)

    def is_connected(self):
        return self.wlan.isconnected()
