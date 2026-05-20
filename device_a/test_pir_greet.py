# device_a/test_pir_greet.py
# Test isolé : capteur PIR + salutation vocale TTS.
# Étape 1 — confirme que le PIR détecte du mouvement (visuel + bip).
# Étape 2 — confirme que le TTS prononce la salutation correctement.
# Aucune dépendance à main2.py, session ou RFID.

import gc
import time
import network
import usocket
import ussl
import ujson
import urequests
from machine import Pin
from m5stack import lcd, speaker, btnA

# ============================================================
# CONFIG
# ============================================================
MIDDLEWARE_URL = "https://smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_HOST     = "smartfocustracker-middleware-1054003632036.europe-west6.run.app"
CLOUD_PORT     = 443
RESP_FILE      = '/flash/res/resp.wav'

KNOWN_NETWORKS = [
    ("iPhone de Pablo", "1234567890"),
    ("iot-unil",        "4u6uch4hpY9pJ2f9"),
]

COLOR_BG     = 0x1a1a2e
COLOR_WHITE  = 0xFFFFFF
COLOR_GREY   = 0xAAAAAA
COLOR_GOOD   = 0x00FF00
COLOR_BAD    = 0xFF0000
COLOR_WARN   = 0xFFAA00
COLOR_ACCENT = 0x00BCD4

# ============================================================
# HARDWARE
# ============================================================
try:
    pir = Pin(26, Pin.IN)
    print("[PIR] Init OK")
except Exception as e:
    pir = None
    print("[PIR] Init FAILED:", e)

# ============================================================
# DISPLAY HELPERS
# ============================================================
def draw_screen(pir_val, status, log_lines):
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("PIR + Greet Test", 30, 6, COLOR_ACCENT)
    lcd.line(0, 28, 320, 28, 0x333333)

    # PIR state — grand indicateur visuel
    lcd.font(lcd.FONT_DejaVu40)
    if pir_val:
        lcd.fillRect(10, 38, 140, 50, 0x003300)
        lcd.print("PIR: 1", 14, 48, COLOR_GOOD)
    else:
        lcd.fillRect(10, 38, 140, 50, 0x1a1a2e)
        lcd.print("PIR: 0", 14, 48, COLOR_GREY)

    # Status
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(status[:28], 10, 98, COLOR_WARN)

    # Log lignes
    lcd.font(lcd.FONT_Default)
    y = 126
    for line in log_lines[-5:]:
        lcd.print(line[:44], 10, y, COLOR_WHITE)
        y += 16

    # Bouton
    lcd.fillRect(0, 210, 320, 30, 0x222222)
    lcd.font(lcd.FONT_Default)
    lcd.print("[A] Forcer salutation TTS", 20, 218, COLOR_ACCENT)

def bip(freq=1200):
    try: speaker.sing(freq, 1, 150)
    except:
        try: speaker.playTone(freq, 1)
        except: pass

# ============================================================
# WIFI
# ============================================================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True
    for ssid, pwd in KNOWN_NETWORKS:
        lcd.clear(COLOR_BG)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("WiFi: " + ssid, 10, 100, COLOR_WHITE)
        wlan.connect(ssid, pwd)
        for _ in range(12):
            if wlan.isconnected():
                return True
            time.sleep(1)
    return False

# ============================================================
# TTS — même fonction que main2.py
# ============================================================
def _safe_remove(path):
    try: import os; os.remove(path)
    except: pass

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
        hdata = b''
        while b'\r\n\r\n' not in hdata:
            chunk = ss.read(128)
            if not chunk: break
            hdata += chunk
        if b'\r\n\r\n' not in hdata: return False, 'bad response'
        hpart, bstart = hdata.split(b'\r\n\r\n', 1)
        code = int(hpart.split(b'\r\n')[0].decode().split(' ')[1])
        if code != 200: return False, 'HTTP ' + str(code)
        _safe_remove(out_file)
        f = open(out_file, 'wb')
        if bstart: f.write(bstart)
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

def fetch_weather_cond():
    """Récupère la météo actuelle pour la salutation."""
    try:
        r = urequests.get(MIDDLEWARE_URL + "/weather")
        if r.status_code == 200:
            d    = ujson.loads(r.text)
            cur  = d.get("current", {})
            cond = cur.get("condition", "N/A")
            temp = int(round(cur.get("temperature", 0)))
            r.close()
            return cond, temp
        r.close()
    except Exception as e:
        print("[WEATHER]", e)
    return "N/A", "--"

def speak_greet(cond, temp):
    """
    Construit et prononce la salutation TTS.
    Ici sans prénom — test isolé.
    """
    text = "Bonjour ! Dehors : {}, {}C.".format(cond, temp)
    c = cond.lower()
    if "rain" in c or "drizzle" in c or "shower" in c or "storm" in c or "thunder" in c:
        text += " Pensez a prendre un parapluie."
    print("[GREET] Text:", text)
    ok, msg = _ssl_post_to_wav_file('/speak-wav', {'text': text}, RESP_FILE)
    if ok:
        try: speaker.playWAV('res/resp.wav', volume=8)
        except Exception as e: print("[SPEAKER]", e)
    else:
        print("[GREET] TTS failed:", msg)
    gc.collect()
    return ok, text

# ============================================================
# MAIN
# ============================================================
def main():
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Connexion WiFi...", 10, 110, COLOR_WHITE)

    wifi_ok = connect_wifi()
    log_lines = ["WiFi: " + ("OK" if wifi_ok else "FAIL")]

    cond, temp = ("N/A", "--")
    if wifi_ok:
        log_lines.append("Fetch meteo...")
        cond, temp = fetch_weather_cond()
        log_lines.append("Meteo: {} {}C".format(cond, temp))

    pir_prev  = False
    status    = "En attente de mouvement..."

    draw_screen(False, status, log_lines)

    while True:
        # Lecture PIR
        pir_val = False
        if pir:
            try: pir_val = bool(pir.value())
            except: pass

        # Front montant → bip + TTS
        if pir_val and not pir_prev:
            print("[PIR] Mouvement detecte !")
            bip(1400)
            status = "Mouvement ! TTS..."
            log_lines.append("PIR: mouvement detecte")
            draw_screen(pir_val, status, log_lines)

            if wifi_ok:
                ok, text = speak_greet(cond, temp)
                status = "TTS OK" if ok else "TTS FAIL"
                log_lines.append(status + ": " + text[:30])
            else:
                status = "WiFi absent — TTS ignore"
                log_lines.append(status)

        pir_prev = pir_val
        draw_screen(pir_val, status, log_lines)

        # Bouton A — force une salutation TTS sans attendre le PIR
        if btnA.wasPressed():
            bip(1200)
            status = "Forçage TTS..."
            log_lines.append("Bouton A: force TTS")
            draw_screen(pir_val, status, log_lines)
            if wifi_ok:
                ok, text = speak_greet(cond, temp)
                status = "TTS OK" if ok else "TTS FAIL"
                log_lines.append(status)
            else:
                status = "Pas de WiFi"

        gc.collect()
        time.sleep_ms(200)   # polling 5x/s — plus réactif que la boucle principale

main()
