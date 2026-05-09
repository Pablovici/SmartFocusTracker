# test_alerts.py — teste les alertes vocales (cached + dynamic TTS)
from m5stack import lcd, speaker, btnA, btnB, btnC
import gc, os, time, usocket, ussl, ubinascii, urequests, ujson

# ============================================================
# CONFIG
# ============================================================
CLOUD_HOST      = "smartfocustracker-middleware-1054003632036.europe-west6.run.app"
ALERT_WAV_BREAK = '/flash/res/alert_break.wav'
ALERT_WAV_AIR   = '/flash/res/alert_air.wav'
RESP_FILE       = '/flash/res/resp.wav'
COLOR_BG        = 0x1a1a2e
COLOR_WARN      = 0xFFAA00
COLOR_WHITE     = 0xFFFFFF
COLOR_ACCENT    = 0x00BCD4
COLOR_GREY      = 0xAAAAAA
COLOR_GREEN     = 0x00FF00
COLOR_RED       = 0xFF0000

# ============================================================
# HELPERS
# ============================================================
def log(msg, color=COLOR_WHITE):
    print("[LOG]", msg)

def bip(freq=1200):
    try: speaker.sing(freq, 1, 200)
    except:
        try: speaker.playTone(freq, 1)
        except: pass

def safe_remove(p):
    try: os.remove(p)
    except: pass

def file_size(p):
    try: return os.stat(p)[6]
    except: return 0

def draw_menu(status="", col=COLOR_WHITE):
    lcd.clear(COLOR_BG)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Test Alertes", 70, 6, COLOR_ACCENT)
    lcd.line(0, 30, 320, 30, 0x444444)
    if status:
        lcd.font(lcd.FONT_Default)
        lcd.print(status[:42], 10, 40, col)
    # Info fichiers
    lcd.font(lcd.FONT_Default)
    b_sz = file_size(ALERT_WAV_BREAK)
    a_sz = file_size(ALERT_WAV_AIR)
    lcd.print("alert_break.wav : {}B".format(b_sz), 10, 65, COLOR_GREEN if b_sz > 1000 else COLOR_RED)
    lcd.print("alert_air.wav   : {}B".format(a_sz), 10, 80, COLOR_GREEN if a_sz > 1000 else COLOR_RED)
    # Boutons
    lcd.fillRect(0,   210, 106, 30, 0x333333)
    lcd.fillRect(107, 210, 106, 30, 0x004466)
    lcd.fillRect(213, 210, 107, 30, 0x333300)
    lcd.print("PAUSE",  18,  218, COLOR_WHITE)
    lcd.print("AIR",    140, 218, COLOR_ACCENT)
    lcd.print("HUMID",  225, 218, COLOR_WARN)

def draw_alert_overlay(text):
    lcd.fillRect(0, 70, 320, 100, 0x1a0800)
    lcd.line(0, 70, 320, 70, COLOR_WARN)
    lcd.line(0, 170, 320, 170, COLOR_WARN)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("! ALERTE !", 105, 78, COLOR_WARN)
    lcd.font(lcd.FONT_Default)
    words = text.split(" "); lines = []; line = ""
    for w in words:
        if len(line) + len(w) + 1 <= 46: line = line + " " + w if line else w
        else: lines.append(line); line = w
    if line: lines.append(line)
    y = 104
    for l in lines[:4]: lcd.print(l, 10, y, COLOR_WHITE); y += 14

# ============================================================
# NETWORK
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
        addr = usocket.getaddrinfo(CLOUD_HOST, 443, 0, usocket.SOCK_STREAM)[0][-1]
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
        f.close(); f = None
        return True, 'ok'
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
# TESTS
# ============================================================
def test_cached(wav_path, display_text):
    """Joue un WAV pre-genere — pas de reseau."""
    sz = file_size(wav_path)
    if sz < 1000:
        draw_menu("Fichier absent ! ({})".format(sz), COLOR_RED)
        lcd.font(lcd.FONT_Default)
        lcd.print("Lance d'abord 'Download WAV'", 10, 120, COLOR_WARN)
        time.sleep(3)
        return
    draw_alert_overlay(display_text)
    bip(900)
    rel = wav_path.replace('/flash/', '')
    try:
        speaker.playWAV(rel, volume=8)
        draw_menu("OK - WAV joue !", COLOR_GREEN)
    except Exception as e:
        draw_menu("Erreur: " + str(e)[:30], COLOR_RED)
    time.sleep(2)

