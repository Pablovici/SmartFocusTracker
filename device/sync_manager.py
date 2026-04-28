# sync_manager.py
# Handles the initial data sync from BigQuery at boot time.
# On startup, the device fetches the latest sensor values from the
# middleware so the display is never empty — even if no new readings
# have been taken yet in the current session.

import urequests
import ujson
from config import MIDDLEWARE_URL

class SyncManager:
    """
    Responsible for the boot-time synchronization with the backend.
    Calls GET /latest on the middleware, which itself queries BigQuery
    for the most recent sensor row. This ensures the device always
    displays meaningful data immediately after startup, satisfying
    the project requirement of syncing state on reboot.
    """

    def __init__(self):
        # Base URL of the Flask middleware, loaded from config.py
        # to avoid hardcoding environment-specific URLs.
        self.base_url = MIDDLEWARE_URL

    def fetch_latest(self):
        # Attempts to retrieve the latest sensor snapshot from the middleware.
        # Returns a dict of sensor values on success, or None on failure.
        # Failure cases: no WiFi, middleware unreachable, malformed response.
        try:
            response = urequests.get(self.base_url + "/latest", timeout=5)

            # HTTP 200 means the middleware responded successfully.
            # Any other status (500, 404) is treated as a failed sync.
            if response.status_code == 200:
                data = ujson.loads(response.text)
                response.close()  # Free memory — critical on microcontrollers
                return data
            else:
                print("[SYNC] Unexpected status:", response.status_code)
                response.close()
                return None

        except Exception as e:
            # Covers network timeouts, DNS failures, and connection refused.
            # Returning None signals main.py to display cached or placeholder values.
            print("[SYNC] Failed to reach middleware:", e)
            return None

    def sync(self):
        # Entry point called once by main.py immediately after WiFi connects.
        # Returns the latest data dict if sync succeeded, None otherwise.
        # main.py is responsible for deciding what to display in each case.
        print("[SYNC] Fetching latest data from BigQuery...")
        data = self.fetch_latest()

        if data:
            print("[SYNC] Sync successful:", data)
        else:
            print("[SYNC] Sync failed — will display placeholder values.")

        return data