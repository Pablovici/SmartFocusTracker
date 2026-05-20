# device_a/main2.py — production v3  Liquid Glass DA
# All sensors / voice / alerts / BQ + new iOS-style Liquid Glass UI
# MicroPython — deployed via UIFlow 1.0

import gc, os, time, ntptime, network, usocket, ussl, ubinascii, urequests, ujson
from machine import I2C, Pin
from m5stack import lcd, btnA, btnB, btnC, speaker, rgb
from MediaTrans.MicRecord import MicRecord

# ============================================================
# CONFIGURATION
# ============================================================
MIDDLEWARE_URL  = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_HOST      = "smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_PORT      = 443
NTP_UTC_OFFSET  = 2
SENSOR_INTERVAL = 10
BQ_INTERVAL     = 30
DRAW_INTERVAL   = 2
HUMIDITY_MIN    = 40
HUMIDITY_MAX    = 60
WEATHER_INTERVAL= 1800
ALERT_COOLDOWN  = 3600
BREAK_INTERVAL  = 2700
RECORD_SECS     = 3
GREET_COOLDOWN  = 3600
SESSION_INTERVAL= 5
VOICE_FILE      = '/flash/voice.wav'
RESP_FILE       = '/flash/res/resp.wav'
ALERT_WAV_BREAK       = '/flash/res/alert_break.wav'
ALERT_WAV_AIR         = '/flash/res/alert_air.wav'
ALERT_WAV_HUMID_HIGH  = '/flash/res/alert_humid_high.wav'
ALERT_TEXT_BREAK      = "Vous travaillez depuis 45 minutes. Il est temps de faire une pause !"
ALERT_TEXT_AIR        = "La qualite de l air est mauvaise. Pensez a aerer la piece."
ALERT_TEXT_HUMID_HIGH = "L air est trop humide. Pensez a ventiler la piece pour eviter les moisissures."

KNOWN_NETWORKS = [
    ("iPhone de Pablo", "1234567890"),
    ("iot-unil",        "4u6uch4hpY9pJ2f9"),
]

# ============================================================
# SETTINGS
# ============================================================
SETTINGS_FILE  = '/flash/settings.json'
SENSOR_OPTIONS = [5, 10, 30]
BQ_OPTIONS     = [30, 60, 300]
BREAK_OPTIONS  = [1800, 2700, 3600]
PARAM_DEFS = [
    ("Sensor reading", "sensor_interval", SENSOR_OPTIONS, ["5s",  "10s", "30s"]),
    ("BigQuery send",  "bq_interval",     BQ_OPTIONS,     ["30s", "1min","5min"]),
    ("Break reminder", "break_interval",  BREAK_OPTIONS,  ["30m", "45m", "60m"]),
]
settings = {
    "sensor_interval": SENSOR_INTERVAL,
    "bq_interval":     BQ_INTERVAL,
    "break_interval":  BREAK_INTERVAL,
}

CARD_NAMES = {}

# ============================================================
# PALETTE  — Liquid Glass
# Glass = lerp(background, white, 0.50) — pre-computed alpha
# ============================================================
C_BG1 = 0x1D4883; C_BG2 = 0x173765; C_BG3 = 0x102746

C_GLASS   = 0x8EA4C1
C_GLASS_B = 0xCDD7E4
C_GLASS_H = 0xEDF0F5

C_CC_BG   = 0x102748
C_CC_TILE = 0x838FA0

C_SEP     = 0x2A4A70

C_TXT1    = 0x0C1E36
C_TXT2    = 0x233E65
C_TXT3    = 0x4B6D9C

C_L1      = 0xFFFFFF
C_L2      = 0xA8C0E0
C_L3      = 0x5070A0

C_BLUE    = 0x0493F8
C_GREEN   = 0x089744
C_AMBER   = 0xE77706
C_TEAL    = 0x007A90
C_LAVEND  = 0x9333F2
C_GOLD    = 0xAA8800
C_CORAL   = 0xCC2A38

C_BLUE_L   = 0x65BFFF
C_GREEN_L  = 0x48F38F
C_AMBER_L  = 0xFFAD5B
C_LAVEND_L = 0xC895FB

# Legacy aliases used by connect_to_network / weather icons
COLOR_BG      = C_BG1
COLOR_WHITE   = C_L1
COLOR_GREY    = C_L2
COLOR_DIVIDER = C_SEP
COLOR_GOOD    = C_GREEN_L
COLOR_WARN    = C_AMBER_L
COLOR_BAD     = C_CORAL
COLOR_ACCENT  = C_BLUE_L
COLOR_GREY_DIM      = C_L3
COLOR_CARD_ACTIVE   = 0x1A3A5A
COLOR_CARD_INACTIVE = 0x102748
COLOR_SUN   = C_GOLD
COLOR_RAIN  = C_BLUE_L
COLOR_STORM = C_CORAL
COLOR_SNOW  = C_L1
COLOR_CLOUD = C_L2
COLOR_MIST  = C_TXT3

DEG = chr(176)

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
try:    i2c_a = I2C(1, scl=Pin(33), sda=Pin(32), freq=100000)
except Exception as e: print("[HW] i2c_a:", e); i2c_a = None

try:    i2c_c = I2C(scl=Pin(13), sda=Pin(14), freq=100000)
except Exception as e: print("[HW] i2c_c:", e); i2c_c = None

try:    env  = SHT30(i2c_a) if i2c_a else None
except Exception as e: print("[HW] SHT30:", e); env = None

try:    tvoc = SGP30(i2c_c) if i2c_c else None
except Exception as e: print("[HW] SGP30:", e); tvoc = None

try:    pir  = Pin(26, Pin.IN)
except Exception as e: print("[HW] PIR:", e); pir = None

try:
    i2c_touch = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
    print("[HW] FT6336U touch OK")
except Exception as e: print("[HW] Touch:", e); i2c_touch = None

wlan = network.WLAN(network.STA_IF)

try:    mic = MicRecord()
except Exception as e: print("[HW] MicRecord:", e); mic = None

try:    os.mkdir('/flash/res')
except: pass

# ============================================================
# STATE
# Screens: 0=home  2=voice  3=forecast  4=wifi
#          5=settings  6=sensor_settings  7=sensor_detail  8=session_detail
# ============================================================
state = {
    "temperature": None, "humidity": None,
    "co2_ppm": None, "tvoc_ppb": None,
    "air_quality_label": "Unknown", "motion": False,
    "weather_temp": "--", "weather_cond": "N/A", "weather_city": "",
    "forecast": [],
    "session_active": False, "session_paused": False, "session_work_sec": 0,
    "session_false_count": 0, "session_card_id": None,
    "time_str": "--:--", "date_str": "---",
}

alert_times = {
    "humidity":     -ALERT_COOLDOWN,
    "humidity_high":-ALERT_COOLDOWN,
    "air":          -ALERT_COOLDOWN,
    "break":        -ALERT_COOLDOWN,
    "motion_greet": -GREET_COOLDOWN,
}
last_motion_time  = 0
_pir_prev         = False
current_screen    = 0
last_answer       = ""
last_question     = ""
_ntp_synced       = False
_sensor_param_idx = 0
_touch_start      = None
_touch_done       = False
_panel_open       = False
_main_needs_full_redraw = True

_last_main = {
    "time_str": None, "date_str": None,
    "weather_temp": None, "weather_cond": None,
    "temperature": None, "humidity": None,
    "session_active": None, "session_paused": None,
}

# ============================================================
# HELPERS
# ============================================================
def classify_air(co2):
    if co2 is None: return "Unknown"
    if co2 < 800:   return "Good"
    if co2 < 1000:  return "Moderate"
    return "Poor"

def air_color(label):
    if label == "Good":     return C_GREEN_L
    if label == "Moderate": return C_AMBER_L
    return C_CORAL

def wcol(cond):
    c = cond.lower()
    if "thunder" in c or "storm" in c: return C_CORAL
    if "snow"    in c:                 return C_TXT2
    if "rain"    in c or "shower" in c:return C_BLUE
    if "clear"   in c or "sun"    in c:return C_GOLD
    if "cloud"   in c:                 return C_TXT3
    return C_TXT1

