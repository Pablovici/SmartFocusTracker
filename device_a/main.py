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
from m5stack import lcd, btnA, btnB, btnC, speaker
from MediaTrans.MicRecord import MicRecord

# ============================================================
# CONFIG
# ============================================================
MIDDLEWARE_URL   = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_HOST       = "smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_PORT       = 443
NTP_UTC_OFFSET   = 2
SENSOR_INTERVAL  = 30
DRAW_INTERVAL    = 5
HUMIDITY_MIN     = 40
WEATHER_INTERVAL = 600
ALERT_COOLDOWN   = 3600
BREAK_INTERVAL   = 3600
RECORD_SECS      = 5
VOICE_FILE       = '/flash/voice.wav'
RESP_FILE        = '/flash/res/resp.wav'

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

COLOR_SUN   = 0xFFD740
COLOR_RAIN  = 0x4FC3F7
COLOR_STORM = 0xFF5252
COLOR_SNOW  = 0xE8E8E8
COLOR_CLOUD = 0xB0BEC5
COLOR_MIST  = 0x90A4AE

# ============================================================
# SHT30 — Temp & Humidity (Port A: SCL=33, SDA=32)
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
# SGP30 — CO2 & TVOC (Port C: SCL=13, SDA=14)
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
# HARDWARE INIT
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
# Screens: 0=main  1=session  2=answer  3=forecast  4=wifi
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
alert_times    = {"weather": 0, "humidity": 0, "air": 0, "break": 0}
current_screen = 0
last_answer    = ""
last_question  = ""
wifi_sel_idx   = 0

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

