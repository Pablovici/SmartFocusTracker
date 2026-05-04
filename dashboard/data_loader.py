# dashboard/data_loader.py
# Fetches all data from Flask middleware for the Streamlit dashboard.
# All API calls are centralized here — app.py never calls the API directly.
# Assigned to: Amir

import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

# Middleware URL loaded from environment — never hardcoded
MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://localhost:8080")

# Request timeout in seconds — avoids blocking the dashboard indefinitely
TIMEOUT = 10

# ============================================================
# HELPER
# ============================================================

def _get(endpoint, params=None):
    # Generic GET request to middleware.
    # Returns parsed JSON on success, empty dict on failure.
    # Fails silently — dashboard shows empty state instead of crashing.
    try:
        r = requests.get(
            MIDDLEWARE_URL + endpoint,
            params=params,
            timeout=TIMEOUT
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("[DATA] Failed to fetch {}: {}".format(endpoint, e))
        return {}

# ============================================================
# CURRENT DATA
# ============================================================

def get_latest():
    # Returns the latest indoor sensor reading as a dict.
    # Used for the real-time metrics at the top of the dashboard.
    return _get("/latest")

def get_current_weather():
    # Returns current weather and forecast from middleware.
    return _get("/weather")

def get_current_session():
    # Returns the active work session state.
    return _get("/session/current")

# ============================================================
# HISTORICAL DATA — Returns pandas DataFrames for charts
# ============================================================

def get_indoor_history(days=7):
    # Returns indoor sensor history as a DataFrame.
    # Columns: timestamp, temperature, humidity, co2_ppm,
    #          tvoc_ppb, air_quality_label
    data = _get("/history/indoor", params={"days": days})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        # Convert timestamp strings to datetime for Plotly charts
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

def get_outdoor_history(days=7):
    # Returns outdoor weather history as a DataFrame.
    # Columns: timestamp, temperature, humidity, condition, wind_speed
    data = _get("/history/outdoor", params={"days": days})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

def get_session_history(limit=20):
    # Returns recent completed work sessions as a DataFrame.
    # Columns: session_id, start_time, end_time, total_work_minutes
    data = _get("/history/sessions", params={"limit": limit})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    for col in ["start_time", "end_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df

def get_session_stats():
    # Returns aggregate session statistics as a dict.
    # Keys: total_sessions, avg_work_minutes,
    #       total_work_minutes, longest_session_minutes
    return _get("/history/session-stats")

def get_recent_alerts(limit=10):
    # Returns recent alerts as a DataFrame.
    # Columns: timestamp, alert_type, message
    data = _get("/history/alerts", params={"limit": limit})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df