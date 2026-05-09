# test_voice.py — v7 : ordre correct record2file(duration, filename)
from m5stack import lcd
lcd.clear(0x1a1a2e)
lcd.font(lcd.FONT_Default)
_y = [5]

def log(msg, color=0xFFFFFF):
    if _y[0] > 220:
        lcd.clear(0x1a1a2e)
        _y[0] = 5
    print("[LOG]", msg)
    lcd.print(str(msg)[:42], 5, _y[0], color)
    _y[0] += 12

log("== VOICE TEST v7 ==", 0x00FFFF)

import gc, os, time
from m5stack import speaker, btnA, btnB, btnC
from MediaTrans.MicRecord import MicRecord

gc.collect()
mic = MicRecord()
log("mic OK", 0x00FF00)

try:
    os.mkdir('/flash/res')
except: pass

VOICE_FILE  = '/flash/voice.wav'
RESP_FILE   = 'res/resp.wav'   # chemin relatif comme Zak
RECORD_SECS = 5

import usocket, ussl, ubinascii, urequests, ujson
CLOUD_HOST = "smartfocustracker-middleware-1054003632036.europe-west6.run.app"
MIDDLEWARE  = "https://" + CLOUD_HOST
log("imports OK", 0x00FF00)

def file_size(p):
    try: return os.stat(p)[6]
    except: return 0

def safe_remove(p):
    try: os.remove(p)
    except: pass

def draw(status, step="", col=0xFFFFFF):
    lcd.clear(0x1a1a2e)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Voice Test", 90, 6, 0x00BCD4)
    lcd.line(0, 30, 320, 30, 0x444444)
    lcd.print(status[:26], 10, 40, col)
    if step:
        lcd.font(lcd.FONT_Default)
        lcd.print(step[:42], 10, 65, 0xAAAAAA)
    lcd.font(lcd.FONT_Default)
    lcd.fillRect(0,   210, 106, 30, 0x333333)
    lcd.fillRect(107, 210, 106, 30, 0x004466)
    lcd.fillRect(213, 210, 107, 30, 0x333333)
    lcd.print("Quitter", 14,  218, 0xAAAAAA)
    lcd.print("PARLER",  128, 218, 0x00FFFF)
    lcd.print("Quitter", 220, 218, 0xAAAAAA)

def bip(freq=1200):
    try: speaker.sing(freq, 1, 200)
    except:
        try: speaker.playTone(freq, 1)
        except: pass

def _ssl_post_wav_transcribe(filepath):
    sz = file_size(filepath)
    if sz <= 0: return None, 'empty file'
    prefix   = b'{"audio_b64":"'
    suffix   = b'"}'
    b64_len  = ((sz + 2) // 3) * 4
    body_len = len(prefix) + b64_len + len(suffix)
    req = ('POST /voice/transcribe HTTP/1.1\r\nHost: ' + CLOUD_HOST +
           '\r\nContent-Type: application/json\r\nContent-Length: ' +
           str(body_len) + '\r\nConnection: close\r\n\r\n').encode()
    s = ss = f = None
    try:
        addr = usocket.getaddrinfo(CLOUD_HOST, 443, 0, usocket.SOCK_STREAM)[0][-1]
        s = usocket.socket(); s.settimeout(60); s.connect(addr)
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
        code = int(raw.split(b'\r\n')[0].decode().split(' ')[1])
        parts = raw.split(b'\r\n\r\n', 1)
        return code, parts[1].decode() if len(parts) > 1 else ''
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

def _ssl_post_to_wav(path, payload, out_file):
    body = ujson.dumps(payload).encode()
    req  = ('POST ' + path + ' HTTP/1.1\r\nHost: ' + CLOUD_HOST +
            '\r\nContent-Type: application/json\r\nContent-Length: ' +
            str(len(body)) + '\r\nConnection: close\r\n\r\n').encode() + body
    s = ss = f = None
    try:
        addr = usocket.getaddrinfo(CLOUD_HOST, 443, 0, usocket.SOCK_STREAM)[0][-1]
        s = usocket.socket(); s.settimeout(30); s.connect(addr)
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

def _llm_ask(question):
    try:
        r = urequests.post(MIDDLEWARE + "/llm",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"question": question}))
        if r.status_code == 200:
            ans = ujson.loads(r.text).get("answer", "")
            r.close(); return ans
        r.close(); return ""
    except Exception as e:
        print("[LLM]", e); return ""

def voice_test():
    draw("Preparez-vous...", "Parlez apres le bip")
    time.sleep(1)
    bip(1200)
    time.sleep_ms(150)

    draw(">>> PARLEZ <<<", "Enregistrement {}s...".format(RECORD_SECS), col=0xFF4444)
    try:
        # ORDRE CORRECT : durée en premier, fichier en second
        mic.record2file(RECORD_SECS, VOICE_FILE)
    except Exception as e:
        print("[MIC]", e)

    bip(800)
    sz = file_size(VOICE_FILE)
    print("[MIC] taille:", sz)

    if sz < 1000:
        draw("Rien entendu", "Taille: {}B — parle plus fort".format(sz), col=0xFFAA00)
        time.sleep(3); return

    draw("Transcription...", "Envoi audio...", col=0x00BCD4)
    code, body = _ssl_post_wav_transcribe(VOICE_FILE)
    gc.collect()
    print("[STT]", code, (body or "")[:60])

    if code is None or code != 200:
        draw("Erreur STT", "Code: {}".format(code), col=0xFF0000)
        time.sleep(3); return

    try:
        transcript = ujson.loads(body).get("transcript", "").strip()
    except Exception as e:
        draw("Erreur JSON", str(e)[:40], col=0xFF0000)
        time.sleep(2); return

    print("[STT] transcript:", transcript)
    if not transcript:
        draw("Rien transcrit", "Parle plus pres du micro", col=0xFFAA00)
        time.sleep(3); return

    draw("Reflexion...", transcript[:40], col=0x00BCD4)
    answer = _llm_ask(transcript)
    gc.collect()
    print("[LLM]", answer)

    if not answer:
        draw("IA indisponible", "", col=0xFFAA00)
        time.sleep(3); return

    draw("Synthese...", answer[:40], col=0x00BCD4)
    ok, msg = _ssl_post_to_wav('/speak-wav', {'text': answer}, '/flash/' + RESP_FILE)
    gc.collect()
    print("[TTS] ok:", ok, msg)

    if ok:
        draw("Reponse !", "Lecture...", col=0x00FF00)
        try:
            speaker.playWAV(RESP_FILE, volume=8)
        except Exception as e:
            print("[WAV]", e)
    else:
        draw("TTS KO", msg[:40], col=0xFF0000)
    gc.collect()

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
    if btnB.wasPressed(): return 'mid'
    if btnA.wasPressed() or btnC.wasPressed(): return 'left'
    return None

log("Pret !", 0x00FF00)
time.sleep_ms(500)
draw("Pret !", "Touche PARLER pour commencer", col=0x00FF00)

while True:
    z = touched_zone()
    if z == 'mid':
        time.sleep_ms(200)
        try:
            voice_test()
        except Exception as e:
            draw("Erreur", str(e)[:40], col=0xFF0000)
            time.sleep(2)
        draw("Pret !", "Touche PARLER pour retester", col=0x00FF00)
    elif z == 'left':
        break
    time.sleep_ms(80)