def format_seconds(s):
    if not s: return "0min"
    m = int(s // 60); h = int(m // 60); m = m % 60
    return "{}h {}m".format(h, m) if h > 0 else "{}min".format(m)

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
# WEATHER ICONS — drawn with LCD primitives (no image files)
# cx/cy = center of the icon bounding box (~18x18px)
# ============================================================
def _icon_sun(cx, cy):
    # Core circle
    lcd.fillCircle(cx, cy, 5, COLOR_SUN)
    # 8 rays: (inner_x, inner_y, outer_x, outer_y)
    rays = [
        (cx,   cy-6,  cx,   cy-10),
        (cx+4, cy-4,  cx+7, cy-7),
        (cx+6, cy,    cx+10,cy),
        (cx+4, cy+4,  cx+7, cy+7),
        (cx,   cy+6,  cx,   cy+10),
        (cx-4, cy+4,  cx-7, cy+7),
        (cx-6, cy,    cx-10,cy),
        (cx-4, cy-4,  cx-7, cy-7),
    ]
    for x1,y1,x2,y2 in rays:
        lcd.line(x1, y1, x2, y2, COLOR_SUN)

def _icon_cloud(cx, cy, col):
    # Three overlapping circles + filled rect base
    lcd.fillCircle(cx-4, cy+1, 5, col)
    lcd.fillCircle(cx+3, cy-1, 6, col)
    lcd.fillCircle(cx-9, cy+3, 3, col)
    lcd.fillRect(cx-12, cy+3, 22, 6, col)

def _icon_rain(cx, cy):
    _icon_cloud(cx, cy-3, COLOR_CLOUD)
    # Rain drops
    for rx, ry in [(cx-7, cy+6), (cx-2, cy+8), (cx+4, cy+6), (cx+9, cy+8)]:
        lcd.line(rx, ry, rx-2, ry+5, COLOR_RAIN)

def _icon_heavy_rain(cx, cy):
    _icon_cloud(cx, cy-4, 0x607D8B)  # darker cloud
    for rx, ry in [(cx-8,cy+5),(cx-3,cy+7),(cx+2,cy+5),(cx+7,cy+7),(cx-5,cy+10),(cx+4,cy+10)]:
        lcd.line(rx, ry, rx-2, ry+6, COLOR_RAIN)

def _icon_snow(cx, cy):
    # Snowflake: 4 axes through center + center dot
    lcd.line(cx-8, cy,   cx+8, cy,   COLOR_SNOW)
    lcd.line(cx,   cy-8, cx,   cy+8, COLOR_SNOW)
    lcd.line(cx-6, cy-6, cx+6, cy+6, COLOR_SNOW)
    lcd.line(cx-6, cy+6, cx+6, cy-6, COLOR_SNOW)
    lcd.fillCircle(cx, cy, 2, COLOR_SNOW)
    # Tips
    for tx, ty in [(cx-8,cy),(cx+8,cy),(cx,cy-8),(cx,cy+8)]:
        lcd.line(tx-2, ty-2, tx+2, ty+2, COLOR_SNOW)

def _icon_storm(cx, cy):
    _icon_cloud(cx, cy-4, 0x546E7A)  # dark blue-grey cloud
    # Lightning bolt
    lcd.line(cx+1, cy+3, cx-4, cy+10, 0xFFE000)
    lcd.line(cx-4, cy+10, cx+1, cy+10, 0xFFE000)
    lcd.line(cx+1, cy+10, cx-3, cy+16, 0xFFE000)

def _icon_mist(cx, cy):
    # Horizontal dashed lines
    for my in [cy-5, cy-1, cy+3, cy+7]:
        lcd.line(cx-9, my, cx-3, my, COLOR_MIST)
        lcd.line(cx,   my, cx+6, my, COLOR_MIST)
        lcd.line(cx-6, my+2, cx+9, my+2, COLOR_MIST)

def _icon_few_clouds(cx, cy):
    # Small cloud + sun peeking behind
    lcd.fillCircle(cx+4, cy+1, 5, COLOR_SUN)  # sun peek
    lcd.line(cx+4, cy-5, cx+4, cy-8, COLOR_SUN)
    lcd.line(cx+9, cy+1, cx+12, cy+1, COLOR_SUN)
    _icon_cloud(cx-2, cy+2, COLOR_CLOUD)

def draw_weather_icon(cx, cy, cond):
    c = cond.lower()
    if "thunder" in c or "storm" in c:
        _icon_storm(cx, cy)
    elif "snow" in c or "sleet" in c:
        _icon_snow(cx, cy)
    elif "heavy rain" in c or "shower" in c:
        _icon_heavy_rain(cx, cy)
    elif "rain" in c or "drizzle" in c:
        _icon_rain(cx, cy)
    elif "clear" in c or "sun" in c:
        _icon_sun(cx, cy)
    elif "few clouds" in c or "scattered" in c:
        _icon_few_clouds(cx, cy)
    elif "mist" in c or "fog" in c or "haze" in c:
        _icon_mist(cx, cy)
    else:  # clouds / overcast
        _icon_cloud(cx, cy, COLOR_CLOUD)

# ============================================================
# WIFI
# ============================================================
def connect_wifi():
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
    ssid, pwd = KNOWN_NETWORKS[idx]
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Connecting to", 10, 80, COLOR_GREY)
    lcd.print(ssid, 10, 110, COLOR_WHITE)
    wlan.active(True)
    if wlan.isconnected():
        wlan.disconnect()
        time.sleep(1)
    wlan.connect(ssid, pwd)
    for i in range(15):
        lcd.print("." * (i % 4 + 1), 10, 150, COLOR_ACCENT)
        if wlan.isconnected():
            try: ntptime.settime()
            except: pass
            return True
        time.sleep(1)
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
    payload = {
        "temperature": state["temperature"], "humidity": state["humidity"],
        "co2_ppm": state["co2_ppm"], "tvoc_ppb": state["tvoc_ppb"],
        "air_quality_label": state["air_quality_label"],
        "motion_detected": state["motion"],
    }
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
    try:
        r = urequests.get(MIDDLEWARE_URL + "/weather")
        if r.status_code == 200:
            data    = ujson.loads(r.text)
            current = data.get("current", {})
            state["weather_temp"] = int(round(current.get("temperature", 0)))
            state["weather_cond"] = current.get("condition", "N/A")
            state["weather_city"] = current.get("city", "")
            state["forecast"]     = data.get("forecast", [])
        r.close()
    except Exception as e: print("[WEATHER]", e)
    gc.collect()

def fetch_session():
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current")
        if r.status_code == 200:
            d = ujson.loads(r.text)
            state["session_active"]   = d.get("active", False)
            state["session_paused"]   = d.get("paused", False)
            state["session_work_sec"] = d.get("work_seconds", 0)
        r.close()
    except Exception as e: print("[SESSION]", e)
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
        s.settimeout(60)
        s.connect(addr)
        ss = ussl.wrap_socket(s, server_hostname=CLOUD_HOST)
        ss.write(req); ss.write(prefix)
        f = open(filepath, 'rb')
        while True:
            chunk = f.read(384)
            if not chunk: break
            b64 = ubinascii.b2a_base64(chunk)
            if b64[-1] == 10: b64 = b64[:-1]
            ss.write(b64)
            gc.collect()
        f.close(); f = None
        ss.write(suffix)
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
        s.settimeout(30)
        s.connect(addr)
        ss = ussl.wrap_socket(s, server_hostname=CLOUD_HOST)
        ss.write(req)
        header_data = b''
        while b'\r\n\r\n' not in header_data:
            chunk = ss.read(128)
            if not chunk: break
            header_data += chunk
        if b'\r\n\r\n' not in header_data:
            return False, 'bad response'
        header_part, body_start = header_data.split(b'\r\n\r\n', 1)
        status_code = int(header_part.split(b'\r\n')[0].decode().split(' ')[1])
        if status_code != 200:
            return False, 'HTTP ' + str(status_code)
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
        show_msg("Rien entendu\nReessayez")
        time.sleep(2)
        return
    show_msg("Analyse...")
    code, body = _ssl_post_wav_to_ask(VOICE_FILE)
    gc.collect()
    if code is None or code != 200:
        show_msg("Erreur reseau")
        time.sleep(2)
        return
    try:
        resp          = ujson.loads(body)
        answer        = resp.get('answer_text', '')
        last_question = resp.get('question', '')
    except:
        show_msg("Erreur JSON")
        time.sleep(2)
        return
    if not answer:
        show_msg("Pas de reponse\nIA indisponible")
        time.sleep(2)
        return
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
# ALERTS TTS
# ============================================================
def speak(text):
    try:
        r = urequests.post(MIDDLEWARE_URL + "/speak",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"text": text}))
        r.close()
    except Exception as e: print("[TTS]", e)
    gc.collect()

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

