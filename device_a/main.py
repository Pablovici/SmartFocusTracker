# device_a/main.py
# Main device — weather display, sensors, voice assistant, session status.
# Sensors: SHT30 (temp/humidity), SGP30 (CO2/TVOC), PIR (motion)
# MicroPython — deployed via UIFlow 1.0
# Assigned to: Amir

import gc
import os
import time
import ntptime
import network
import usocket
import ussl
import ubinascii
import urequests
import ujson
from machine import I2C, Pin
from m5stack import lcd, btnA, btnB, btnC, speaker, rgb
from MediaTrans.MicRecord import MicRecord

# ============================================================
# CONFIGURATION
# ============================================================
MIDDLEWARE_URL   = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_HOST       = "smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_PORT       = 443
NTP_UTC_OFFSET   = 2
SENSOR_INTERVAL  = 10
BQ_INTERVAL      = 30         # Offset from SENSOR_INTERVAL to avoid request collisions
DRAW_INTERVAL    = 5
HUMIDITY_MIN     = 40
WEATHER_INTERVAL = 1800
ALERT_COOLDOWN   = 3600
BREAK_INTERVAL   = 3600
PIR_ABSENT_ALERT = 300
RECORD_SECS      = 5
VOICE_FILE       = '/flash/voice.wav'
RESP_FILE        = '/flash/res/resp.wav'
# Device A is display-only for sessions — polls less than Device B (10s)
# to avoid competing for the same Flask worker at the same time.
SESSION_INTERVAL = 15

KNOWN_NETWORKS = [
    ("iPhone de Amir", "toad1234"),
    ("iot-unil",       "4u6uch4hpY9pJ2f9"),
]

# ============================================================
# COLORS
# ============================================================
COLOR_BG      = 0x1a1a2e
COLOR_WHITE   = 0xFFFFFF
COLOR_GREY    = 0xAAAAAA
COLOR_DIVIDER = 0x444444
COLOR_GOOD    = 0x00FF00
COLOR_WARN    = 0xFFAA00
COLOR_BAD     = 0xFF0000
COLOR_ACCENT  = 0x00BCD4

COLOR_GREY_DIM      = 0x555577
COLOR_CARD_ACTIVE   = 0x0d2b1a
COLOR_CARD_INACTIVE = 0x22223a

COLOR_SUN   = 0xFFD740
COLOR_RAIN  = 0x4FC3F7
COLOR_STORM = 0xFF5252
COLOR_SNOW  = 0xE8E8E8
COLOR_CLOUD = 0xB0BEC5
COLOR_MIST  = 0x90A4AE

# ============================================================
# SHT30 — Temp & Humidity
# ============================================================
class SHT30:
    def __init__(self, i2c, addr=0x44):
        self.i2c = i2c; self.addr = addr

    @property
    def temperature(self):
        self.i2c.writeto(self.addr, bytes([0x2C, 0x06]))
        time.sleep_ms(50)
        data = self.i2c.readfrom(self.addr, 6)
        return -45 + (175 * ((data[0] << 8) | data[1]) / 65535.0)

    @property
    def humidity(self):
        self.i2c.writeto(self.addr, bytes([0x2C, 0x06]))
        time.sleep_ms(50)
        data = self.i2c.readfrom(self.addr, 6)
        return 100 * ((data[3] << 8) | data[4]) / 65535.0

# ============================================================
# SGP30 — CO2 & TVOC
# ============================================================
class SGP30:
    def __init__(self, i2c, addr=0x58):
        self.i2c = i2c; self.addr = addr
        self.i2c.writeto(self.addr, bytes([0x20, 0x03]))
        time.sleep_ms(10)

    @property
    def eCO2(self):
        self.i2c.writeto(self.addr, bytes([0x20, 0x08]))
        time.sleep_ms(12)
        data = self.i2c.readfrom(self.addr, 6)
        return (data[0] << 8) | data[1]

    @property
    def TVOC(self):
        self.i2c.writeto(self.addr, bytes([0x20, 0x08]))
        time.sleep_ms(12)
        data = self.i2c.readfrom(self.addr, 6)
        return (data[3] << 8) | data[4]

# ============================================================
# HARDWARE INITIALIZATION
# ============================================================
i2c_a = I2C(1, scl=Pin(33), sda=Pin(32), freq=100000)
i2c_c = I2C(scl=Pin(13), sda=Pin(14), freq=100000)
env   = SHT30(i2c_a)
tvoc  = SGP30(i2c_c)
pir   = Pin(26, Pin.IN)
wlan  = network.WLAN(network.STA_IF)
mic   = MicRecord()

try:
    os.mkdir('/flash/res')
except:
    pass

# ============================================================
# STATE
# Screens: 0=main  2=answer  3=forecast  4=wifi
# ============================================================
state = {
    "temperature": None, "humidity": None,
    "co2_ppm": None, "tvoc_ppb": None,
    "air_quality_label": "Unknown", "motion": False,
    "weather_temp": "--", "weather_cond": "N/A", "weather_city": "",
    "forecast": [],
    "session_active": False, "session_paused": False, "session_work_sec": 0,
    "time_str": "--:--", "date_str": "---",
}

