# middleware/bigquery_client.py
# Handles all BigQuery read and write operations.
# All other middleware files import from here.
# Assigned to: Pablo

import os
import uuid
from datetime import datetime, timezone
from google.cloud import bigquery

# ============================================================
# CLIENT INITIALIZATION
# ============================================================

# BigQuery client initialized once at module load.
# Credentials loaded automatically from GOOGLE_APPLICATION_CREDENTIALS.
client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])

# Table references built from environment variables.
DATASET        = os.environ["GCP_DATASET_ID"]
TABLE_INDOOR   = "{}.{}".format(DATASET, os.environ["BQ_TABLE_INDOOR"])
TABLE_OUTDOOR  = "{}.{}".format(DATASET, os.environ["BQ_TABLE_OUTDOOR"])
TABLE_SESSIONS = "{}.{}".format(DATASET, os.environ["BQ_TABLE_SESSIONS"])
TABLE_ALERTS   = "{}.{}".format(DATASET, os.environ["BQ_TABLE_ALERTS"])

# ============================================================
# HELPERS
# ============================================================

def now_utc():
    # Returns current UTC time as a BigQuery-compatible ISO string.
    return datetime.now(timezone.utc).isoformat()

def run_query(sql):
    # Executes a SQL query and returns results as a list of dicts.
    query_job = client.query(sql)
    return [dict(row) for row in query_job.result()]

# ============================================================
# INDOOR READINGS
# ============================================================

def insert_indoor(data):
    # Inserts one row of indoor sensor data.
    # Accepts partial payloads — missing fields default to None.
    # Called by both M5Stack A (ENVIII + PIR) and M5Stack B (TVOC).
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
    sql = """
        SELECT *
        FROM `{}`
        ORDER BY timestamp DESC
        LIMIT 1
    """.format(TABLE_INDOOR)
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
    # Inserts one outdoor weather snapshot.
    # Called whenever Flask fetches fresh data from OpenWeatherMap.
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
    # Inserts the complete session record in one shot at session end.
    # This avoids the BigQuery streaming buffer DML UPDATE limitation —
    # rows inserted via streaming cannot be updated with DML for ~90 minutes.
    # By only inserting when the session ends, we get a clean complete record.
    row = {
        "session_id":         session_id,
        "rfid_card_id":       card_id,
        "start_time":         start_time,
        "end_time":           end_time,
        "total_work_minutes": total_work_minutes,
        "pauses":             pauses,
    }
    errors = client.insert_rows_json(TABLE_SESSIONS, [row])
    if errors:
        print("[BQ] save_complete_session errors:", errors)
    return len(errors) == 0

def get_current_session():
    # Returns the most recent session that has not ended yet.
    # Used by GET /session/current for both M5Stacks.
    sql = """
        SELECT session_id, rfid_card_id, start_time, pauses,
               UNIX_SECONDS(start_time) AS start_time_unix
        FROM `{}`
        WHERE end_time IS NULL
        ORDER BY start_time DESC
        LIMIT 1
    """.format(TABLE_SESSIONS)
    rows = run_query(sql)
    return rows[0] if rows else None

def get_session_history(limit=20):
    # Returns the last N completed sessions.
    # Used by Streamlit dashboard for session analytics.
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
    # Returns aggregate session statistics for the Streamlit dashboard.
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

# ============================================================
# ALERTS
# ============================================================

def insert_alert(alert_type, message):
    # Logs an alert event to BigQuery.
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
    # Returns the most recent alerts for the dashboard.
    sql = """
        SELECT timestamp, alert_type, message
        FROM `{}`
        ORDER BY timestamp DESC
        LIMIT {}
    """.format(TABLE_ALERTS, limit)
    return run_query(sql)