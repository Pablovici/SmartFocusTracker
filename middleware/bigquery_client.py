# middleware/bigquery_client.py
# Handles all BigQuery read and write operations.
# All other middleware files import from here.
# Assigned to: Pablo

import os
import json
import uuid
from datetime import datetime, timezone
from google.cloud import bigquery

# ============================================================
# CLIENT INITIALIZATION
# ============================================================

# BigQuery client initialized once at module load.
# Credentials loaded automatically from GOOGLE_APPLICATION_CREDENTIALS.
# project= is passed explicitly so table paths resolve correctly
# even when running outside of a GCP environment (e.g. local dev).
client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])

# FIX ③ — Full three-part table paths: project.dataset.table
# Previously built as "dataset.table" which can fail in SQL backtick queries
# depending on the execution context.
PROJECT        = os.environ["GCP_PROJECT_ID"]
DATASET        = os.environ["GCP_DATASET_ID"]
TABLE_INDOOR   = "{}.{}.{}".format(PROJECT, DATASET, os.environ["BQ_TABLE_INDOOR"])
TABLE_OUTDOOR  = "{}.{}.{}".format(PROJECT, DATASET, os.environ["BQ_TABLE_OUTDOOR"])
TABLE_SESSIONS = "{}.{}.{}".format(PROJECT, DATASET, os.environ["BQ_TABLE_SESSIONS"])
TABLE_ALERTS   = "{}.{}.{}".format(PROJECT, DATASET, os.environ["BQ_TABLE_ALERTS"])

# ============================================================
# HELPERS
# ============================================================

def now_utc():
    # Returns current UTC time as a BigQuery-compatible ISO 8601 string.
    # Example output: "2026-05-05T14:30:00.123456+00:00"
    # BigQuery TIMESTAMP columns accept this format directly.
    return datetime.now(timezone.utc).isoformat()

def parse_dt(value):
    """
    Converts a value to a timezone-aware datetime object.
    Accepts either an already-parsed datetime or an ISO string.
    Used internally to safely compute durations between timestamps.
    """
    if isinstance(value, datetime):
        # Already a datetime — ensure it's timezone-aware
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        # Parse ISO string — Python 3.7+ handles the "+00:00" suffix
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    return None

def run_query(sql):
    # Executes a SQL query and returns results as a list of dicts.
    # query_job.result() blocks until the query completes.
    query_job = client.query(sql)
    return [dict(row) for row in query_job.result()]

# ============================================================
# INDOOR READINGS
# ============================================================

def insert_indoor(data):
    # Inserts one row of indoor sensor data.
    # Accepts partial payloads — missing fields default to None.
    row = {
        "timestamp":         now_utc(),
        "temperature":       data.get("temperature"),
        "humidity":          data.get("humidity"),
        "co2_ppm":           data.get("co2_ppm"),
        "tvoc_ppb":          data.get("tvoc_ppb"),
        "air_quality_label": data.get("air_quality_label"),
        "motion_detected":   data.get("motion_detected"),
    }
    errors = client.insert_rows_json(TABLE_INDOOR, [row])
    if errors:
        print("[BQ] insert_indoor errors:", errors)
    return len(errors) == 0

def get_latest_indoor():
    # Returns the most recent indoor sensor reading.
    # Used by GET /latest for boot sync on both M5Stacks.
    sql = "SELECT * FROM `{}` ORDER BY timestamp DESC LIMIT 1".format(TABLE_INDOOR)
    rows = run_query(sql)
    return rows[0] if rows else {}

def get_indoor_history(days=7):
    # Returns indoor readings for the last N days.
    # Used by Streamlit dashboard for historical charts.
    sql = """
        SELECT timestamp, temperature, humidity,
               co2_ppm, tvoc_ppb, air_quality_label
        FROM `{}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {} DAY)
        ORDER BY timestamp ASC
    """.format(TABLE_INDOOR, days)
    return run_query(sql)

# ============================================================
# OUTDOOR WEATHER
# ============================================================

def insert_outdoor(data):
    # Inserts one outdoor weather snapshot from OpenWeatherMap.
    row = {
        "timestamp":   now_utc(),
        "city":        data.get("city"),
        "temperature": data.get("temperature"),
        "humidity":    data.get("humidity"),
        "condition":   data.get("condition"),
        "wind_speed":  data.get("wind_speed"),
        "icon_code":   data.get("icon_code"),
    }
    errors = client.insert_rows_json(TABLE_OUTDOOR, [row])
    if errors:
        print("[BQ] insert_outdoor errors:", errors)
    return len(errors) == 0

def get_outdoor_history(days=7):
    # Returns outdoor weather history for the last N days.
    sql = """
        SELECT timestamp, temperature, humidity, condition, wind_speed
        FROM `{}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {} DAY)
        ORDER BY timestamp ASC
    """.format(TABLE_OUTDOOR, days)
    return run_query(sql)