alert_times      = {"weather": 0, "humidity": 0, "air": 0, "break": 0, "absent": 0}
last_motion_time = 0
current_screen   = 0
last_answer      = ""
last_question    = ""

# ============================================================
# PARTIAL REDRAW — zone tracking for main screen (FIX 1)
#
# Instead of lcd.clear() on every DRAW_INTERVAL, we track what
# was last drawn in each zone and only repaint the zones that changed.
# No more full-screen flash every 5 seconds.
# ============================================================

# Sentinel values different from any real state value so all zones
# are drawn on the very first call to smart_update_main_screen().
_last_main = {
    "time_str":          None,
    "date_str":          None,
    "weather_temp":      None,
    "weather_cond":      None,
    "weather_city":      None,
    "temperature":       None,
    "humidity":          None,
    "air_quality_label": None,
    "session_active":    None,
    "session_paused":    None,
}

# Set to True whenever we need a full lcd.clear() redraw:
# on first boot, and every time we switch back to screen 0.
_main_needs_full_redraw = True

# Forecast screen is only redrawn when data changes (every 30 min)
# or when first entering the screen. Without this flag, draw_forecast_screen()
# was called every DRAW_INTERVAL (5s) causing unnecessary full redraws.
_forecast_needs_redraw = True

# WiFi screen is only redrawn on first entry or after a connection attempt.
_wifi_needs_redraw = True

# ============================================================
# HELPERS
# ============================================================

def classify_air(co2):
    if co2 is None: return "Unknown"
    if co2 < 800:   return "Good"
    if co2 < 1000:  return "Moderate"
    return "Poor"

def air_color(label):
    if label == "Good":     return COLOR_GOOD
    if label == "Moderate": return COLOR_WARN
    return COLOR_BAD

def show_msg(msg):
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(msg, 10, 100, COLOR_WHITE)

def get_time_strings():
    t = time.localtime(time.time() + NTP_UTC_OFFSET * 3600)
    days   = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    return "{:02d}:{:02d}".format(t[3], t[4]), "{} {} {}".format(days[t[6]], t[2], months[t[1]-1])

def file_size(path):
    try:    return os.stat(path)[6]
    except: return 0

def safe_remove(path):
    try:    os.remove(path)
    except: pass

def condition_color(cond):
    c = cond.lower()
    if "thunder" in c or "storm" in c:                 return COLOR_STORM
    if "snow" in c or "sleet" in c:                    return COLOR_SNOW
    if "rain" in c or "shower" in c or "drizzle" in c: return COLOR_RAIN
    if "clear" in c or "sun" in c:                     return COLOR_SUN
    if "cloud" in c or "overcast" in c:                return COLOR_CLOUD
    if "mist" in c or "fog" in c or "haze" in c:       return COLOR_MIST
    return COLOR_WHITE

def date_to_dayname(date_str, today_str):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if date_str == today_str:
        return "Today"
    parts = date_str.split("-")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    ts   = time.mktime((y, m, d, 12, 0, 0, 0, 0))
    wday = time.localtime(ts)[6]
    return days[wday]

def today_str():
    t = time.localtime(time.time() + NTP_UTC_OFFSET * 3600)
    return "{:04d}-{:02d}-{:02d}".format(t[0], t[1], t[2])

# ============================================================
# WEATHER ICONS
# ============================================================

def _icon_sun(cx, cy):
    lcd.fillCircle(cx, cy, 5, COLOR_SUN)
    rays = [(cx,cy-6,cx,cy-10),(cx+4,cy-4,cx+7,cy-7),(cx+6,cy,cx+10,cy),
            (cx+4,cy+4,cx+7,cy+7),(cx,cy+6,cx,cy+10),(cx-4,cy+4,cx-7,cy+7),
            (cx-6,cy,cx-10,cy),(cx-4,cy-4,cx-7,cy-7)]
    for x1,y1,x2,y2 in rays: lcd.line(x1,y1,x2,y2,COLOR_SUN)

def _icon_cloud(cx, cy, col):
    lcd.fillCircle(cx-4,cy+1,5,col); lcd.fillCircle(cx+3,cy-1,6,col)
    lcd.fillCircle(cx-9,cy+3,3,col); lcd.fillRect(cx-12,cy+3,22,6,col)

def _icon_rain(cx, cy):
    _icon_cloud(cx,cy-3,COLOR_CLOUD)
    for rx,ry in [(cx-7,cy+6),(cx-2,cy+8),(cx+4,cy+6),(cx+9,cy+8)]:
        lcd.line(rx,ry,rx-2,ry+5,COLOR_RAIN)

def _icon_heavy_rain(cx, cy):
    _icon_cloud(cx,cy-4,0x607D8B)
    for rx,ry in [(cx-8,cy+5),(cx-3,cy+7),(cx+2,cy+5),(cx+7,cy+7),(cx-5,cy+10),(cx+4,cy+10)]:
        lcd.line(rx,ry,rx-2,ry+6,COLOR_RAIN)