def test_dynamic(humidity_pct=35):
    """Alerte humidite dynamique via TTS."""
    text = "L air est trop sec, {}% d humidite. Pensez a humidifier la piece.".format(humidity_pct)
    draw_alert_overlay(text)
    lcd.font(lcd.FONT_Default)
    lcd.print("Appel TTS...", 10, 155, COLOR_ACCENT)
    bip(900)
    gc.collect()
    ok, msg = _ssl_post_to_wav_file('/speak-wav', {'text': text}, RESP_FILE)
    if ok:
        try:
            speaker.playWAV('res/resp.wav', volume=8)
            draw_menu("OK - TTS joue !", COLOR_GREEN)
        except Exception as e:
            draw_menu("playWAV erreur: " + str(e)[:30], COLOR_RED)
    else:
        draw_menu("TTS FAIL: " + msg[:30], COLOR_RED)
    gc.collect()
    time.sleep(2)

def download_wavs():
    """Re-telecharge les 2 WAV fixes (utile si absents)."""
    for wav_path, text, label in [
        (ALERT_WAV_BREAK, "Vous travaillez depuis 45 minutes. Il est temps de faire une pause !", "break"),
        (ALERT_WAV_AIR,   "La qualite de l air est mauvaise. Pensez a aerer la piece.", "air"),
    ]:
        draw_menu("Download " + label + "...", COLOR_ACCENT)
        ok, msg = _ssl_post_to_wav_file('/speak-wav', {'text': text}, wav_path)
        print("[DL]", label, "OK" if ok else "FAIL: " + msg)
        draw_menu(label + (" OK" if ok else " FAIL: " + msg[:20]),
                  COLOR_GREEN if ok else COLOR_RED)
        time.sleep(1)
    gc.collect()

# ============================================================
# TOUCH + BUTTONS
# ============================================================
def touched_zone():
    try:
        from m5stack import touch
        t = touch.read()
        if t:
            x, y = t[0], t[1]
            if y > 205:
                if x < 107:  return 'left'
                if x < 213:  return 'mid'
                return 'right'
    except: pass
    if btnA.wasPressed(): return 'left'
    if btnB.wasPressed(): return 'mid'
    if btnC.wasPressed(): return 'right'
    return None

# ============================================================
# MAIN
# ============================================================
draw_menu("Pret !")
lcd.font(lcd.FONT_Default)
lcd.print("[A] Pause  [B] Air  [C] Humid", 10, 100, COLOR_GREY)
lcd.print("Maintien A+C = download WAV", 10, 115, COLOR_GREY)

while True:
    z = touched_zone()
    if z == 'left':
        time.sleep_ms(200)
        # Maintien long (>1s) = download
        t0 = time.time()
        while btnA.isPressed() or btnC.isPressed():
            if time.time() - t0 > 1:
                download_wavs()
                draw_menu("Pret !")
                break
            time.sleep_ms(50)
        else:
            test_cached(ALERT_WAV_BREAK,
                        "Vous travaillez depuis 45 minutes. Il est temps de faire une pause !")
            draw_menu("Pret !")
    elif z == 'mid':
        time.sleep_ms(200)
        test_cached(ALERT_WAV_AIR,
                    "La qualite de l air est mauvaise. Pensez a aerer la piece.")
        draw_menu("Pret !")
    elif z == 'right':
        time.sleep_ms(200)
        test_dynamic(35)
        draw_menu("Pret !")
    time.sleep_ms(80)
