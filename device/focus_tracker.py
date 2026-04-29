# focus_tracker.py
# Tracks focus sessions and breaks using two signals:
# 1. The PIR sensor — absence for more than 5 minutes triggers an auto-pause
# 2. The PAUSE button — manual pause toggled by the user via touchscreen
#
# The tracker also monitors how long the user has been focused without a break
# and triggers a vocal reminder when the FOCUS_ALERT_THRESHOLD_MIN is exceeded.

import time
from config import FOCUS_ALERT_THRESHOLD_MIN

# Time in seconds of continuous PIR absence before auto-pausing.
# 5 minutes is long enough to ignore brief absences (bathroom, coffee).
PIR_ABSENCE_TIMEOUT = 300


class FocusTracker:
    """
    Maintains the current focus session state.
    State transitions:
        focus → pause  : manual button press OR PIR absence > 5min
        pause → focus  : manual button press OR PIR detects presence again
    """

    def __init__(self):
        self.status          = "focus"   # Current state: "focus" or "pause"
        self.session_start   = time.time()
        self.focus_start     = time.time()  # Start of current continuous focus streak
        self.pause_start     = None         # Set when a pause begins
        self.pauses_count    = 0
        self.last_motion_time = time.time() # Last time PIR detected presence
        self.alert_triggered  = False       # Prevents repeated alerts per streak

    # ----------------------------------------------------------
    # STATE TRANSITIONS
    # ----------------------------------------------------------

    def start_pause(self):
        # Transitions from focus to pause, regardless of the trigger source.
        # Records the pause start time and increments the pause counter.
        if self.status == "focus":
            self.status      = "pause"
            self.pause_start = time.time()
            self.pauses_count += 1
            self.alert_triggered = False  # Reset so the next focus streak can alert
            print("[FOCUS] Pause started.")

    def end_pause(self):
        # Transitions from pause back to focus.
        # Resets the focus streak timer so the alert threshold starts fresh.
        if self.status == "pause":
            self.status      = "focus"
            self.focus_start = time.time()
            self.pause_start = None
            print("[FOCUS] Focus resumed.")

    def toggle_pause(self):
        # Called by the PAUSE button handler in main.py.
        # Acts as a simple toggle between focus and pause states.
        if self.status == "focus":
            self.start_pause()
        else:
            self.end_pause()

    # ----------------------------------------------------------
    # PIR-BASED AUTO PAUSE
    # ----------------------------------------------------------

    def update_motion(self, motion_detected):
        # Called every loop cycle with the latest PIR reading.
        # If the user is present, keeps the session alive.
        # If absent for more than PIR_ABSENCE_TIMEOUT, auto-pauses.
        if motion_detected:
            self.last_motion_time = time.time()
            # If the user returns while on auto-pause, resume automatically.
            if self.status == "pause":
                self.end_pause()
        else:
            absence_duration = time.time() - self.last_motion_time
            if absence_duration >= PIR_ABSENCE_TIMEOUT and self.status == "focus":
                print("[FOCUS] Auto-pause: no motion for {}s.".format(int(absence_duration)))
                self.start_pause()

    # ----------------------------------------------------------
    # FOCUS ALERT
    # ----------------------------------------------------------

    def should_alert(self):
        # Returns True if the user has been focusing continuously for longer
        # than FOCUS_ALERT_THRESHOLD_MIN without taking a break.
        # The flag prevents the alert from firing repeatedly within the same streak.
        if self.status != "focus" or self.alert_triggered:
            return False
        focus_duration_min = (time.time() - self.focus_start) / 60
        if focus_duration_min >= FOCUS_ALERT_THRESHOLD_MIN:
            self.alert_triggered = True
            return True
        return False

    # ----------------------------------------------------------
    # SESSION DATA
    # ----------------------------------------------------------

    def get_session_time_str(self):
        # Returns a human-readable string of the total session duration.
        # Used by display_manager.py to show the session timer on screen.
        elapsed = int(time.time() - self.session_start)
        hours   = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        if hours > 0:
            return "{}h {}min".format(hours, minutes)
        return "{}min".format(minutes)

    def get_state(self):
        # Returns the current tracker state as a dict compatible with
        # current_data in main.py, ready to be merged and sent to the middleware.
        return {
            "focus_status": self.status,
            "session_time": self.get_session_time_str(),
            "pauses_count": self.pauses_count
        }

    def get_session_payload(self):
        # Builds the full session record sent to POST /session at the end
        # of a session. avg_co2 and avg_humidity are computed externally
        # by main.py since this class has no access to sensor history.
        return {
            "session_start": self.session_start,
            "session_end":   time.time(),
            "duration_min":  round((time.time() - self.session_start) / 60, 1),
            "pauses_count":  self.pauses_count
        }