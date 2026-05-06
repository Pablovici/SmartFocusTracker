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

# MIDDLEWARE_URL resolution order:
# 1. st.secrets["MIDDLEWARE_URL"]  → Streamlit Cloud deployment
# 2. os.environ["MIDDLEWARE_URL"]  → local dev with .env file
# 3. localhost fallback             → bare local dev
#
# On Streamlit Cloud, secrets are defined in
# dashboard/.streamlit/secrets.toml (never committed to Git).
# Locally, define MIDDLEWARE_URL in dashboard/.env.
try:
    MIDDLEWARE_URL = st.secrets["MIDDLEWARE_URL"]
except Exception:
    MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://localhost:8080")

# Request timeout — prevents the dashboard from hanging
TIMEOUT = 10

# ============================================================
# HELPER
# ============================================================

def _get(endpoint, params=None):
    """
    Generic GET request to the middleware.
    Returns parsed JSON on success, empty dict/list on failure.
    Fails silently — dashboard shows empty state instead of crashing.
    """
    try:
        r = requests.get(
            MIDDLEWARE_URL + endpoint,
            params=params,
            timeout=TIMEOUT,
        )
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
    """
    Latest indoor sensor reading.
    TTL=30s — sensors post roughly every 60s, 30s cache is a good balance.
    Cached so that multiple widgets reading this don't fire multiple requests.
    """
    return _get("/latest")

@st.cache_data(ttl=300)
def get_current_weather():
    """
    Current weather + forecast from OpenWeatherMap via middleware.
    TTL=300s (5 minutes) — weather doesn't change faster than this.

    Without caching, every Streamlit interaction triggered a fresh
    OpenWeatherMap API call AND a BigQuery insert. This was wasteful
    and a potential source of rate-limiting and instability.
    """
    return _get("/weather")

@st.cache_data(ttl=5)
def get_current_session():
    """
    Active work session state from the middleware in-memory dict.
    TTL=5s — short TTL so the dashboard stays near real-time
    without hammering the server on every page interaction.

    Previously uncached: every slider change or button click fired
    a GET /session/current request, creating bursts of traffic that
    could destabilize the Flask server and corrupt the device's
    fetch_session() responses.
    """
    return _get("/session/current")

# ============================================================
# HISTORICAL DATA — Returns pandas DataFrames for Plotly charts
# ============================================================

@st.cache_data(ttl=60)
def get_indoor_history(days=7):
    """
    Indoor sensor history for the last N days.
    TTL=60s — historical data doesn't need sub-minute freshness.
    """
    data = _get("/history/indoor", params={"days": days})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

@st.cache_data(ttl=60)
def get_outdoor_history(days=7):
    """
    Outdoor weather history for the last N days.
    TTL=60s — same rationale as indoor history.
    """
    data = _get("/history/outdoor", params={"days": days})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

@st.cache_data(ttl=60)
def get_session_history(limit=20):
    """
    Recent completed work sessions.
    TTL=60s — new sessions end at most every few minutes.
    """
    data = _get("/history/sessions", params={"limit": limit})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    for col in ["start_time", "end_time"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df

@st.cache_data(ttl=60)
def get_session_stats():
    """
    Aggregate session statistics (totals, averages).
    TTL=60s — aggregates change only when sessions end.
    """
    return _get("/history/session-stats")

@st.cache_data(ttl=60)
def get_recent_alerts(limit=10):
    """
    Most recent alert events.
    TTL=60s — alerts are not instantaneous dashboard data.
    """
    data = _get("/history/alerts", params={"limit": limit})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df