# ============================================================
# WORK SESSIONS
# ============================================================

def save_complete_session(session_id, card_id, start_time,
                          end_time, total_work_minutes, pauses):
    """
    Inserts a complete session record into BigQuery at session end.

    Design note: we only insert once (at end), never update.
    Reason: BigQuery streaming buffer does not support DML UPDATE
    on recently inserted rows (~90 minute delay). Inserting a complete
    record avoids this limitation entirely.

    FIX ① — total_work_minutes fallback:
    If the Flask handler did not compute total_work_minutes
    (e.g. forgot to calculate it, or passed None), we compute it
    here from start_time and end_time as a safety net.
    Without this fix, total_work_minutes was always NULL in BigQuery.

    FIX ② — pauses JSON serialization:
    BigQuery JSON columns expect a JSON string, not a Python list/dict.
    json.dumps() converts the Python object to a string before insert.
    Without this fix, BigQuery rejects the row silently or stores NULL.
    """

    # FIX ① — compute duration if not provided by the caller
    if total_work_minutes is None:
        start_dt = parse_dt(start_time)
        end_dt   = parse_dt(end_time)
        if start_dt and end_dt:
            # total_seconds() gives the exact difference as a float
            # dividing by 60 converts to minutes
            total_work_minutes = (end_dt - start_dt).total_seconds() / 60
            print("[BQ] Computed total_work_minutes:", total_work_minutes)
        else:
            print("[BQ] Warning: could not compute duration — timestamps unparseable")

    # FIX ② — serialize pauses list to JSON string for BigQuery JSON column
    # pauses is a Python list of dicts (each dict has start/end timestamps)
    # BigQuery's JSON column type stores it as a string internally
    pauses_json = json.dumps(pauses) if pauses is not None else json.dumps([])

    # Ensure timestamps are strings in ISO format for BigQuery
    # parse_dt + isoformat() normalises whatever format the caller passed
    start_str = parse_dt(start_time).isoformat() if start_time else None
    end_str   = parse_dt(end_time).isoformat()   if end_time   else None

    row = {
        "session_id":         session_id,
        "rfid_card_id":       card_id,
        "start_time":         start_str,
        "end_time":           end_str,
        "total_work_minutes": total_work_minutes,
        "pauses":             pauses_json,
    }

    errors = client.insert_rows_json(TABLE_SESSIONS, [row])
    if errors:
        print("[BQ] save_complete_session errors:", errors)
    return len(errors) == 0

def get_session_history(limit=20):
    # Returns the last N completed sessions for the Streamlit dashboard.
    # Only queries rows where end_time IS NOT NULL — i.e. fully closed sessions.
    sql = """
        SELECT session_id, start_time, end_time,
               total_work_minutes, pauses
        FROM `{}`
        WHERE end_time IS NOT NULL
        ORDER BY start_time DESC
        LIMIT {}
    """.format(TABLE_SESSIONS, limit)
    return run_query(sql)

def get_session_stats():
    # Returns aggregate session statistics for the Streamlit dashboard:
    # total sessions, average duration, cumulative work time, longest session.
    sql = """
        SELECT
            COUNT(*)                AS total_sessions,
            AVG(total_work_minutes) AS avg_work_minutes,
            SUM(total_work_minutes) AS total_work_minutes,
            MAX(total_work_minutes) AS longest_session_minutes
        FROM `{}`
        WHERE end_time IS NOT NULL
    """.format(TABLE_SESSIONS)
    rows = run_query(sql)
    return rows[0] if rows else {}

# NOTE — get_current_session() has been removed.
# FIX ④: the previous implementation queried for rows WHERE end_time IS NULL,
# but the current architecture never inserts a row until the session ends.
# Therefore that query would always return None and was misleading.
# The in-memory _session dict in app.py is the authoritative source
# for the current live session state — BigQuery is for completed records only.

# ============================================================
# ALERTS
# ============================================================

def insert_alert(alert_type, message):
    # Logs an alert event (low humidity, bad air quality, etc.) to BigQuery.
    row = {
        "timestamp":    now_utc(),
        "alert_type":   alert_type,
        "message":      message,
        "acknowledged": False,
    }
    errors = client.insert_rows_json(TABLE_ALERTS, [row])
    if errors:
        print("[BQ] insert_alert errors:", errors)
    return len(errors) == 0

def get_recent_alerts(limit=10):
    # Returns the most recent alerts for the Streamlit dashboard.
    sql = """
        SELECT timestamp, alert_type, message
        FROM `{}`
        ORDER BY timestamp DESC
        LIMIT {}
    """.format(TABLE_ALERTS, limit)
    return run_query(sql)