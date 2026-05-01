# sync_manager.py
# Fetches the latest sensor snapshot from the middleware at boot time.
# Ensures the display always shows meaningful data immediately after startup,
# even before the first new sensor read cycle completes.

import urequests
import ujson
from device_a.config import MIDDLEWARE_URL

def fetch_latest():
    # Calls GET /latest on the middleware, which queries BigQuery
    # for the most recent sensor row. Returns a dict on success,
    # or None if the device is offline or the middleware is unreachable.
    try:
        response = urequests.get(MIDDLEWARE_URL + "/latest", timeout=5)
        if response.status_code == 200:
            data = ujson.loads(response.text)
            response.close()
            return data
        response.close()
        return None
    except Exception as e:
        print("[SYNC] Failed:", e)
        return None