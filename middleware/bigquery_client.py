# bigquery_client.py
# Abstraction layer for all BigQuery interactions.
# All database reads and writes go through this module —
# no other file in the middleware imports the BigQuery client directly.

import os
from google.cloud import bigquery
from datetime import datetime, timezone

# The client is instantiated once at module level.
# It automatically uses the service account defined by the
# GOOGLE_APPLICATION_CREDENTIALS environment variable.
client = bigquery.Client()

# Table references are built from environment variables so the app
# can be redeployed against a different GCP project without code changes.
PROJECT    = os.environ["GCP_PROJECT_ID"]
DATASET    = os.environ["GCP_DATASET_ID"]
T_SENSORS  = os.environ["BQ_TABLE_SENSORS"]
T_SESSIONS = os.environ["BQ_TABLE_SESSIONS"]
T_WEATHER  = os.environ["BQ_TABLE_WEATHER"]

def full_table(name):
    # Returns the fully qualified BigQuery table ID: project.dataset.table
    return "{}.{}.{}".format(PROJECT, DATASET, name)


# ----------------------------------------------------------
# SENSOR READINGS
# ----------------------------------------------------------

def insert_sensor_reading(data):
    # Inserts one row into sensor_readings.
    # data is the dict received directly from the M5Stack payload.
    # timestamp is generated server-side to ensure consistency.
    row = {
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "temperature_in":  data.get("temperature"),
        "humidity":        data.get("humidity"),
        "co2_ppm":         data.get("co2_ppm"),
        "tvoc_ppb":        data.get("tvoc_ppb"),
        "motion_detected": data.get("motion"),
        "focus_status":    data.get("focus_status", "focus")
    }
    errors = client.insert_rows_json(full_table(T_SENSORS), [row])
    if errors:
        print("[BQ] Insert error:", errors)
        return False
    return True

def fetch_latest_sensor():
    # Returns the most recent row from sensor_readings.
    # Used by the device at boot to restore the last known state.
    query = """
        SELECT *
        FROM `{table}`
        ORDER BY timestamp DESC
        LIMIT 1
    """.format(table=full_table(T_SENSORS))

    results = client.query(query).result()
    for row in results:
        return dict(row)
    return None


# ----------------------------------------------------------
# FOCUS SESSIONS
# ----------------------------------------------------------

def insert_focus_session(session):
    # Inserts a completed focus session into focus_sessions.
    # session_end and duration_min may be None if the session
    # was interrupted (e.g. device reboot mid-session).
    row = {
        "session_id":    session.get("session_id"),
        "session_start": session.get("session_start"),
        "session_end":   session.get("session_end"),
        "duration_min":  session.get("duration_min"),
        "pauses_count":  session.get("pauses_count"),
        "avg_co2_ppm":   session.get("avg_co2_ppm"),
        "avg_humidity":  session.get("avg_humidity")
    }
    errors = client.insert_rows_json(full_table(T_SESSIONS), [row])
    if errors:
        print("[BQ] Session insert error:", errors)
        return False
    return True

def fetch_sensor_history(hours=24):
    # Returns all sensor readings from the last N hours.
    # Used by the Streamlit dashboard to plot historical data.
    query = """
        SELECT *
        FROM `{table}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        ORDER BY timestamp ASC
    """.format(table=full_table(T_SENSORS), hours=hours)

    results = client.query(query).result()
    return [dict(row) for row in results]


# ----------------------------------------------------------
# WEATHER HISTORY
# ----------------------------------------------------------

def insert_weather(data):
    # Inserts one weather snapshot into weather_history.
    # forecast_json stores the 7-day forecast as a serialized
    # JSON string to avoid a complex nested schema in BigQuery.
    import json
    row = {
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "temp_out":      data.get("temp_out"),
        "humidity_out":  data.get("humidity_out"),
        "description":   data.get("description"),
        "icon_code":     data.get("icon_code"),
        "wind_speed":    data.get("wind_speed"),
        "forecast_json": json.dumps(data.get("forecast", []))
    }
    errors = client.insert_rows_json(full_table(T_WEATHER), [row])
    if errors:
        print("[BQ] Weather insert error:", errors)
        return False
    return True
