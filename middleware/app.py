# middleware/app.py
# Flask API — main entry point for the middleware layer.
# Receives data from M5Stack devices and serves data to Streamlit dashboard.
# Assigned to: Pablo

import os
import json
import time
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import bigquery_client as bq
from weather_service import get_weather
from speech_service import text_to_speech, speech_to_text
from llm_service import answer_question

# ============================================================
# APP INITIALIZATION
# ============================================================

load_dotenv()
app = Flask(__name__)

# ============================================================
# SESSION STATE
# In-memory session tracker — faster than BigQuery for real-time.
# Session is only written to BigQuery once, at the end.
# This avoids the BigQuery streaming buffer DML UPDATE limitation.
# ============================================================

_session = {
    "session_id":   None,
    "card_id":      None,
    "active":       False,
    "paused":       False,
    "work_seconds": 0,
    "work_start":   None,
    "pause_start":  None,
    "pauses":       [],
}

def _restore_session():
    # Called once at module load.
    # If Cloud Run restarts mid-session, restores active session from BigQuery.
    existing = bq.get_current_session()
    if existing:
        _session["session_id"] = existing["session_id"]
        _session["card_id"]    = existing.get("rfid_card_id")
        _session["active"]     = True
        _session["paused"]     = False
        _session["work_start"] = existing.get("start_time_unix", time.time())
        print("[SESSION] Restored from BigQuery:", existing["session_id"])

_restore_session()

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    # Verifies the service is running.
    # Used by Cloud Run for container health checks.
    return jsonify({"status": "ok"}), 200

# ============================================================
# SENSOR DATA
# Single route accepts partial payloads from both M5Stack devices.
# device_a posts: temperature, humidity, motion_detected
# device_b posts: co2_ppm, tvoc_ppb, air_quality_label
# ============================================================

@app.route("/data/indoor", methods=["POST"])
def post_indoor():
    # Accepts indoor sensor data from either M5Stack device.
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    success = bq.insert_indoor(data)
    if not success:
        return jsonify({"error": "BigQuery insert failed"}), 500
    return jsonify({"status": "ok"}), 200

# ============================================================
# BOOT SYNC
# ============================================================

@app.route("/latest", methods=["GET"])
def get_latest():
    # Returns latest indoor sensor reading for M5Stack boot sync.
    data = bq.get_latest_indoor()
    return jsonify(data), 200

# ============================================================
# WEATHER
# ============================================================