# ============================================================
# DISPLAY — MAIN (screen 0)
# BtnA=WiFi  BtnB=Voice  BtnC=Forecast
# ============================================================
def draw_main_screen():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(state["time_str"], 10, 8, COLOR_WHITE)
    lcd.print(state["date_str"], 175, 8, COLOR_GREY)
    wcol = condition_color(state["weather_cond"])
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{}C".format(state["weather_temp"]), 10, 40, wcol)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("{} {}".format(state["weather_cond"], state["weather_city"]), 10, 72, COLOR_GREY)
    lcd.line(0, 100, 320, 100, COLOR_DIVIDER)
    t = state["temperature"]; h = state["humidity"]
    lcd.print("In: {}C  {}%".format(
        "--" if t is None else t,
        "--" if h is None else h), 10, 110, COLOR_WHITE)
    aq = state["air_quality_label"]
    lcd.print("Air: {}".format(aq), 10, 140, air_color(aq))
    if state["session_active"]:
        label = "Paused" if state["session_paused"] else format_seconds(state["session_work_sec"])
        color = COLOR_WARN if state["session_paused"] else COLOR_GOOD
    else:
        label = "No session"; color = COLOR_GREY
    lcd.print("Session: {}".format(label), 10, 170, color)
    lcd.font(lcd.FONT_Default)
    lcd.print("[WiFi]",     10,  220, COLOR_ACCENT)
    lcd.print("[Voice]",    120, 220, COLOR_WARN)
    lcd.print("[Forecast]", 225, 220, wcol)

# ============================================================
# DISPLAY — ANSWER (screen 2)
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
        lcd.print(l, 10, y, COLOR_WHITE)
        y += 20
    lcd.font(lcd.FONT_Default)
    lcd.print("[Back]", 240, 220, COLOR_GREY)