def _icon_snow(cx, cy):
    lcd.line(cx-8,cy,cx+8,cy,COLOR_SNOW); lcd.line(cx,cy-8,cx,cy+8,COLOR_SNOW)
    lcd.line(cx-6,cy-6,cx+6,cy+6,COLOR_SNOW); lcd.line(cx-6,cy+6,cx+6,cy-6,COLOR_SNOW)
    lcd.fillCircle(cx,cy,2,COLOR_SNOW)
    for tx,ty in [(cx-8,cy),(cx+8,cy),(cx,cy-8),(cx,cy+8)]:
        lcd.line(tx-2,ty-2,tx+2,ty+2,COLOR_SNOW)

def _icon_storm(cx, cy):
    _icon_cloud(cx,cy-4,0x546E7A)
    lcd.line(cx+1,cy+3,cx-4,cy+10,0xFFE000); lcd.line(cx-4,cy+10,cx+1,cy+10,0xFFE000)
    lcd.line(cx+1,cy+10,cx-3,cy+16,0xFFE000)

def _icon_mist(cx, cy):
    for my in [cy-5,cy-1,cy+3,cy+7]:
        lcd.line(cx-9,my,cx-3,my,COLOR_MIST); lcd.line(cx,my,cx+6,my,COLOR_MIST)
        lcd.line(cx-6,my+2,cx+9,my+2,COLOR_MIST)

def _icon_few_clouds(cx, cy):
    lcd.fillCircle(cx+4,cy+1,5,COLOR_SUN); lcd.line(cx+4,cy-5,cx+4,cy-8,COLOR_SUN)
    lcd.line(cx+9,cy+1,cx+12,cy+1,COLOR_SUN); _icon_cloud(cx-2,cy+2,COLOR_CLOUD)

def draw_weather_icon(cx, cy, cond):
    c = cond.lower()
    if "thunder" in c or "storm" in c:          _icon_storm(cx,cy)
    elif "snow" in c or "sleet" in c:            _icon_snow(cx,cy)
    elif "heavy rain" in c or "shower" in c:     _icon_heavy_rain(cx,cy)
    elif "rain" in c or "drizzle" in c:          _icon_rain(cx,cy)
    elif "clear" in c or "sun" in c:             _icon_sun(cx,cy)
    elif "few clouds" in c or "scattered" in c:  _icon_few_clouds(cx,cy)
    elif "mist" in c or "fog" in c or "haze" in c: _icon_mist(cx,cy)
    else:                                        _icon_cloud(cx,cy,COLOR_CLOUD)

# ============================================================
# WIFI
# ============================================================

def connect_wifi():
    """Boot WiFi — tries all KNOWN_NETWORKS in order."""
    wlan.active(True)
    if wlan.isconnected(): return True
    for ssid, pwd in KNOWN_NETWORKS:
        show_msg("WiFi:\n{}".format(ssid))
        wlan.connect(ssid, pwd)
        for _ in range(15):
            if wlan.isconnected():
                show_msg("Connected!")
                time.sleep(1)
                return True
            time.sleep(1)
    show_msg("No WiFi found")
    return False

def connect_to_network(idx):
    """
    FIX 2 — WiFi fallback.
    Tries the requested network first. If it fails, automatically
    falls back to the other network in KNOWN_NETWORKS.
    The user is never left disconnected just because one network
    was unavailable.
    """
    indices_to_try = [idx, 1 - idx]  # requested first, then fallback

    for attempt, try_idx in enumerate(indices_to_try):
        ssid, pwd = KNOWN_NETWORKS[try_idx]
        lcd.clear(COLOR_BG)
        lcd.font(lcd.FONT_DejaVu18)
        if attempt > 0:
            # Show fallback indication
            lcd.print("Not found, trying:", 10, 60, COLOR_WARN)
        else:
            lcd.print("Connecting to:", 10, 80, COLOR_GREY)
        lcd.print(ssid, 10, 110, COLOR_WHITE)

        wlan.active(True)
        if wlan.isconnected():
            wlan.disconnect()
            time.sleep(1)
        wlan.connect(ssid, pwd)

        for i in range(15):
            lcd.fillRect(10, 148, 120, 20, COLOR_BG)
            lcd.print("." * (i % 4 + 1), 10, 150, COLOR_ACCENT)
            if wlan.isconnected():
                try: ntptime.settime()
                except: pass
                lcd.print("Connected!", 10, 180, COLOR_GOOD)
                time.sleep(1)
                return True
            time.sleep(1)

        # This network failed — will try the next one if available
        lcd.print("Failed.", 10, 180, COLOR_BAD)
        time.sleep(1)

    # Both networks failed
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("No WiFi available", 10, 110, COLOR_BAD)
    time.sleep(2)
    return False

# ============================================================
# SENSORS
# ============================================================

def read_sensors():
    try:
        state["temperature"] = round(env.temperature, 1)
        state["humidity"]    = round(env.humidity, 1)
    except Exception as e: print("[ENV]", e)
    try:
        state["co2_ppm"]  = tvoc.eCO2
        state["tvoc_ppb"] = tvoc.TVOC
    except Exception as e: print("[TVOC]", e)
    try:
        state["motion"] = bool(pir.value())
    except Exception as e: print("[PIR]", e)
    state["air_quality_label"] = classify_air(state["co2_ppm"])