@app.route("/weather", methods=["GET"])
def weather():
    # Fetches weather from OpenWeatherMap.
    # Stores current snapshot in BigQuery, returns full response.
    try:
        data = get_weather()
        bq.insert_outdoor(data["current"])
        return jsonify(data), 200
    except Exception as e:
        print("[WEATHER] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# SESSION MANAGEMENT
# ============================================================

@app.route("/session/start", methods=["POST"])
def session_start():
    # Starts a new work session in memory only.
    # BigQuery insert happens only at session end.
    data    = request.get_json()
    card_id = data.get("card_id") if data else None

    if _session["active"]:
        return jsonify({"error": "Session already active"}), 400

    session_id = str(uuid.uuid4())
    _session.update({
        "session_id":   session_id,
        "card_id":      card_id,
        "active":       True,
        "paused":       False,
        "work_seconds": 0,
        "work_start":   time.time(),
        "pause_start":  None,
        "pauses":       [],
    })
    print("[SESSION] Started:", session_id)
    return jsonify({"status": "started", "session_id": session_id}), 200

@app.route("/session/pause", methods=["POST"])
def session_pause():
    # Pauses the active session — work time stops accumulating.
    if not _session["active"] or _session["paused"]:
        return jsonify({"error": "No active session to pause"}), 400

    _session["paused"]      = True
    _session["pause_start"] = time.time()
    print("[SESSION] Paused.")
    return jsonify({"status": "paused"}), 200

@app.route("/session/resume", methods=["POST"])
def session_resume():
    # Resumes a paused session — records pause duration.
    if not _session["active"] or not _session["paused"]:
        return jsonify({"error": "Session is not paused"}), 400

    pause_end      = time.time()
    pause_duration = pause_end - _session["pause_start"]
    _session["pauses"].append({
        "pause_start":  _session["pause_start"],
        "pause_end":    pause_end,
        "duration_sec": pause_duration,
    })
    _session["paused"]      = False
    _session["pause_start"] = None
    print("[SESSION] Resumed. Pause duration:", pause_duration)
    return jsonify({"status": "resumed"}), 200

@app.route("/session/end", methods=["POST"])
def session_end():
    # Ends the active session and saves complete record to BigQuery.
    # Only insert happens here — avoids streaming buffer UPDATE issue.
    if not _session["active"]:
        return jsonify({"error": "No active session"}), 400

    # Record final pause if session ended while paused
    if _session["paused"]:
        pause_end      = time.time()
        pause_duration = pause_end - _session["pause_start"]
        _session["pauses"].append({
            "pause_start":  _session["pause_start"],
            "pause_end":    pause_end,
            "duration_sec": pause_duration,
        })

    # Calculate total work time excluding all pauses
    elapsed      = time.time() - _session["work_start"]
    total_pause  = sum(p["duration_sec"] for p in _session["pauses"])
    work_minutes = round((elapsed - total_pause) / 60, 2)

    # Convert start time to ISO string for BigQuery
    start_iso = datetime.fromtimestamp(
        _session["work_start"], tz=timezone.utc).isoformat()

    # Save complete session to BigQuery in one insert
    bq.save_complete_session(
        session_id         = _session["session_id"],
        card_id            = _session["card_id"],
        start_time         = start_iso,
        end_time           = bq.now_utc(),
        total_work_minutes = work_minutes,
        pauses             = json.dumps(_session["pauses"])
    )
    print("[SESSION] Ended. Work minutes:", work_minutes)

    # Reset in-memory state
    _session.update({
        "session_id":   None,
        "card_id":      None,
        "active":       False,
        "paused":       False,
        "work_seconds": 0,
        "work_start":   None,
        "pause_start":  None,
        "pauses":       [],
    })
    return jsonify({"status": "ended", "work_minutes": work_minutes}), 200

@app.route("/session/current", methods=["GET"])
def session_current():
    # Returns real-time session state for M5Stack A display.
    work_sec = 0
    if _session["active"] and not _session["paused"] and _session["work_start"]:
        elapsed     = time.time() - _session["work_start"]
        total_pause = sum(p["duration_sec"] for p in _session["pauses"])
        work_sec    = max(0, elapsed - total_pause)

    return jsonify({
        "active":       _session["active"],
        "paused":       _session["paused"],
        "session_id":   _session["session_id"],
        "work_seconds": work_sec,
    }), 200

# ============================================================
# TTS
# ============================================================

@app.route("/speak", methods=["POST"])
def speak():
    # Converts text to speech via Google TTS.
    # Logs alert to BigQuery if message contains alert keywords.
    data = request.get_json()
    text = data.get("text") if data else None

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        audio_b64 = text_to_speech(text)
        if any(kw in text.lower() for kw in ["warning", "alert", "poor", "low"]):
            bq.insert_alert("TTS_ALERT", text)
        return jsonify({"audio_b64": audio_b64}), 200
    except Exception as e:
        print("[TTS] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# STT + LLM
# ============================================================

@app.route("/ask", methods=["POST"])
def ask():
    # Full pipeline: audio → STT → LLM with BQ context → TTS → audio.
    data      = request.get_json()
    audio_b64 = data.get("audio_b64") if data else None

    if not audio_b64:
        return jsonify({"error": "No audio provided"}), 400

    try:
        question       = speech_to_text(audio_b64)
        answer_text    = answer_question(question)
        audio_response = text_to_speech(answer_text)
        print("[ASK] Q:", question, "| A:", answer_text)
        return jsonify({
            "question":    question,
            "answer_text": answer_text,
            "audio_b64":   audio_response,
        }), 200
    except Exception as e:
        print("[ASK] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# DASHBOARD HISTORY ROUTES
# ============================================================

@app.route("/history/indoor", methods=["GET"])
def history_indoor():
    # Returns indoor sensor history for Streamlit dashboard.
    days = request.args.get("days", 7, type=int)
    return jsonify(bq.get_indoor_history(days)), 200

@app.route("/history/outdoor", methods=["GET"])
def history_outdoor():
    # Returns outdoor weather history for Streamlit dashboard.
    days = request.args.get("days", 7, type=int)
    return jsonify(bq.get_outdoor_history(days)), 200

@app.route("/history/sessions", methods=["GET"])
def history_sessions():
    # Returns recent completed work sessions for Streamlit dashboard.
    limit = request.args.get("limit", 20, type=int)
    return jsonify(bq.get_session_history(limit)), 200

@app.route("/history/session-stats", methods=["GET"])
def session_stats():
    # Returns aggregate session statistics for Streamlit dashboard.
    return jsonify(bq.get_session_stats()), 200

@app.route("/history/alerts", methods=["GET"])
def history_alerts():
    # Returns recent alerts for Streamlit dashboard.
    limit = request.args.get("limit", 10, type=int)
    return jsonify(bq.get_recent_alerts(limit)), 200

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)