# ============================================================
# DISPLAY — FORECAST (screen 3)
# Layout per row (38px):
#   strip(4px) | day name | [icon 22px] | temp + condition (2 lines)
# ============================================================
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

    td    = today_str()
    y0    = 30    # first row top
    row_h = 38    # 5 rows × 38 = 190px  +  header 30  +  footer 20  = 240 ✓

    for i, day in enumerate(forecast[:5]):
        y    = y0 + i * row_h
        date = day.get("date", "")
        name = date_to_dayname(date, td)
        tmin = int(round(day.get("temp_min", 0)))
        tmax = int(round(day.get("temp_max", 0)))
        cond = day.get("condition", "N/A")
        col  = condition_color(cond)

        # Left color strip
        lcd.fillRect(0, y + 1, 4, row_h - 2, col)

        # Day name (max 5 chars, FONT_DejaVu18)
        lcd.font(lcd.FONT_DejaVu18)
        name_disp = name[:5] if len(name) > 5 else name
        lcd.print(name_disp, 8, y + 10, COLOR_WHITE)

        # Weather icon centered at x=80, vertically centered in row
        draw_weather_icon(80, y + row_h // 2, cond)

        # Temperature range — line 1
        lcd.font(lcd.FONT_Default)
        lcd.print("{}~{}C".format(tmin, tmax), 100, y + 9, col)

        # Condition text — line 2 (max 20 chars)
        cond_disp = cond[:20] if len(cond) > 20 else cond
        lcd.print(cond_disp, 100, y + 22, COLOR_GREY)

        # Row separator (skip after last)
        if i < 4:
            lcd.line(4, y + row_h, 320, y + row_h, COLOR_DIVIDER)

    lcd.font(lcd.FONT_Default)
    lcd.print("[Back]", 10, 220, COLOR_GREY)

# ============================================================
# DISPLAY — WIFI (screen 4)
# ============================================================
def draw_wifi_screen():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("WiFi", 10, 8, COLOR_WHITE)
    if wlan.isconnected():
        ssid = wlan.config("essid")
        ip   = wlan.ifconfig()[0]
        lcd.print("Connected", 150, 8, COLOR_GOOD)
        lcd.font(lcd.FONT_Default)
        lcd.print("SSID: {}".format(ssid), 10, 34, COLOR_GREY)
        lcd.print("IP:   {}".format(ip),   10, 48, COLOR_GREY)
    else:
        lcd.print("Disconnected", 130, 8, COLOR_BAD)
    lcd.line(0, 65, 320, 65, COLOR_DIVIDER)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Select network:", 10, 72, COLOR_GREY)
    y = 100
    for i, (ssid, _) in enumerate(KNOWN_NETWORKS):
        if i == wifi_sel_idx:
            lcd.print(">", 10, y, COLOR_ACCENT)
            lcd.print(ssid[:28], 28, y, COLOR_WHITE)
        else:
            lcd.print(" ", 10, y, COLOR_GREY)
            lcd.print(ssid[:28], 28, y, COLOR_GREY)
        y += 32
    lcd.font(lcd.FONT_Default)
    lcd.print("[Back]",    10,  220, COLOR_GREY)
    lcd.print("[Connect]", 110, 220, COLOR_GOOD)
    lcd.print("[Next]",    250, 220, COLOR_ACCENT)

# ============================================================
# BUTTONS
# ============================================================
def handle_buttons():
    global current_screen, wifi_sel_idx

    if current_screen == 4:        # WiFi
        if btnA.wasPressed():
            current_screen = 0
        if btnB.wasPressed():
            ok = connect_to_network(wifi_sel_idx)
            draw_wifi_screen()
            lcd.font(lcd.FONT_DejaVu18)
            lcd.print("Connected!" if ok else "Failed!", 80, 140,
                      COLOR_GOOD if ok else COLOR_BAD)
            time.sleep(1)
            draw_wifi_screen()
        if btnC.wasPressed():
            wifi_sel_idx = (wifi_sel_idx + 1) % len(KNOWN_NETWORKS)
            draw_wifi_screen()

    elif current_screen == 3:      # Forecast
        if btnA.wasPressed():
            current_screen = 0

    elif current_screen == 2:      # Answer
        if btnA.wasPressed():
            current_screen = 0

    else:                           # Main (0)
        if btnA.wasPressed():
            current_screen = 4     # → WiFi
            draw_wifi_screen()
        if btnB.wasPressed():
            voice_flow()
        if btnC.wasPressed():
            current_screen = 3     # → Forecast
            draw_forecast_screen()

# ============================================================
# BOOT
# ============================================================
def boot():
    show_msg("Booting...")
    time.sleep(1)
    show_msg("Warming up\nair sensor...")
    time.sleep(15)
    connect_wifi()
    try: ntptime.settime()
    except: pass
    fetch_weather()
    fetch_session()
    state["time_str"], state["date_str"] = get_time_strings()
    read_sensors()
    draw_main_screen()
    print("[BOOT] Done.")

# ============================================================
# MAIN LOOP
# ============================================================
def loop():
    last_sensor = 0; last_weather = 0; last_session = 0
    last_clock  = 0; last_draw    = 0
    while True:
        now = time.time()
        if now - last_clock >= 1:
            state["time_str"], state["date_str"] = get_time_strings()
            last_clock = now
        if now - last_sensor >= SENSOR_INTERVAL:
            read_sensors(); post_indoor(); last_sensor = now
        if now - last_weather >= WEATHER_INTERVAL:
            fetch_weather(); last_weather = now
        if now - last_session >= 5:
            fetch_session(); last_session = now
        check_alerts()
        handle_buttons()
        if now - last_draw >= DRAW_INTERVAL:
            if   current_screen == 0: draw_main_screen()
            elif current_screen == 3: draw_forecast_screen()
            elif current_screen == 4: draw_wifi_screen()
            last_draw = now
        gc.collect()
        time.sleep(1)

boot()
loop()
