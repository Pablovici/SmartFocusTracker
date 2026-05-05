# device_a/sync_manager.py
# Fetches latest sensor data from middleware at boot.

import urequests
import ujson
from config import MIDDLEWARE_URL

def fetch_latest():
    try:
        r = urequests.get(MIDDLEWARE_URL + "/latest", timeout=5)
        if r.status_code == 200:
            data = ujson.loads(r.text)
            r.close()
            return data
        r.close()
        return None
    except Exception as e:
        print("[SYNC] Failed:", e)
        return None