def post_indoor():
    """
    Posts indoor sensor data to middleware.
    gc.collect() called BEFORE the request to free memory first —
    prevents MemoryError on long-running sessions.
    """
    payload = {
        "temperature": state["temperature"], "humidity": state["humidity"],
        "co2_ppm": state["co2_ppm"], "tvoc_ppb": state["tvoc_ppb"],
        "air_quality_label": state["air_quality_label"],
        "motion_detected": state["motion"],
    }
    gc.collect()
    try:
        r = urequests.post(MIDDLEWARE_URL + "/data/indoor",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps(payload))
        r.close()
    except Exception as e: print("[POST]", e)
    gc.collect()

# ============================================================
# WEATHER & SESSION
# ============================================================

def fetch_weather():
    """
    gc.collect() before the call prevents MicroPython heap
    fragmentation from causing MemoryError on long runtimes.
    Sets _forecast_needs_redraw so the forecast screen repaints
    only when data actually changed, not every 5 seconds.
    """
    global _forecast_needs_redraw
    gc.collect()
    try:
        r = urequests.get(MIDDLEWARE_URL + "/weather")
        if r.status_code == 200:
            data    = ujson.loads(r.text)
            current = data.get("current", {})
            state["weather_temp"] = int(round(current.get("temperature", 0)))
            state["weather_cond"] = current.get("condition", "N/A")
            state["weather_city"] = current.get("city", "")
            state["forecast"]     = data.get("forecast", [])
            _forecast_needs_redraw = True   # New data arrived — redraw forecast if visible
        r.close()
    except Exception as e: print("[WEATHER]", e)
    gc.collect()

def fetch_session():
    """
    FIX 3 — Reads session state from middleware.
    gc.collect() BEFORE the call is the key fix for session data
    becoming permanently stale after the device has been running
    for a long time. MicroPython's heap fragments over time and
    urequests.get() fails to allocate if GC hasn't run recently.
    Without the pre-call GC, exceptions are swallowed and the
    session display freezes at the last known state indefinitely.
    """
    gc.collect()
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current")
        if r.status_code == 200:
            d = ujson.loads(r.text)
            state["session_active"]   = d.get("active", False)
            state["session_paused"]   = d.get("paused", False)
            state["session_work_sec"] = d.get("work_seconds", 0)
        r.close()
    except Exception as e:
        print("[SESSION]", e)
    gc.collect()

def sync_latest():
    """Restores last sensor values from BigQuery on boot."""
    gc.collect()
    try:
        r = urequests.get(MIDDLEWARE_URL + "/latest")
        if r.status_code == 200:
            d = ujson.loads(r.text)
            if d.get("temperature") is not None:
                state["temperature"] = round(d["temperature"], 1)
            if d.get("humidity") is not None:
                state["humidity"] = round(d["humidity"], 1)
            if d.get("co2_ppm") is not None:
                state["co2_ppm"] = d["co2_ppm"]
            if d.get("tvoc_ppb") is not None:
                state["tvoc_ppb"] = d["tvoc_ppb"]
            if d.get("air_quality_label"):
                state["air_quality_label"] = d["air_quality_label"]
            state["motion"] = bool(d.get("motion_detected", False))
        r.close()
    except Exception as e: print("[SYNC]", e)
    gc.collect()

# ============================================================
# HTTPS SOCKET — stream WAV to /ask
# ============================================================

