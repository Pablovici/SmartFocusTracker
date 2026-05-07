# dashboard/data_loader.py
# Fetches all data from Flask middleware for the Streamlit dashboard.
# All API calls are centralized here — app.py never calls the API directly.
# Assigned to: Amir

import os
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

try:
    MIDDLEWARE_URL = st.secrets["MIDDLEWARE_URL"]
except Exception:
    MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://localhost:8080")

TIMEOUT = 10

# ============================================================
# HELPER
# ============================================================

def _get(endpoint, params=None):
    """Generic GET — fails silently, returns {} on error."""
    try:
        r = requests.get(MIDDLEWARE_URL + endpoint, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("[DATA] Failed to fetch {}: {}".format(endpoint, e))
        return {}

# ============================================================
# CURRENT DATA
# ============================================================

@st.cache_data(ttl=30)
def get_latest():
    """Latest indoor sensor reading. TTL=30s — sensors post every ~60s."""
    return _get("/latest")

@st.cache_data(ttl=300)
def get_current_weather():
    """Weather + forecast. TTL=300s (5 min) — weather changes slowly."""
    return _get("/weather")

# SESSION SYNC FIX — TTL reduced to 2s.
# With auto-refresh every 10s, the cache is naturally invalidated each refresh.
# Short TTL ensures any in-page interaction also fetches fresh session data.
# Critical because the session is the most time-sensitive piece of data
# on the dashboard.
@st.cache_data(ttl=2)
def get_current_session():
    """Active work session state. TTL=2s for near-real-time accuracy."""
    return _get("/session/current")

# ============================================================
# HISTORICAL DATA
# ============================================================

@st.cache_data(ttl=60)
def get_indoor_history(days=7):
    data = _get("/history/indoor", params={"days": days})
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

@st.cache_data(ttl=60)
def get_outdoor_history(days=7):
    data = _get("/history/outdoor", params={"days": days})
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

@st.cache_data(ttl=60)
def get_session_history(limit=20):
    data = _get("/history/sessions", params={"limit": limit})
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    for col in ["start_time", "end_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df

@st.cache_data(ttl=60)
def get_session_stats(days=30):
    """
    Aggregate stats for the last N days.
    days=30 par défaut — aligne avec le filtre du middleware.
    Le dashboard peut passer days=slider_value pour cohérence visuelle.
    """
    return _get("/history/session-stats", params={"days": days})

@st.cache_data(ttl=60)
def get_recent_alerts(limit=10):
    data = _get("/history/alerts", params={"limit": limit})
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df