def condition_color(cond):
    c = cond.lower()
    if "thunder" in c or "storm" in c: return C_CORAL
    if "snow"    in c:                 return C_L1
    if "rain"    in c or "shower" in c:return C_BLUE_L
    if "clear"   in c or "sun"    in c:return C_GOLD
    if "cloud"   in c:                 return C_L2
    if "mist"    in c or "fog"    in c:return C_TXT3
    return C_L1

def _wfr(cond):
    c = cond.lower()
    if "cloud"   in c:                  return "Nuageux"
    if "clear"   in c or "sun"    in c: return "Ensoleille"
    if "rain"    in c or "shower" in c: return "Pluie"
    if "snow"    in c:                  return "Neige"
    if "thunder" in c or "storm"  in c: return "Orage"
    return cond

def _cx(text, fw, x, w):
    return x + max(0, (w - len(text) * fw) // 2)

def _bold(text, x, y, col):
    lcd.print(text, x,     y, col)
    lcd.print(text, x + 1, y, col)

def get_time_strings_short():
    t = time.localtime(time.time() + NTP_UTC_OFFSET * 3600)
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    return "{:02d}:{:02d}".format(t[3], t[4]), "{} {:02d}".format(days[t[6]], t[2])

def file_size(path):
    try:    return os.stat(path)[6]
    except: return 0

def safe_remove(path):
    try:    os.remove(path)
    except: pass

def today_str():
    t = time.localtime(time.time() + NTP_UTC_OFFSET * 3600)
    return "{:04d}-{:02d}-{:02d}".format(t[0], t[1], t[2])

def date_to_dayname(date_str, today):
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    if date_str == today: return "Today"
    parts = date_str.split("-")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    ts   = time.mktime((y, m, d, 12, 0, 0, 0, 0))
    return days[time.localtime(ts)[6]]

def _comfort_label():
    aq = state["air_quality_label"]
    h  = state["humidity"]
    t  = state["temperature"]
    if aq == "Poor":                    return "Open a window",    C_CORAL
    if aq == "Moderate":                return "Air getting stuffy",C_AMBER_L
    if h is not None and h < 35:        return "Air is dry",       C_AMBER_L
    if h is not None and h > 65:        return "A bit humid",      C_AMBER_L
    if t is not None and t > 26:        return "A bit warm",       C_AMBER_L
    if t is not None and t < 18:        return "A bit cold",       C_AMBER_L
    return "Great to work", C_GREEN_L

# ============================================================
# SETTINGS LOAD / SAVE
# ============================================================
def load_settings():
    try:
        f = open(SETTINGS_FILE, 'r')
        d = ujson.loads(f.read()); f.close()
        for k in settings:
            if k in d: settings[k] = d[k]
        print("[SETTINGS] Loaded:", settings)
    except: print("[SETTINGS] Using defaults")

def save_settings():
    try:
        f = open(SETTINGS_FILE, 'w')
        f.write(ujson.dumps(settings)); f.close()
        print("[SETTINGS] Saved")
    except Exception as e: print("[SETTINGS] Save failed:", e)

# ============================================================
# NTP SYNC
# ============================================================
def _sync_ntp():
    global _ntp_synced
    for srv in ["pool.ntp.org", "time.google.com", "time.cloudflare.com"]:
        try:
            try: ntptime.host = srv
            except: pass
            ntptime.settime(); _ntp_synced = True
            print("[NTP] Synced via", srv); return True
        except Exception as e: print("[NTP]", srv, "failed:", e); time.sleep(2)
    _ntp_synced = False; return False

def _sync_time_http():
    global _ntp_synced
    try:
        gc.collect()
        r = urequests.get(MIDDLEWARE_URL + "/time")
        if r.status_code == 200:
            d = ujson.loads(r.text); r.close()
            from machine import RTC
            RTC().datetime((d["year"],d["month"],d["day"],d["weekday"],
                            d["hour"],d["minute"],d["second"],0))
            _ntp_synced = True
            print("[TIME] Set via HTTP"); return True
        r.close()
    except Exception as e: print("[TIME] HTTP failed:", e)
    return False

# ============================================================
# HARDWARE READS — wifi bars, battery, touch
# ============================================================
def _read_wifi_bars():
    if not wlan.isconnected(): return 0
    try:
        rssi = wlan.status('rssi')
        if rssi >= -55: return 4
        if rssi >= -67: return 3
        if rssi >= -80: return 2
        return 1
    except: return 0

def _read_battery_pct():
    try:
        i2c_a.writeto(0x34, bytes([0x78]))
        data = i2c_a.readfrom(0x34, 2)
        raw = ((data[0] & 0x7F) << 4) | (data[1] & 0x0F)
        return max(0, min(100, int((raw * 1.1 - 3000) * 100 / 1200)))
    except: return None

def read_touch_xy():
    if i2c_touch is None: return None
    try:
        data = i2c_touch.readfrom_mem(0x38, 0x02, 5)
        n = data[0] & 0x0F
        if n == 0: return None
        x = ((data[1] & 0x0F) << 8) | data[2]
        y = ((data[3] & 0x0F) << 8) | data[4]
        return (x, y)
    except: return None

# ============================================================
# WEATHER ICONS  (drawn on dark bg — use light colors)
# ============================================================
def _icon_sun(cx, cy):
    lcd.fillCircle(cx, cy, 5, COLOR_SUN)
    for x1,y1,x2,y2 in [(cx,cy-6,cx,cy-10),(cx+4,cy-4,cx+7,cy-7),(cx+6,cy,cx+10,cy),
                         (cx+4,cy+4,cx+7,cy+7),(cx,cy+6,cx,cy+10),(cx-4,cy+4,cx-7,cy+7),
                         (cx-6,cy,cx-10,cy),(cx-4,cy-4,cx-7,cy-7)]:
        lcd.line(x1,y1,x2,y2,COLOR_SUN)

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
    if   "thunder" in c or "storm"     in c: _icon_storm(cx,cy)
    elif "snow"    in c or "sleet"     in c: _icon_snow(cx,cy)
    elif "heavy rain" in c or "shower" in c: _icon_heavy_rain(cx,cy)
    elif "rain"    in c or "drizzle"   in c: _icon_rain(cx,cy)
    elif "clear"   in c or "sun"       in c: _icon_sun(cx,cy)
    elif "few clouds" in c or "scattered" in c: _icon_few_clouds(cx,cy)
    elif "mist"    in c or "fog"       in c: _icon_mist(cx,cy)
    else:                                    _icon_cloud(cx,cy,COLOR_CLOUD)

# ============================================================
# WIFI CONNECT
# ============================================================
def show_msg(msg):
    _draw_bg()
    _card_base(10, 90, 300, 60)
    lcd.font(lcd.FONT_Default)
    lines = msg.split("\n")
    y = 108 if len(lines) > 1 else 115
    for l in lines:
        lcd.print(l, _cx(l, 6, 10, 300), y, C_TXT1); y += 16

def connect_wifi():
    wlan.active(True)
    if wlan.isconnected(): return True
    for ssid, pwd in KNOWN_NETWORKS:
        show_msg("WiFi:\n{}".format(ssid))
        wlan.connect(ssid, pwd)
        for _ in range(15):
            if wlan.isconnected():
                show_msg("Connected!")
                time.sleep(1); return True
            time.sleep(1)
    show_msg("No WiFi found")
    return False

def connect_to_network(idx):
    for attempt, try_idx in enumerate([idx, 1 - idx]):
        ssid, pwd = KNOWN_NETWORKS[try_idx]
        _draw_bg()
        lcd.font(lcd.FONT_DejaVu18)
        if attempt > 0: lcd.print("Not found, trying:", 10, 60, C_AMBER_L)
        else:           lcd.print("Connecting to:", 10, 80, C_L2)
        lcd.print(ssid, 10, 110, C_L1)
        wlan.active(True)
        if wlan.isconnected(): wlan.disconnect(); time.sleep(1)
        wlan.connect(ssid, pwd)
        for i in range(15):
            lcd.fillRect(10, 148, 120, 20, C_BG2)
            lcd.print("." * (i % 4 + 1), 10, 150, C_BLUE_L)
            if wlan.isconnected():
                try: ntptime.settime()
                except: pass
                lcd.print("Connected!", 10, 180, C_GREEN_L)
                time.sleep(1); return True
            time.sleep(1)
        lcd.print("Failed.", 10, 180, C_CORAL)
        time.sleep(1)
    _draw_bg()
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("No WiFi available", 10, 110, C_CORAL)
    time.sleep(2); return False

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
    try:   state["motion"] = bool(pir.value())
    except Exception as e: print("[PIR]", e)
    state["air_quality_label"] = classify_air(state["co2_ppm"])

def post_indoor():
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
        r.close()
    except Exception as e: print("[WEATHER]", e)
    gc.collect()

def fetch_session():
    gc.collect()
    try:
        r = urequests.get(MIDDLEWARE_URL + "/session/current")
        if r.status_code == 200:
            d = ujson.loads(r.text)
            server_active = d.get("active", False)
            server_paused = d.get("paused", False)
            if state["session_active"] and not server_active:
                state["session_false_count"] += 1
                if state["session_false_count"] < 3:
                    r.close(); gc.collect(); return
            else:
                state["session_false_count"] = 0
            state["session_active"]   = server_active
            state["session_paused"]   = server_paused
            state["session_work_sec"] = d.get("work_seconds", 0)
            state["session_card_id"]  = d.get("card_id")
        r.close()
    except Exception as e: print("[SESSION]", e)
    gc.collect()

def sync_latest():
    gc.collect()
    try:
        r = urequests.get(MIDDLEWARE_URL + "/latest")
        if r.status_code == 200:
            d = ujson.loads(r.text)
            if d.get("temperature") is not None: state["temperature"] = round(d["temperature"], 1)
            if d.get("humidity")    is not None: state["humidity"]    = round(d["humidity"], 1)
            if d.get("co2_ppm")     is not None: state["co2_ppm"]     = d["co2_ppm"]
            if d.get("tvoc_ppb")    is not None: state["tvoc_ppb"]    = d["tvoc_ppb"]
            if d.get("air_quality_label"):        state["air_quality_label"] = d["air_quality_label"]
            state["motion"] = bool(d.get("motion_detected", False))
        r.close()
    except Exception as e: print("[SYNC]", e)
    gc.collect()

# ============================================================
# HTTPS SOCKET — STT
# ============================================================
def _ssl_post_wav_transcribe(filepath):
    sz = file_size(filepath)
    if sz <= 0: return None, 'empty file'
    prefix   = b'{"audio_b64":"'; suffix = b'"}'
    b64_len  = ((sz + 2) // 3) * 4
    body_len = len(prefix) + b64_len + len(suffix)
    req = ('POST /voice/transcribe HTTP/1.1\r\nHost: ' + CLOUD_HOST +
           '\r\nContent-Type: application/json\r\nContent-Length: ' +
           str(body_len) + '\r\nConnection: close\r\n\r\n').encode('utf-8')
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
        return status_code, parts[1].decode('utf-8') if len(parts) > 1 else ''
    except Exception as e: return None, str(e)
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
# HTTPS SOCKET — stream response WAV to file
# ============================================================
def _ssl_post_to_wav_file(path, payload_dict, out_file):
    body = ujson.dumps(payload_dict).encode('utf-8')
    req  = ('POST ' + path + ' HTTP/1.1\r\nHost: ' + CLOUD_HOST +
            '\r\nContent-Type: application/json\r\nContent-Length: ' +
            str(len(body)) + '\r\nConnection: close\r\n\r\n').encode('utf-8') + body
    s = ss = f = None
    try:
        addr = usocket.getaddrinfo(CLOUD_HOST, CLOUD_PORT, 0, usocket.SOCK_STREAM)[0][-1]
        s  = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
        s.settimeout(30); s.connect(addr)
        ss = ussl.wrap_socket(s, server_hostname=CLOUD_HOST)
        ss.write(req)
        hdata = b''
        while b'\r\n\r\n' not in hdata:
            chunk = ss.read(128)
            if not chunk: break
            hdata += chunk
        if b'\r\n\r\n' not in hdata: return False, 'bad response'
        hpart, bstart = hdata.split(b'\r\n\r\n', 1)
        code = int(hpart.split(b'\r\n')[0].decode().split(' ')[1])
        if code != 200: return False, 'HTTP ' + str(code)
        safe_remove(out_file)
        f = open(out_file, 'wb')
        if bstart: f.write(bstart)
        while True:
            chunk = ss.read(512)
            if not chunk: break
            f.write(chunk)
        f.close(); f = None; return True, 'ok'
    except Exception as e: return False, str(e)
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
# HTTPS SOCKET — LLM + TTS combined
# ============================================================
def _ssl_post_text_to_wav(question, context, out_file):
    body = ujson.dumps({"question": question, "context": context}).encode('utf-8')
    req  = ('POST /voice/respond HTTP/1.1\r\nHost: ' + CLOUD_HOST +
            '\r\nContent-Type: application/json\r\nContent-Length: ' +
            str(len(body)) + '\r\nConnection: close\r\n\r\n').encode('utf-8') + body
    s = ss = f = None
    try:
        addr = usocket.getaddrinfo(CLOUD_HOST, CLOUD_PORT, 0, usocket.SOCK_STREAM)[0][-1]
        s = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
        s.settimeout(60); s.connect(addr)
        ss = ussl.wrap_socket(s, server_hostname=CLOUD_HOST)
        ss.write(req)
        hdata = b''
        while b'\r\n\r\n' not in hdata:
            chunk = ss.read(256)
            if not chunk: break
            hdata += chunk
        if b'\r\n\r\n' not in hdata: return False, '', 'bad response'
        hpart, bstart = hdata.split(b'\r\n\r\n', 1)
        code   = int(hpart.split(b'\r\n')[0].decode().split(' ')[1])
        answer = ''
        for line in hpart.split(b'\r\n'):
            try:
                l = line.decode('utf-8')
                if l.lower().startswith('x-answer:'): answer = l[9:].strip()
            except: pass
        if code != 200: return False, answer, 'HTTP ' + str(code)
        safe_remove(out_file)
        f = open(out_file, 'wb')
        if bstart: f.write(bstart)
        while True:
            chunk = ss.read(512)
            if not chunk: break
            f.write(chunk)
        f.close(); f = None; return True, answer, 'ok'
    except Exception as e: return False, '', str(e)
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
# VOICE HELPERS
# ============================================================
def _build_sensor_context():
    s = state; parts = []
    if s["temperature"] is not None: parts.append("Temp: {}C".format(s["temperature"]))
    if s["humidity"]    is not None: parts.append("Humidity: {}%".format(s["humidity"]))
    if s["co2_ppm"]     is not None: parts.append("CO2: {}ppm".format(s["co2_ppm"]))
    if s["air_quality_label"]:        parts.append("Air: {}".format(s["air_quality_label"]))
    parts.append("Outdoor: {}, {}C".format(s["weather_cond"], s["weather_temp"]))
    if s["session_active"]:
        parts.append("Session: {}min worked".format(int(s["session_work_sec"] // 60)))
    return ", ".join(parts)

def bip(freq=1200):
    try: speaker.sing(freq, 1, 200)
    except:
        try: speaker.playTone(freq, 1)
        except: pass

# ============================================================
# ALERTS & LEDS
# ============================================================
def _alert_overlay(text):
    lcd.fillRect(0, 68, 320, 104, 0x2A1000)
    lcd.line(0, 68, 320, 68, C_AMBER)
    lcd.line(0, 172, 320, 172, C_AMBER)
    lcd.font(lcd.FONT_DejaVu18)
    tw = len("! ALERTE !") * 11
    lcd.print("! ALERTE !", (320 - tw) // 2, 76, C_AMBER_L)
    lcd.font(lcd.FONT_Default)
    words = text.split(" "); lines = []; line = ""
    for w in words:
        if len(line) + len(w) + 1 <= 46: line = line + " " + w if line else w
        else: lines.append(line); line = w
    if line: lines.append(line)
    y = 106
    for l in lines[:4]: lcd.print(l, 10, y, C_L1); y += 14

def _play_alert_wav(wav_path):
    rel = wav_path.replace('/flash/', '')
    try: speaker.playWAV(rel, volume=8)
    except Exception as e: print("[ALERT WAV]", e)

def _log_alert_bq(alert_type, message):
    try:
        r = urequests.post(MIDDLEWARE_URL + "/alert/log",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"alert_type": alert_type, "message": message}))
        r.close()
    except Exception as e: print("[ALERT LOG]", e)

def speak_alert_cached(wav_file, display_text):
    global _main_needs_full_redraw
    _alert_overlay(display_text); bip(900)
    _play_alert_wav(wav_file)
    _log_alert_bq("DEVICE_ALERT", display_text)
    gc.collect(); _main_needs_full_redraw = True

def speak_alert(text):
    global _main_needs_full_redraw
    _alert_overlay(text); bip(900); gc.collect()
    ok, _ = _ssl_post_to_wav_file('/speak-wav', {'text': text}, RESP_FILE)
    if ok:
        try: speaker.playWAV('res/resp.wav', volume=8)
        except Exception as e: print("[ALERT TTS]", e)
    _log_alert_bq("DEVICE_ALERT", text)
    gc.collect(); _main_needs_full_redraw = True

def _ensure_alert_wavs():
    for wav_path, text in [
        (ALERT_WAV_BREAK,      ALERT_TEXT_BREAK),
        (ALERT_WAV_AIR,        ALERT_TEXT_AIR),
        (ALERT_WAV_HUMID_HIGH, ALERT_TEXT_HUMID_HIGH),
    ]:
        try:
            os.stat(wav_path); print("[ALERT] Found:", wav_path)
        except:
            print("[ALERT] Downloading:", wav_path)
            ok, msg = _ssl_post_to_wav_file('/speak-wav', {'text': text}, wav_path)
            print("[ALERT]", "OK" if ok else "FAIL: " + msg)

def update_leds():
    label = state["air_quality_label"]
    if label == "Good":       rgb.setColorAll(0x00CC00)
    elif label == "Moderate": rgb.setColorAll(0xFFAA00)
    elif label == "Poor":     rgb.setColorAll(0xFF0000)
    else:                     rgb.setColorAll(0x000000)

# ============================================================
# MOTION GREETING
# ============================================================
def _build_greeting_text():
    parts = []
    cond = state["weather_cond"]; temp = state["weather_temp"]
    parts.append("Dehors : {}, {}C.".format(cond, temp))
    c = cond.lower()
    if "rain" in c or "drizzle" in c or "shower" in c or "thunder" in c or "storm" in c:
        parts.append("Pensez a prendre un parapluie.")
    if state["air_quality_label"] == "Poor":
        parts.append("Qualite de l air mauvaise, pensez a aerer.")
    h = state["humidity"]
    if h is not None and h < HUMIDITY_MIN:
        parts.append("Humidite interieure basse : {}%.".format(int(h)))
    elif h is not None and h > HUMIDITY_MAX:
        parts.append("Humidite elevee : {}%.".format(int(h)))
    return " ".join(parts)

def _motion_greet_overlay(name, summary):
    lcd.fillRect(0, 56, 320, 116, 0x001A0D)
    lcd.line(0, 56,  320, 56,  C_GREEN_L)
    lcd.line(0, 172, 320, 172, C_GREEN_L)
    lcd.font(lcd.FONT_DejaVu18)
    greeting = "Bonjour {} !".format(name) if name else "Bonjour !"
    lcd.print(greeting, 10, 64, C_GREEN_L)
    lcd.font(lcd.FONT_Default)
    words = summary.split(" "); lines = []; line = ""
    for w in words:
        if len(line) + len(w) + 1 <= 46: line = line + " " + w if line else w
        else: lines.append(line); line = w
    if line: lines.append(line)
    y = 98
    for l in lines[:4]: lcd.print(l, 10, y, C_L1); y += 14

def speak_motion_greet():
    global _main_needs_full_redraw
    name    = CARD_NAMES.get(state["session_card_id"], "") if state["session_card_id"] else ""
    summary = _build_greeting_text()
    salut   = "Bonjour {} ! ".format(name) if name else "Bonjour ! "
    full_text = salut + summary
    _motion_greet_overlay(name, summary); gc.collect()
    ok, _ = _ssl_post_to_wav_file('/speak-wav', {'text': full_text}, RESP_FILE)
    if ok:
        try: speaker.playWAV('res/resp.wav', volume=8)
        except Exception as e: print("[GREET]", e)
    _log_alert_bq("MOTION_GREET", full_text)
    gc.collect(); _main_needs_full_redraw = True

def check_alerts():
    now = time.time()
    if state["session_active"] and not state["session_paused"]:
        if state["session_work_sec"] >= settings["break_interval"]:
            if now - alert_times["break"] > ALERT_COOLDOWN:
                speak_alert_cached(ALERT_WAV_BREAK, ALERT_TEXT_BREAK)
                alert_times["break"] = now
    if state["air_quality_label"] == "Poor":
        if now - alert_times["air"] > ALERT_COOLDOWN:
            speak_alert_cached(ALERT_WAV_AIR, ALERT_TEXT_AIR)
            alert_times["air"] = now
    h = state["humidity"]
    if h is not None and h < HUMIDITY_MIN:
        if now - alert_times["humidity"] > ALERT_COOLDOWN:
            speak_alert("L air est trop sec, {}% d humidite. "
                        "Pensez a humidifier la piece.".format(int(h)))
            alert_times["humidity"] = now
    if h is not None and h > HUMIDITY_MAX:
        if now - alert_times["humidity_high"] > ALERT_COOLDOWN:
            speak_alert_cached(ALERT_WAV_HUMID_HIGH, ALERT_TEXT_HUMID_HIGH)
            alert_times["humidity_high"] = now
    global _pir_prev
    pir_now = state["motion"]
    # motion greet disabled — re-enable by uncommenting the block below
    # if pir_now and not _pir_prev:
    #     if current_screen == 0:
    #         if now - alert_times["motion_greet"] > GREET_COOLDOWN:
    #             speak_motion_greet()
    #             alert_times["motion_greet"] = now
    _pir_prev = pir_now

# ============================================================
# GLASS DRAW HELPERS
# ============================================================
def _draw_bg():
    lcd.fillRect(0,   0, 320,  80, C_BG1)
    lcd.fillRect(0,  80, 320,  80, C_BG2)
    lcd.fillRect(0, 160, 320,  80, C_BG3)

def _card_base(x, y, w, h):
    lcd.fillRoundRect(x, y, w, h, 10, C_GLASS)
    lcd.drawRoundRect(x, y, w, h, 10, C_GLASS_B)
    lcd.fillRect(x + 5, y + 1, w - 10, 2, C_GLASS_H)

def _tag(x, y, text):
    lcd.font(lcd.FONT_Default)
    _bold(text, x + 8, y + 8, C_TXT2)

def _erase_card(x, y, w, h):
    for by_s, by_e, col in [(0,80,C_BG1),(80,160,C_BG2),(160,240,C_BG3)]:
        oy = max(y, by_s); ey = min(y + h, by_e)
        if ey > oy: lcd.fillRect(x, oy, w, ey - oy, col)

def _detail_top(back, title, accent):
    _draw_bg()
    draw_statusbar()
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
    lcd.print(val, max(x + len(label) * 6 + 10, vx), y, vcol)
    lcd.fillRect(x, y + 14, 296, 1, C_SEP)

# ============================================================
# STATUS BAR (real data)
# ============================================================
def draw_statusbar():
    lcd.fillRect(0, 0, 320, 26, C_BG1)
    lcd.fillRect(0, 25, 320, 1, C_SEP)
    lcd.font(lcd.FONT_Default)
    t = state["time_str"]
    lcd.print(t, _cx(t, 6, 0, 320), 9, C_L1)
    # WiFi bars
    bars = _read_wifi_bars()
    for i in range(4):
        h = 3 + i * 3
        lcd.fillRect(10 + i * 5, 22 - h, 3, h, C_L1 if i < bars else C_L3)
    try:    ssid = wlan.config("essid") if wlan.isconnected() else "No WiFi"
    except: ssid = "No WiFi"
    lcd.print(ssid[:10], 34, 9, C_L2 if wlan.isconnected() else C_CORAL)
    pct = _read_battery_pct()
    pct_s = "{}%".format(pct) if pct is not None else "--"
    lcd.print(pct_s, 242, 9, C_L3)
    col = (C_GREEN_L if pct > 30 else C_AMBER_L if pct > 10 else C_CORAL) if pct is not None else C_L3
    lcd.drawRect(272, 8, 22, 11, C_L2)
    lcd.fillRect(294, 11, 2, 5, C_L2)
    if pct is not None:
        fw = max(0, min(18, pct * 18 // 100))
        if fw: lcd.fillRect(274, 10, fw, 7, col)

# ============================================================
# HOME SCREEN — 4 glass cards
# ============================================================
CX1, CX2 = 5, 163
CY1, CY2 = 30, 135
CW,  CH  = 152, 102

def _aq_glass(aq):
    if aq == "Good":     return 0x85B89A
    if aq == "Moderate": return 0xC0A87A
    if aq == "Poor":     return 0xC08888
    return C_GLASS

def _card_base_col(x, y, w, h, fill):
    lcd.fillRoundRect(x, y, w, h, 10, fill)
    lcd.drawRoundRect(x, y, w, h, 10, C_GLASS_B)
    lcd.fillRect(x + 5, y + 1, w - 10, 2, C_GLASS_H)

def _home_outdoor(x, y, w, h):
    _card_base(x, y, w, h)
    _tag(x, y, "OUTDOOR")
    col = wcol(state["weather_cond"])
    lcd.font(lcd.FONT_Default)
    city = state["weather_city"] if state["weather_city"] else "Outdoor"
    lcd.print(city[:12], x + 8, y + 24, C_TXT2)
    lcd.font(lcd.FONT_DejaVu24)
    temp_str = "{}{}C".format(state["weather_temp"], DEG)
    lcd.print(temp_str, x + 8, y + 40, C_TXT1)
    lcd.fillCircle(x + 8 + len(temp_str) * 14 + 6, y + 52, 6, col)
    lcd.font(lcd.FONT_Default)
    lcd.print(_wfr(state["weather_cond"]), x + 8, y + 74, C_TXT3)

def _home_indoor(x, y, w, h):
    aq   = state["air_quality_label"]
    fill = _aq_glass(aq)
    _card_base_col(x, y, w, h, fill)
    _tag(x, y, "INDOOR")
    t = state["temperature"]; hu = state["humidity"]
    lcd.font(lcd.FONT_DejaVu24)
    t_str = "{}{}C".format("--" if t is None else int(t), DEG)
    lcd.print(t_str, x + 8, y + 24, C_TXT1)
    lcd.fillCircle(x + 10, y + 65, 5, C_BLUE)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("{}%".format("--" if hu is None else int(hu)), x + 22, y + 56, C_TXT2)
    # Air quality label bottom-right
    lcd.font(lcd.FONT_Default)
    acol = air_color(aq)
    lcd.print(aq, x + w - len(aq) * 6 - 8, y + h - 14, acol)

def _home_session(x, y, w, h):
    _card_base(x, y, w, h)
    _tag(x, y, "SESSION")
    if state["session_active"]:
        s    = "Paused" if state["session_paused"] else "Active"
        scol = C_AMBER if state["session_paused"] else C_GREEN
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
    lcd.fillRoundRect(x + 8, y + 72, w - 24, 3, 1, C_LAVEND)

def draw_home():
    _draw_bg()
    draw_statusbar()
    _home_outdoor(CX1, CY1, CW, CH)
    _home_indoor(CX2, CY1, CW, CH)
    _home_session(CX1, CY2, CW, CH)
    _home_voice(CX2, CY2, CW, CH)
    lcd.fillRoundRect(140, 237, 40, 3, 1, C_GLASS_B)

# draw_main_screen alias for boot/compat
def draw_main_screen():
    draw_home()

def smart_update_main_screen():
    global _last_main
    if state["time_str"] != _last_main["time_str"] or state["date_str"] != _last_main["date_str"]:
        draw_statusbar()
        _last_main["time_str"] = state["time_str"]
        _last_main["date_str"] = state["date_str"]
    if (state["weather_temp"] != _last_main["weather_temp"] or
            state["weather_cond"] != _last_main["weather_cond"]):
        _erase_card(CX1, CY1, CW, CH)
        _home_outdoor(CX1, CY1, CW, CH)
        _last_main["weather_temp"] = state["weather_temp"]
        _last_main["weather_cond"] = state["weather_cond"]
    if (state["temperature"] != _last_main["temperature"] or
            state["humidity"]    != _last_main["humidity"]):
        _erase_card(CX2, CY1, CW, CH)
        _home_indoor(CX2, CY1, CW, CH)
        _last_main["temperature"] = state["temperature"]
        _last_main["humidity"]    = state["humidity"]
    if (state["session_active"] != _last_main["session_active"] or
            state["session_paused"] != _last_main["session_paused"]):
        _erase_card(CX1, CY2, CW, CH)
        _home_session(CX1, CY2, CW, CH)
        _last_main["session_active"] = state["session_active"]
        _last_main["session_paused"] = state["session_paused"]

# ============================================================
# CONTROL CENTER PANEL
# ============================================================
def _cc_tile(x, y, w, h, label, col, icon):
    lcd.fillRoundRect(x, y, w, h, 12, C_CC_TILE)
    lcd.drawRoundRect(x, y, w, h, 12, C_GLASS_B)
    lcd.fillRect(x + 5, y + 1, w - 10, 2, C_GLASS_H)
    cx = x + w // 2; cy = y + 30
    if icon == "wifi":
        lcd.line(cx, cy-12, cx-10, cy+6, col)
        lcd.line(cx, cy-12, cx+10, cy+6, col)
        lcd.line(cx-10, cy+6, cx+10, cy+6, col)
        lcd.line(cx-5,  cy+1, cx+5,  cy+1, col)
    elif icon == "sensors":
        lcd.drawRoundRect(cx-10, cy-10, 20, 20, 10, col)
        lcd.fillCircle(cx, cy, 4, col)
    elif icon == "settings":
        lcd.drawRoundRect(cx-8, cy-8, 16, 16, 8, col)
        lcd.fillRect(cx-2, cy-12, 4, 5, col)
        lcd.fillRect(cx-2, cy+7,  4, 5, col)
        lcd.fillRect(cx-12, cy-2, 5, 4, col)
        lcd.fillRect(cx+7,  cy-2, 5, 4, col)
    lcd.font(lcd.FONT_Default)
    lw = len(label) * 6
    lcd.print(label, cx - lw // 2, y + 58, col)

def draw_panel():
    lcd.fillRect(0, 0, 320, 204, C_CC_BG)
    # Handle pill
    lcd.fillRoundRect(140, 5, 40, 4, 2, C_GLASS_B)
    lcd.fillRect(0, 14, 320, 1, C_SEP)
    # Title + logo
    _bold("SmartFocusTracker", _cx("SmartFocusTracker", 6, 0, 320), 20, C_L1)
    # focus ring icon — left of title
    lx = _cx("SmartFocusTracker", 6, 0, 320) - 22
    lcd.drawRoundRect(lx, 18, 14, 14, 7, C_BLUE_L)
    lcd.fillCircle(lx + 7, 25, 3, C_BLUE_L)
    lcd.fillRect(0, 36, 320, 1, C_SEP)
    # Status row: WiFi + battery
    lcd.font(lcd.FONT_Default)
    try:    ssid = wlan.config("essid") if wlan.isconnected() else "No WiFi"
    except: ssid = "No WiFi"
    lcd.print("wifi  {}  {}".format(chr(183), ssid[:14]), 12, 44, C_L2)
    pct = _read_battery_pct()
    pct_s = "{}%".format(pct) if pct is not None else "--"
    lcd.print(pct_s, 296 - len(pct_s) * 6, 44, C_L3)
    lcd.fillRect(0, 56, 320, 1, C_SEP)
    # 3 glass tiles
    _cc_tile(8,   62, 96, 76, "WiFi",     C_BLUE_L,  "wifi")
    _cc_tile(112, 62, 96, 76, "Sensors",  C_AMBER_L, "sensors")
    _cc_tile(216, 62, 96, 76, "Settings", C_L2,      "settings")
    lcd.fillRect(0, 146, 320, 1, C_SEP)
    # Comfort phrase
    phrase, ccol = _comfort_label()
    lcd.font(lcd.FONT_Default)
    lcd.print(phrase, _cx(phrase, 6, 0, 320), 156, ccol)
    lcd.fillRect(0, 172, 320, 1, C_SEP)
    # Swipe hint
    hint = "Swipe up  or  [A] to close"
    lcd.print(hint, _cx(hint, 6, 0, 320), 182, C_L3)
    lcd.fillRect(0, 203, 320, 1, C_GLASS_B)

# ============================================================
# DETAIL SCREENS
# ============================================================
def draw_forecast_screen():
    _detail_top("Home", "5-Day Forecast", C_BLUE_L)
    forecast = state["forecast"]
    if not forecast:
        _card_base(12, 64, 296, 80)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No forecast data", _cx("No forecast data",11,12,296), 96, C_TXT3)
        return
    td = today_str(); col_w = 64
    for i, day in enumerate(forecast[:5]):
        cx = col_w * i + 32; x0 = col_w * i
        date = day.get("date",""); name = date_to_dayname(date, td)
        tmin = int(round(day.get("temp_min",0))); tmax = int(round(day.get("temp_max",0)))
        cond = day.get("condition","N/A"); col = condition_color(cond)
        if i > 0: lcd.line(x0, 60, x0, 210, C_SEP)
        lcd.fillRect(x0 + (1 if i>0 else 0), 60, col_w - (1 if i>0 else 0), 4, col)
        lcd.font(lcd.FONT_Default)
        name_s = name[:3]; lcd.print(name_s, cx - len(name_s)*4, 72, col)
        draw_weather_icon(cx, 118, cond)
        lcd.font(lcd.FONT_DejaVu18)
        tmax_s = "{}{}".format(tmax, DEG)
        lcd.print(tmax_s, cx - len(tmax_s)*6, 158, C_L1)
        lcd.font(lcd.FONT_Default)
        tmin_s = "{}{}".format(tmin, DEG)
        lcd.print(tmin_s, cx - len(tmin_s)*4, 182, C_L3)
    lcd.line(0, 210, 320, 210, C_SEP)

def draw_sensor_detail():
    _detail_top("Home", "Indoor", C_TEAL)
    t  = state["temperature"]; h = state["humidity"]
    co2= state["co2_ppm"];     tv= state["tvoc_ppb"]
    aq = state["air_quality_label"]
    _card_base(12, 64, 296, 100)
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("{}{}C".format("--" if t is None else int(t), DEG), 24, 76, C_TXT1)
    lcd.fillCircle(190, 107, 8, C_BLUE)
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print("{}%".format("--" if h is None else int(h)), 206, 92, C_TXT2)
    acol = air_color(aq)
    _detail_row(20, 176, "CO2",    "{} ppm".format("--" if co2 is None else co2),  acol)
    _detail_row(20, 196, "TVOC",   "{} ppb".format("--" if tv  is None else tv),   C_L2)
    _detail_row(20, 216, "Air",    aq,                                               acol)

def draw_session_detail():
    _detail_top("Home", "Session", C_GREEN_L)
    _card_base(12, 64, 296, 100)
    if state["session_active"]:
        s    = "Paused"  if state["session_paused"] else "Active"
        scol = C_AMBER   if state["session_paused"] else C_GREEN
        bw = len(s) * 11 + 34
        lcd.drawRoundRect(24, 80, bw, 34, 10, scol)
        lcd.fillCircle(38, 97, 5, scol)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print(s, 50, 87, scol)
        mins = int(state["session_work_sec"] // 60)
        secs = int(state["session_work_sec"] % 60)
        brk_in = max(0, int((settings["break_interval"] - state["session_work_sec"]) // 60))
        brk_col = C_CORAL if brk_in <= 5 else C_AMBER_L if brk_in <= 15 else C_L2
        _detail_row(20, 180, "Duration", "{:02d}:{:02d}".format(mins, secs), C_L1)
        _detail_row(20, 200, "Break in", "{} min".format(brk_in),            brk_col)
        name = CARD_NAMES.get(state["session_card_id"], "") if state["session_card_id"] else ""
        if name:
            _detail_row(20, 220, "User", name, C_BLUE_L)
    else:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No active session", _cx("No active session",11,12,296), 96, C_TXT3)

def draw_wifi_screen():
    _detail_top("Home", "WiFi", C_BLUE_L)
    for i, (ssid, _) in enumerate(KNOWN_NETWORKS):
        x = 10 + i * 158; w = 146; y = 66; h = 124
        try:    is_active = wlan.isconnected() and wlan.config("essid") == ssid
        except: is_active = False
        if is_active:
            lcd.fillRoundRect(x, y, w, h, 10, C_GLASS)
            lcd.drawRoundRect(x, y, w, h, 10, C_GREEN)
            lcd.fillRect(x + 5, y + 1, w - 10, 2, C_GLASS_H)
        else:
            lcd.fillRoundRect(x, y, w, h, 10, C_CC_TILE)
            lcd.drawRoundRect(x, y, w, h, 10, C_GLASS_B)
        lcd.font(lcd.FONT_Default)
        _bold(ssid[:14], x + 8, y + 10, C_TXT1 if is_active else C_L1)
        if is_active:
            lcd.font(lcd.FONT_Default)
            _bold("Connected", x + 8, y + 72, C_GREEN)
        else:
            lcd.print("Tap to connect", x + 8, y + 72, C_L3)
    lcd.font(lcd.FONT_Default)
    lcd.print("A: left   B: back   C: right", _cx("A: left   B: back   C: right",6,0,320), 208, C_L3)

def draw_settings_screen():
    _detail_top("Home", "Settings", C_L2)
    # WiFi card
    x = 10; y = 66; w = 136; h = 124
    lcd.fillRoundRect(x, y, w, h, 10, C_GLASS)
    lcd.drawRoundRect(x, y, w, h, 10, C_BLUE)
    lcd.fillRect(x+5, y+1, w-10, 2, C_GLASS_H)
    _tag(x, y, "WIFI")
    try:    ssid = wlan.config("essid") if wlan.isconnected() else "Disconnected"
    except: ssid = "Unknown"
    lcd.font(lcd.FONT_Default)
    lcd.print(ssid[:16], x+8, y+28, C_TXT2)
    scol = C_GREEN if wlan.isconnected() else C_CORAL
    _bold("Connected" if wlan.isconnected() else "Off", x+8, y+46, scol)
    lcd.print("A: manage", x+8, y+80, C_TXT3)
    # Sensors card
    x2 = 174
    lcd.fillRoundRect(x2, y, w, h, 10, C_GLASS)
    lcd.drawRoundRect(x2, y, w, h, 10, C_AMBER)
    lcd.fillRect(x2+5, y+1, w-10, 2, C_GLASS_H)
    _tag(x2, y, "SENSORS")
    lcd.font(lcd.FONT_Default)
    lcd.print("Read: {}s".format(settings["sensor_interval"]),   x2+8, y+28, C_TXT2)
    lcd.print("BQ:   {}s".format(settings["bq_interval"]),       x2+8, y+42, C_TXT2)
    lcd.print("Brk: {}m".format(settings["break_interval"]//60), x2+8, y+56, C_TXT2)
    lcd.print("C: manage", x2+8, y+80, C_TXT3)
    lcd.font(lcd.FONT_Default)
    lcd.print("B: back to home", _cx("B: back to home",6,0,320), 208, C_L3)

def _find_opt_idx(key, opts):
    val = settings[key]
    for i, opt in enumerate(opts):
        if opt == val: return i
    return 0

def draw_sensor_settings_screen():
    global _sensor_param_idx
    label, key, opts, labels = PARAM_DEFS[_sensor_param_idx]
    cur_idx = _find_opt_idx(key, opts)
    _detail_top("Back", "Sensor Settings", C_AMBER_L)
    prog = "{}/{}".format(_sensor_param_idx + 1, len(PARAM_DEFS))
    lcd.font(lcd.FONT_Default)
    lcd.print(prog, 296 - len(prog)*6, 38, C_TXT2)
    _card_base(10, 66, 300, 120)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(label, 22, 78, C_TXT1)
    lcd.fillRect(10, 100, 300, 1, C_SEP)
    col_w = 300 // len(opts)
    for i, lbl in enumerate(labels):
        cx = 10 + col_w * i + col_w // 2
        is_sel = (i == cur_idx)
        if is_sel:
            lcd.fillRoundRect(10 + col_w*i + 4, 104, col_w-8, 68, 8, C_GLASS_B)
            lcd.font(lcd.FONT_DejaVu40)
            tw = len(lbl) * 13
            lcd.print(lbl, cx - tw//2, 114, C_BLUE)
        else:
            lcd.font(lcd.FONT_DejaVu18)
            tw = len(lbl) * 9
            lcd.print(lbl, cx - tw//2, 122, C_TXT3)
    lcd.font(lcd.FONT_Default)
    back_col = C_BLUE_L if _sensor_param_idx > 0 else C_L3
    next_col = C_BLUE_L if _sensor_param_idx < len(PARAM_DEFS)-1 else C_L3
    lcd.print("A: back", 10, 210, back_col)
    lcd.print("B: change", _cx("B: change",6,0,320), 210, C_AMBER_L)
    lcd.print("C: next", 296 - 7*6, 210, next_col)

def draw_voice_screen(status, step="", question="", answer="", status_col=None):
    if status_col is None: status_col = C_L1
    _detail_top("Home", "Voice", C_LAVEND_L)
    _card_base(10, 64, 300, 50)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(status[:22], _cx(status[:22],11,10,300), 78, status_col)
    if step:
        lcd.font(lcd.FONT_Default)
        lcd.print(step[:44], _cx(step[:44],6,10,300), 100, C_TXT3)
    y = 122
    if question:
        _card_base(10, y, 300, 40)
        lcd.font(lcd.FONT_Default)
        lcd.print("Q: " + question[:42], 18, y+12, C_TXT2)
        y += 48
    if answer:
        _card_base(10, y, 300, 240 - y - 10)
        words = answer.split(" "); lines = []; line = ""
        for word in words:
            if len(line) + len(word) + 1 <= 42: line = line + " " + word if line else word
            else: lines.append(line); line = word
        if line: lines.append(line)
        ay = y + 8
        for l in lines[:4]:
            lcd.print(l, 18, ay, C_TXT1); ay += 14

# ============================================================
# VOICE FLOW
# ============================================================
def voice_flow():
    global last_answer, last_question, current_screen
    current_screen = 2

    if mic is None:
        draw_voice_screen("Micro KO", "MicRecord non initialise", status_col=C_CORAL)
        time.sleep(3); return

    draw_voice_screen("Preparez-vous...", "Parlez apres le bip")
    time.sleep(1); bip(1200); time.sleep_ms(150)

    draw_voice_screen(">>> PARLEZ <<<", "Enregistrement {}s...".format(RECORD_SECS), status_col=C_CORAL)
    try: mic.record2file(RECORD_SECS, VOICE_FILE)
    except Exception as e: print("[MIC]", e)
    bip(800)

    sz = file_size(VOICE_FILE)
    if sz < 1000:
        draw_voice_screen("Rien entendu", "Taille: {}B".format(sz), status_col=C_AMBER_L)
        time.sleep(3); return

    draw_voice_screen("Transcription...", "Envoi audio...", status_col=C_BLUE_L)
    code, body = _ssl_post_wav_transcribe(VOICE_FILE); gc.collect()

    if code is None or code != 200:
        draw_voice_screen("Erreur STT", "Code: {}".format(code), status_col=C_CORAL)
        time.sleep(3); return

    try:    transcript = ujson.loads(body).get("transcript","").strip()
    except:
        draw_voice_screen("Erreur JSON", "", status_col=C_CORAL)
        time.sleep(2); return

    if not transcript:
        draw_voice_screen("Rien transcrit", "Parlez plus pres", status_col=C_AMBER_L)
        time.sleep(3); return

    last_question = transcript

    draw_voice_screen("Reflexion...", transcript[:44], status_col=C_BLUE_L)
    ok, answer, msg = _ssl_post_text_to_wav(transcript, _build_sensor_context(), RESP_FILE)
    gc.collect()

    if not ok:
        draw_voice_screen("Erreur", msg[:44], question=transcript, status_col=C_CORAL)
        time.sleep(3); return

    last_answer = answer
    draw_voice_screen("Reponse !", "Appuie [A] pour revenir",
                      question=transcript, answer=answer, status_col=C_GREEN_L)
    try: speaker.playWAV('res/resp.wav', volume=8)
    except Exception as e: print("[SPEAKER]", e)
    gc.collect()

# ============================================================
# TOUCH HANDLER
# ============================================================
def handle_touch():
    global _touch_start, _touch_done, _panel_open
    global current_screen, _main_needs_full_redraw, _sensor_param_idx
    xy = read_touch_xy()
    if xy:
        x, y = xy
        if _touch_start is None:
            _touch_start = (x, y); _touch_done = False
        if not _touch_done:
            dy = y - _touch_start[1]
            # Swipe down (40px) → open CC panel
            if not _panel_open and dy >= 40:
                _touch_done = True; _touch_start = None
                _panel_open = True; draw_panel()
            # Swipe up (30px) → close CC panel
            elif _panel_open and dy <= -30:
                _touch_done = True; _touch_start = None
                _panel_open = False; draw_home(); _main_needs_full_redraw = False
    else:
        # Finger lifted — use start position for tap routing
        if _touch_start is not None and not _touch_done:
            sx, sy = _touch_start

            if _panel_open:
                if 62 <= sy <= 138:
                    _panel_open = False
                    if   8  <= sx <= 104: current_screen = 4; draw_wifi_screen()
                    elif 112<= sx <= 208: current_screen = 7; draw_sensor_detail()
                    elif 216<= sx <= 312: current_screen = 5; draw_settings_screen()
                    else: draw_home(); _main_needs_full_redraw = False
                else:
                    _panel_open = False; draw_home(); _main_needs_full_redraw = False

            elif current_screen == 0:
                if sy < 135:
                    if sx < 163: current_screen = 3; draw_forecast_screen()
                    else:         current_screen = 7; draw_sensor_detail()
                else:
                    if sx < 163: current_screen = 8; draw_session_detail()
                    else:
                        _touch_start = None; _touch_done = False
                        voice_flow(); _main_needs_full_redraw = True; return

            elif current_screen == 5:
                # Settings: nav bar → home | left card → WiFi | right card → sensors
                if sy < 58:
                    current_screen = 0; draw_home(); _main_needs_full_redraw = False
                elif sx < 163:
                    current_screen = 4; draw_wifi_screen()
                else:
                    _sensor_param_idx = 0; current_screen = 6; draw_sensor_settings_screen()

            elif current_screen == 6:
                current_screen = 5; draw_settings_screen()

            else:
                # Screens 2, 3, 4, 7, 8 — tap anywhere → home
                current_screen = 0; draw_home(); _main_needs_full_redraw = False

        _touch_start = None; _touch_done = False

# ============================================================
# BUTTONS
# ============================================================
def handle_buttons():
    global current_screen, _main_needs_full_redraw, _sensor_param_idx
    global _panel_open, _touch_start, _touch_done

    if current_screen == 6:
        if btnA.wasPressed():
            _touch_start = None; _touch_done = False
            if _sensor_param_idx > 0:
                _sensor_param_idx -= 1; draw_sensor_settings_screen()
            else:
                current_screen = 5; draw_settings_screen()
        if btnB.wasPressed():
            _touch_start = None; _touch_done = False
            label, key, opts, labels = PARAM_DEFS[_sensor_param_idx]
            new_idx = (_find_opt_idx(key, opts) + 1) % len(opts)
            settings[key] = opts[new_idx]; save_settings()
            draw_sensor_settings_screen()
        if btnC.wasPressed():
            _touch_start = None; _touch_done = False
            if _sensor_param_idx < len(PARAM_DEFS) - 1:
                _sensor_param_idx += 1; draw_sensor_settings_screen()
            else:
                current_screen = 5; draw_settings_screen()

    elif current_screen == 5:
        if btnA.wasPressed():
            _touch_start = None; _touch_done = False
            current_screen = 4; draw_wifi_screen()
        if btnB.wasPressed():
            _touch_start = None; _touch_done = False
            current_screen = 0; draw_home(); _main_needs_full_redraw = False
        if btnC.wasPressed():
            _touch_start = None; _touch_done = False
            _sensor_param_idx = 0; current_screen = 6; draw_sensor_settings_screen()

    elif current_screen == 4:
        if btnA.wasPressed():
            _touch_start = None; _touch_done = False
            connect_to_network(0); current_screen = 0; draw_home(); _main_needs_full_redraw = False
        if btnB.wasPressed():
            _touch_start = None; _touch_done = False
            current_screen = 0; draw_home(); _main_needs_full_redraw = False
        if btnC.wasPressed():
            _touch_start = None; _touch_done = False
            connect_to_network(1); current_screen = 0; draw_home(); _main_needs_full_redraw = False

    elif current_screen in (7, 8, 3):
        if btnA.wasPressed() or btnB.wasPressed() or btnC.wasPressed():
            _touch_start = None; _touch_done = False
            current_screen = 0; draw_home(); _main_needs_full_redraw = False

    elif current_screen == 2:
        if btnA.wasPressed() or btnB.wasPressed() or btnC.wasPressed():
            _touch_start = None; _touch_done = False
            current_screen = 0; draw_home(); _main_needs_full_redraw = False

    else:  # screen 0 — home
        if btnA.wasPressed():
            _touch_start = None; _touch_done = False
            if _panel_open or current_screen != 0:
                _panel_open = False; current_screen = 0; draw_home(); _main_needs_full_redraw = False
            else:
                current_screen = 5; draw_settings_screen()
        if btnB.wasPressed():
            _touch_start = None; _touch_done = False
            voice_flow(); _main_needs_full_redraw = True
        if btnC.wasPressed():
            _touch_start = None; _touch_done = False
            _panel_open = True; draw_panel()

# ============================================================
# BOOT
# ============================================================
def _boot_logo_anim():
    _draw_bg()
    cx, cy = 160, 82
    # expanding focus rings (outer → inner)
    for r, col, ms in [(32, C_SEP, 90), (22, C_GLASS_B, 90), (13, C_GLASS, 90)]:
        lcd.drawRoundRect(cx - r, cy - r, r * 2, r * 2, r, col)
        time.sleep_ms(ms)
    lcd.fillCircle(cx, cy, 5, C_BLUE_L)
    time.sleep_ms(90)
    # crosshair lines
    lcd.line(cx - 38, cy, cx - 18, cy, C_BLUE_L)
    lcd.line(cx + 18, cy, cx + 38, cy, C_BLUE_L)
    lcd.line(cx, cy - 38, cx, cy - 18, C_BLUE_L)
    lcd.line(cx, cy + 18, cx, cy + 38, C_BLUE_L)
    time.sleep_ms(160)
    # title
    lcd.font(lcd.FONT_DejaVu18)
    title = "SmartFocusTracker"
    _bold(title, _cx(title, 11, 0, 320), 116, C_L1)
    time.sleep_ms(120)
    # tagline
    lcd.font(lcd.FONT_Default)
    tag = "Smart workspace.  Smarter you."
    lcd.print(tag, _cx(tag, 6, 0, 320), 140, C_L3)
    time.sleep_ms(220)
    # separator above progress bar
    lcd.fillRect(20, 162, 280, 1, C_SEP)

def _boot_step(text, pct):
    # progress bar
    lcd.fillRect(20, 164, 280, 8, C_SEP)
    fw = max(0, min(280, 280 * pct // 100))
    if fw:
        lcd.fillRoundRect(20, 164, fw, 8, 4, C_BLUE_L)
    # status text
    lcd.fillRect(0, 178, 320, 14, C_BG3)
    lcd.font(lcd.FONT_Default)
    t = text[:44]
    lcd.print(t, _cx(t, 6, 0, 320), 180, C_L3)

def boot():
    global _main_needs_full_redraw
    try: speaker.setVolume(8)
    except: pass
    load_settings()
    _boot_logo_anim()
    _boot_step("Starting up...", 5)
    time.sleep_ms(400)

    # sensor warmup — live countdown
    for i in range(15):
        _boot_step("Warming air sensor... {}s".format(15 - i), 8 + i * 3)
        time.sleep(1)
    _boot_step("Air sensor ready", 53)
    time.sleep_ms(300)

    # WiFi — inline, no show_msg
    _boot_step("Connecting to WiFi...", 58)
    wlan.active(True)
    connected = False
    if not wlan.isconnected():
        for ssid, pwd in KNOWN_NETWORKS:
            _boot_step("WiFi: {}".format(ssid[:22]), 60)
            wlan.connect(ssid, pwd)
            for _ in range(15):
                if wlan.isconnected():
                    connected = True; break
                time.sleep(1)
            if connected: break
    else:
        connected = True

    if connected:
        try: ssid_name = wlan.config("essid")
        except: ssid_name = "network"
        _boot_step("Connected: {}".format(ssid_name[:20]), 68)
    else:
        _boot_step("No WiFi — offline mode", 68)
    time.sleep_ms(300)

    # NTP
    if wlan.isconnected():
        _boot_step("Syncing time...", 72)
        if _sync_ntp() or _sync_time_http():
            _boot_step("Time synced", 76)
        else:
            _boot_step("Time sync failed", 76)
        time.sleep_ms(300)

    _boot_step("Preparing alerts...", 80)
    _ensure_alert_wavs()
    _boot_step("Fetching session...", 84)
    sync_latest()
    _boot_step("Fetching weather...", 88)
    fetch_weather()
    fetch_session()
    _boot_step("Reading sensors...", 93)
    state["time_str"], state["date_str"] = get_time_strings_short()
    read_sensors()
    update_leds()
    _boot_step("Ready!", 100)
    time.sleep_ms(500)
    draw_home()
    _main_needs_full_redraw = False
    print("[BOOT] Done.")

# ============================================================
# MAIN LOOP
# ============================================================
def loop():
    global last_motion_time, _main_needs_full_redraw
    last_sensor=0; last_bq=0; last_weather=0
    last_session=0; last_clock=0; last_draw=0; last_ntp=0

    while True:
        now = time.time()

        # Touch first — always fast, never blocked
        handle_touch()
        handle_buttons()

        # Clock + PIR — fast, non-blocking
        if now - last_clock >= 1:
            state["time_str"], state["date_str"] = get_time_strings_short()
            last_clock = now
        try:
            state["motion"] = bool(pir.value())
            if state["motion"]: last_motion_time = now
        except: pass

        # Draw — fast (lcd only) — skip if panel is open
        if now - last_draw >= DRAW_INTERVAL:
            if current_screen == 0 and not _panel_open:
                if _main_needs_full_redraw:
                    draw_home(); _main_needs_full_redraw = False
                else:
                    smart_update_main_screen()
            last_draw = now

        # Touch again before any blocking call
        handle_touch()

        # Network/sensor — ONE per iteration (elif = no stacking)
        if now - last_sensor >= settings["sensor_interval"]:
            read_sensors(); update_leds(); last_sensor = now
        elif now - last_session >= SESSION_INTERVAL:
            fetch_session(); last_session = now
        elif now - last_bq >= settings["bq_interval"]:
            post_indoor(); last_bq = now
        elif now - last_weather >= WEATHER_INTERVAL:
            fetch_weather(); last_weather = now
        elif now - last_ntp >= 3600:
            if wlan.isconnected():
                if not _sync_ntp(): _sync_time_http()
            last_ntp = now

        check_alerts()

        # Touch after blocking call too
        handle_touch()

        gc.collect()
        time.sleep_ms(20)

# ============================================================
# ENTRY POINT
# ============================================================
boot()
loop()