def _ssl_post_wav_to_ask(filepath):
    sz = file_size(filepath)
    if sz <= 0: return None, 'empty file'
    prefix   = b'{"audio_b64":"'
    suffix   = b'"}'
    b64_len  = ((sz + 2) // 3) * 4
    body_len = len(prefix) + b64_len + len(suffix)
    req = (
        'POST /ask HTTP/1.1\r\n'
        'Host: ' + CLOUD_HOST + '\r\n'
        'Content-Type: application/json\r\n'
        'Content-Length: ' + str(body_len) + '\r\n'
        'Connection: close\r\n\r\n'
    ).encode('utf-8')
    s = ss = f = None
    try:
        addr = usocket.getaddrinfo(CLOUD_HOST, CLOUD_PORT, 0, usocket.SOCK_STREAM)[0][-1]
        s  = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
        s.settimeout(60); s.connect(addr)
        ss = ussl.wrap_socket(s, server_hostname=CLOUD_HOST)
        ss.write(req); ss.write(prefix)
        f = open(filepath, 'rb')
        while True:
            chunk = f.read(384)
            if not chunk: break
            b64 = ubinascii.b2a_base64(chunk)
            if b64[-1] == 10: b64 = b64[:-1]
            ss.write(b64); gc.collect()
        f.close(); f = None; ss.write(suffix)
        raw = b''
        while True:
            chunk = ss.read(512)
            if not chunk: break
            raw += chunk
        status_code = int(raw.split(b'\r\n')[0].decode().split(' ')[1])
        parts = raw.split(b'\r\n\r\n', 1)
        body_text = parts[1].decode('utf-8') if len(parts) > 1 else ''
        return status_code, body_text
    except Exception as e:
        return None, str(e)
    finally:
        if f:
            try: f.close()
            except: pass
        if ss:
            try: ss.close()
            except: pass
        elif s:
            try: s.close()
            except: pass

# ============================================================
# HTTPS SOCKET — stream /speak-wav to file
# ============================================================

def _ssl_post_to_wav_file(path, payload_dict, out_file):
    body = ujson.dumps(payload_dict).encode('utf-8')
    req  = (
        'POST ' + path + ' HTTP/1.1\r\n'
        'Host: ' + CLOUD_HOST + '\r\n'
        'Content-Type: application/json\r\n'
        'Content-Length: ' + str(len(body)) + '\r\n'
        'Connection: close\r\n\r\n'
    ).encode('utf-8') + body
    s = ss = f = None
    try:
        addr = usocket.getaddrinfo(CLOUD_HOST, CLOUD_PORT, 0, usocket.SOCK_STREAM)[0][-1]
        s  = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
        s.settimeout(30); s.connect(addr)
        ss = ussl.wrap_socket(s, server_hostname=CLOUD_HOST)
        ss.write(req)
        header_data = b''
        while b'\r\n\r\n' not in header_data:
            chunk = ss.read(128)
            if not chunk: break
            header_data += chunk
        if b'\r\n\r\n' not in header_data: return False, 'bad response'
        header_part, body_start = header_data.split(b'\r\n\r\n', 1)
        status_code = int(header_part.split(b'\r\n')[0].decode().split(' ')[1])
        if status_code != 200: return False, 'HTTP ' + str(status_code)
        safe_remove(out_file)
        f = open(out_file, 'wb')
        if body_start: f.write(body_start)
        while True:
            chunk = ss.read(512)
            if not chunk: break
            f.write(chunk)
        f.close(); f = None
        return True, 'ok'
    except Exception as e:
        return False, str(e)
    finally:
        if f:
            try: f.close()
            except: pass
        if ss:
            try: ss.close()
            except: pass
        elif s:
            try: s.close()
            except: pass

# ============================================================
# VOICE FLOW
# ============================================================

def voice_flow():
    global last_answer, last_question, current_screen
    show_msg("Preparez-vous...")
    time.sleep(1)
    try: speaker.sing(1200, 1, 200)
    except: pass
    time.sleep_ms(150)
    show_msg(">>> PARLEZ <<<")
    mic.record2file(RECORD_SECS, VOICE_FILE)
    try: speaker.sing(800, 1, 150)
    except: pass
    sz = file_size(VOICE_FILE)
    if sz < 1000:
        show_msg("Rien entendu\nReessayez"); time.sleep(2); return
    show_msg("Analyse...")
    code, body = _ssl_post_wav_to_ask(VOICE_FILE)
    gc.collect()
    if code is None or code != 200:
        show_msg("Erreur reseau"); time.sleep(2); return
    try:
        resp = ujson.loads(body)
        answer = resp.get('answer_text', '')
        last_question = resp.get('question', '')
    except:
        show_msg("Erreur JSON"); time.sleep(2); return
    if not answer:
        show_msg("Pas de reponse\nIA indisponible"); time.sleep(2); return
    last_answer = answer
    show_msg("Synthese vocale...")
    ok, msg = _ssl_post_to_wav_file('/speak-wav', {'text': answer}, RESP_FILE)
    gc.collect()
    current_screen = 2
    draw_answer_screen()
    if ok:
        try: speaker.playWAV('res/resp.wav', volume=10)
        except Exception as e: print("[SPEAKER]", e)
    gc.collect()

# ============================================================
# ALERTS & LEDS
# ============================================================

def speak(text):
    gc.collect()
    try:
        r = urequests.post(MIDDLEWARE_URL + "/speak",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"text": text}))
        r.close()
    except Exception as e: print("[TTS]", e)
    gc.collect()

def update_leds():
    label = state["air_quality_label"]
    if label == "Good":       rgb.setColorAll(0x00CC00)
    elif label == "Moderate": rgb.setColorAll(0xFFAA00)
    elif label == "Poor":     rgb.setColorAll(0xFF0000)
    else:                     rgb.setColorAll(0x000000)

def check_alerts():
    if not state["motion"]: return
    now = time.time()
    if now - alert_times["weather"] > ALERT_COOLDOWN:
        speak("Current weather: {}, {} degrees.".format(
            state["weather_cond"], state["weather_temp"]))
        alert_times["weather"] = now
    h = state["humidity"]
    if h is not None and h < HUMIDITY_MIN:
        if now - alert_times["humidity"] > ALERT_COOLDOWN:
            speak("Humidity is low at {}%.".format(h))
            alert_times["humidity"] = now
    if state["air_quality_label"] == "Poor":
        if now - alert_times["air"] > ALERT_COOLDOWN:
            speak("Air quality is poor. Please open a window.")
            alert_times["air"] = now
    if state["session_active"] and not state["session_paused"]:
        if state["session_work_sec"] > BREAK_INTERVAL:
            if now - alert_times["break"] > ALERT_COOLDOWN:
                speak("Time for a break!")
                alert_times["break"] = now
        if last_motion_time > 0 and now - last_motion_time > PIR_ABSENT_ALERT:
            if now - alert_times["absent"] > PIR_ABSENT_ALERT:
                speak("Are you still there? No movement detected for 5 minutes.")
                alert_times["absent"] = now

# ============================================================
# DISPLAY — MAIN SCREEN ZONES (FIX 1)
#
# The main screen is split into 4 independent zones.
# Each zone function erases only its own rectangle, then repaints.
# No lcd.clear() needed — no full-screen flash.
#
# Zone layout:
#   y=  0–32 : time zone    (time, date)
#   y= 32–100: weather zone (outdoor temp, condition)
#   y=100     : divider line (drawn once, never erased)
#   y=101–162: sensor zone  (indoor values, air quality)
#   y=162–210: session zone (session state label)
#   y=210–240: button hints (drawn once, static)
# ============================================================

def _zone_time():
    """Redraws the time and date line without touching other zones."""
    lcd.fillRect(0, 0, 320, 32, COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(state["time_str"], 10,  8, COLOR_WHITE)
    lcd.print(state["date_str"], 175, 8, COLOR_GREY)
    _last_main["time_str"] = state["time_str"]
    _last_main["date_str"] = state["date_str"]

def _zone_weather():
    """Redraws outdoor weather without touching the divider at y=100."""
    lcd.fillRect(0, 32, 320, 68, COLOR_BG)   # y=32 to y=99
    wcol = condition_color(state["weather_cond"])
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{}C".format(state["weather_temp"]), 10, 40, wcol)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("{} {}".format(state["weather_cond"], state["weather_city"]), 10, 72, COLOR_GREY)
    _last_main["weather_temp"] = state["weather_temp"]
    _last_main["weather_cond"] = state["weather_cond"]
    _last_main["weather_city"] = state["weather_city"]

def _zone_sensors():
    """Redraws indoor sensor values. Starts at y=101 to preserve the divider."""
    lcd.fillRect(0, 101, 320, 61, COLOR_BG)  # y=101 to y=161
    t = state["temperature"]; h = state["humidity"]
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("In: {}C  {}%".format(
        "--" if t is None else t,
        "--" if h is None else h), 10, 110, COLOR_WHITE)
    aq = state["air_quality_label"]
    lcd.print("Air: {}".format(aq), 10, 140, air_color(aq))
    _last_main["temperature"]       = state["temperature"]
    _last_main["humidity"]          = state["humidity"]
    _last_main["air_quality_label"] = state["air_quality_label"]

def _zone_session():
    """Redraws the session status label only."""
    lcd.fillRect(0, 162, 320, 48, COLOR_BG)  # y=162 to y=209
    if state["session_active"]:
        label = "Paused"   if state["session_paused"] else "Working"
        color = COLOR_WARN if state["session_paused"] else COLOR_GOOD
    else:
        label = "No session"
        color = COLOR_GREY
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Session: {}".format(label), 10, 170, color)
    _last_main["session_active"] = state["session_active"]
    _last_main["session_paused"] = state["session_paused"]

def _zone_buttons():
    """Button hints — static, drawn once during full redraw."""
    wcol = condition_color(state["weather_cond"])
    lcd.font(lcd.FONT_Default)
    lcd.print("[WiFi]",     10,  220, COLOR_ACCENT)
    lcd.print("[Voice]",    120, 220, COLOR_WARN)
    lcd.print("[Forecast]", 225, 220, wcol)

def draw_main_screen():
    """
    Full initial draw — lcd.clear() + all zones + divider + buttons.
    Called only: on boot, and when returning from another screen.
    After this, smart_update_main_screen() handles all updates.
    """
    lcd.clear(COLOR_BG)
    lcd.line(0, 100, 320, 100, COLOR_DIVIDER)  # divider — never erased by zones
    _zone_time()
    _zone_weather()
    _zone_sensors()
    _zone_session()
    _zone_buttons()

def smart_update_main_screen():
    """
    FIX 1 — Partial update instead of full redraw.
    Compares each zone's current state against _last_main.
    Only repaints zones where data changed.
    No lcd.clear() → no full-screen flash.
    """
    if (state["time_str"] != _last_main["time_str"] or
            state["date_str"] != _last_main["date_str"]):
        _zone_time()

    if (state["weather_temp"] != _last_main["weather_temp"] or
            state["weather_cond"] != _last_main["weather_cond"] or
            state["weather_city"] != _last_main["weather_city"]):
        _zone_weather()
        _zone_buttons()   # Button hint color depends on weather condition

    if (state["temperature"]       != _last_main["temperature"] or
            state["humidity"]          != _last_main["humidity"] or
            state["air_quality_label"] != _last_main["air_quality_label"]):
        _zone_sensors()

    if (state["session_active"] != _last_main["session_active"] or
            state["session_paused"] != _last_main["session_paused"]):
        _zone_session()

# ============================================================
# DISPLAY — OTHER SCREENS
# ============================================================

def draw_answer_screen():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("AI Answer", 100, 8, COLOR_WARN)
    lcd.line(0, 32, 320, 32, COLOR_DIVIDER)
    if last_question:
        lcd.font(lcd.FONT_Default)
        lcd.print("Q: " + last_question[:44], 10, 36, COLOR_GREY)
    words = last_answer.split(" ")
    lines = []; line = ""
    for word in words:
        if len(line) + len(word) + 1 <= 48:
            line = line + " " + word if line else word
        else:
            lines.append(line); line = word
    if line: lines.append(line)
    y = 54
    for l in lines[:8]:
        lcd.print(l, 10, y, COLOR_WHITE); y += 20
    lcd.font(lcd.FONT_Default)
    lcd.print("[Back]", 240, 220, COLOR_GREY)

def draw_forecast_screen():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("5-Day Forecast", 55, 6, COLOR_WHITE)
    lcd.line(0, 28, 320, 28, COLOR_DIVIDER)
    forecast = state["forecast"]
    if not forecast:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No forecast data", 45, 110, COLOR_GREY)
        lcd.font(lcd.FONT_Default)
        lcd.print("[Back]", 10, 220, COLOR_GREY)
        return
    td = today_str(); col_w = 64
    for i, day in enumerate(forecast[:5]):
        cx = col_w * i + 32; x0 = col_w * i
        date = day.get("date", ""); name = date_to_dayname(date, td)
        tmin = int(round(day.get("temp_min", 0))); tmax = int(round(day.get("temp_max", 0)))
        cond = day.get("condition", "N/A"); col = condition_color(cond)
        if i > 0: lcd.line(x0, 29, x0, 205, COLOR_DIVIDER)
        x_bar = x0 + (1 if i > 0 else 0)
        lcd.fillRect(x_bar, 29, col_w - (1 if i > 0 else 0), 5, col)
        lcd.font(lcd.FONT_Default)
        name_s = name[:3]; lcd.print(name_s, cx - len(name_s) * 4, 42, col)
        draw_weather_icon(cx, 88, cond)
        lcd.font(lcd.FONT_DejaVu18)
        tmax_s = "{}°".format(tmax); lcd.print(tmax_s, cx - len(tmax_s) * 6, 130, COLOR_WHITE)
        lcd.font(lcd.FONT_Default)
        tmin_s = "{}°".format(tmin); lcd.print(tmin_s, cx - len(tmin_s) * 4, 155, COLOR_GREY)
        cond_s = cond.split()[0][:7]; lcd.print(cond_s, cx - len(cond_s) * 4, 172, COLOR_GREY)
    lcd.line(0, 205, 320, 205, COLOR_DIVIDER)
    lcd.font(lcd.FONT_Default)
    lcd.print("[Back]", 10, 215, COLOR_GREY)

def _wifi_cx(text, char_w):
    return max(0, (320 - len(text) * char_w) // 2)

def _wifi_rx(text, char_w, margin=10):
    return max(0, 320 - len(text) * char_w - margin)

def _wifi_split(ssid, max_chars=11):
    if len(ssid) <= max_chars: return [ssid, ""]
    idx = ssid.rfind(" ", 0, max_chars)
    if idx > 0: return [ssid[:idx], ssid[idx + 1:]]
    return [ssid[:max_chars], ssid[max_chars:]]

def _wifi_draw_card(x, y, w, h, ssid):
    try:    is_active = wlan.isconnected() and wlan.config("essid") == ssid
    except: is_active = False
    bg = COLOR_CARD_ACTIVE if is_active else COLOR_CARD_INACTIVE
    lcd.fillRect(x, y, w, h, bg)
    top_color = COLOR_GOOD if is_active else COLOR_DIVIDER
    lcd.line(x,y,x+w,y,top_color); lcd.line(x,y,x,y+h,COLOR_DIVIDER)
    lcd.line(x+w,y,x+w,y+h,COLOR_DIVIDER); lcd.line(x,y+h,x+w,y+h,COLOR_DIVIDER)
    lines = _wifi_split(ssid, 11); name_color = COLOR_WHITE if is_active else COLOR_GREY
    lcd.font(lcd.FONT_DejaVu18); lcd.print(lines[0], x+7, y+10, name_color)
    if lines[1]: lcd.print(lines[1], x+7, y+30, name_color)
    if is_active: lcd.print(">> Active", x+7, y+72, COLOR_GOOD)
    else:
        lcd.print("Tap to", x+7, y+68, COLOR_GREY_DIM)
        lcd.print("connect", x+7, y+88, COLOR_GREY_DIM)

def draw_wifi_screen():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    title = "WiFi Selection"
    lcd.print(title, _wifi_cx(title, 11), 8, COLOR_ACCENT)
    lcd.line(0, 30, 320, 30, COLOR_DIVIDER)
    _wifi_draw_card(6,   40, 146, 138, KNOWN_NETWORKS[0][0])
    _wifi_draw_card(168, 40, 146, 138, KNOWN_NETWORKS[1][0])
    lcd.line(0, 188, 320, 188, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("< Connect", 10,                        205, COLOR_ACCENT)
    lcd.print("Cancel",    _wifi_cx("Cancel", 11),    205, COLOR_GREY)
    lcd.print("Connect >", _wifi_rx("Connect >", 11), 205, COLOR_ACCENT)

# ============================================================
# BUTTONS
# ============================================================

def handle_buttons():
    """
    FIX 1 — sets _main_needs_full_redraw = True whenever returning
    to screen 0 from another screen, so the next draw cycle does a
    full lcd.clear() + redraw instead of a partial update on a stale bg.
    Sets _forecast_needs_redraw and _wifi_needs_redraw when entering
    those screens so they draw exactly once on entry, not every 5s.
    """
    global current_screen, _main_needs_full_redraw, _forecast_needs_redraw, _wifi_needs_redraw

    if current_screen == 4:
        if btnA.wasPressed():
            connect_to_network(0)
            current_screen = 0
            _main_needs_full_redraw = True
        if btnB.wasPressed():
            current_screen = 0
            _main_needs_full_redraw = True
        if btnC.wasPressed():
            connect_to_network(1)
            current_screen = 0
            _main_needs_full_redraw = True

    elif current_screen == 3:
        if btnA.wasPressed():
            current_screen = 0
            _main_needs_full_redraw = True

    elif current_screen == 2:
        if btnA.wasPressed():
            current_screen = 0
            _main_needs_full_redraw = True

    else:
        if btnA.wasPressed():
            current_screen = 4
            _wifi_needs_redraw = True       # Draw WiFi screen once on entry
        if btnB.wasPressed():
            voice_flow()
            _main_needs_full_redraw = True
        if btnC.wasPressed():
            current_screen = 3
            _forecast_needs_redraw = True   # Draw forecast once on entry

# ============================================================
# BOOT
# ============================================================

def boot():
    show_msg("Booting...")
    time.sleep(1)
    show_msg("Warming up\nair sensor...")
    time.sleep(15)
    connect_wifi()
    for _ntp in range(3):
        try:
            ntptime.settime(); print("[NTP] Sync OK"); break
        except Exception as e:
            print("[NTP] Attempt", _ntp + 1, "failed:", e); time.sleep(2)
    sync_latest()
    fetch_weather()
    fetch_session()
    state["time_str"], state["date_str"] = get_time_strings()
    read_sensors()
    update_leds()
    draw_main_screen()
    global _main_needs_full_redraw
    _main_needs_full_redraw = False
    print("[BOOT] Done.")

# ============================================================
# MAIN LOOP
# ============================================================

def loop():
    """
    Main event loop.
    FIX 1: smart_update_main_screen() replaces draw_main_screen() for
    periodic redraws — only changed zones are repainted.
    FIX 2: connect_to_network() handles WiFi fallback internally.
    FIX 3: gc.collect() before each network call prevents memory
    fragmentation from silently breaking fetch_session() after
    long runtimes.
    """
    global last_motion_time, _main_needs_full_redraw
    last_sensor  = 0; last_bq      = 0; last_weather = 0
    last_session = 0; last_clock   = 0; last_draw    = 0; last_ntp = 0

    while True:
        now = time.time()

        if now - last_clock >= 1:
            state["time_str"], state["date_str"] = get_time_strings()
            last_clock = now

        try:
            state["motion"] = bool(pir.value())
            if state["motion"]: last_motion_time = now
        except: pass

        if now - last_ntp >= 3600:
            try: ntptime.settime()
            except: pass
            last_ntp = now

        if now - last_sensor >= SENSOR_INTERVAL:
            read_sensors(); update_leds(); last_sensor = now

        if now - last_bq >= BQ_INTERVAL:
            post_indoor(); last_bq = now

        if now - last_weather >= WEATHER_INTERVAL:
            fetch_weather(); last_weather = now

        if now - last_session >= SESSION_INTERVAL:
            fetch_session(); last_session = now

        check_alerts()
        handle_buttons()

        if now - last_draw >= DRAW_INTERVAL:
            if current_screen == 0:
                if _main_needs_full_redraw:
                    # Full redraw when returning from another screen
                    draw_main_screen()
                    _main_needs_full_redraw = False
                else:
                    # Partial update — only changed zones repainted
                    smart_update_main_screen()
            elif current_screen == 3:
                # Forecast: only redraw when data changed or first entry
                # (data changes every 30 min via fetch_weather)
                # Without this flag, draw_forecast_screen() was called
                # every DRAW_INTERVAL causing a full screen flash.
                if _forecast_needs_redraw:
                    draw_forecast_screen()
                    _forecast_needs_redraw = False
            elif current_screen == 4:
                # WiFi: only redraw on first entry or after connection attempt
                if _wifi_needs_redraw:
                    draw_wifi_screen()
                    _wifi_needs_redraw = False
            last_draw = now

        gc.collect()
        time.sleep(1)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()