# middleware/app.py
# Flask API — main entry point for the middleware layer.
# Receives data from M5Stack devices and serves data to Streamlit dashboard.
# All business logic is delegated to service modules.
# Assigned to: Pablo

import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import bigquery_client as bq
from weather_service import get_weather
from speech_service import text_to_speech, speech_to_text
from llm_service import answer_question

# ============================================================
# APP INITIALIZATION
# ============================================================

# Load environment variables from .env file.
# Must be called before any os.environ access.
load_dotenv()

app = Flask(__name__)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    # Simple endpoint to verify the service is running.
    # Used by Cloud Run to check container health.
    return jsonify({"status": "ok"}), 200

# ============================================================
# SENSOR DATA — M5Stack A posts indoor readings here
# ============================================================

@app.route("/data/indoor", methods=["POST"])
def post_indoor():
    # Receives indoor sensor payload from M5Stack A.
    # Validates presence of required fields before inserting.
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    success = bq.insert_indoor(data)
    if not success:
        return jsonify({"error": "BigQuery insert failed"}), 500

    return jsonify({"status": "ok"}), 200

# ============================================================
# ENVIRONMENT DATA — M5Stack B posts TVOC/eCO2 readings here
# ============================================================

@app.route("/data/environment", methods=["POST"])
def post_environment():
    # Receives air quality payload from M5Stack B.
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    success = bq.insert_indoor(data)
    if not success:
        return jsonify({"error": "BigQuery insert failed"}), 500

    return jsonify({"status": "ok"}), 200

# ============================================================
# BOOT SYNC — Both M5Stacks call this on startup
# ============================================================

@app.route("/latest", methods=["GET"])
def get_latest():
    # Returns the latest indoor sensor reading for boot sync.
    # M5Stack devices use this to populate their display on startup.
    data = bq.get_latest_indoor()
    return jsonify(data), 200

# ============================================================
# WEATHER — M5Stack A fetches current weather + forecast
# ============================================================

@app.route("/weather", methods=["GET"])
def weather():
    # Fetches weather from OpenWeatherMap and stores snapshot in BigQuery.
    # Forecast data is returned but not stored — display only.
    try:
        data = get_weather()
        # Store current conditions snapshot in BigQuery
        bq.insert_outdoor(data["current"])
        return jsonify(data), 200
    except Exception as e:
        print("[WEATHER] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# SESSIONS — M5Stack B posts session lifecycle events here
# ============================================================

# In-memory session state — tracks active session between requests.
# This is the single source of truth for session state in the middleware.
_session = {
    "session_id":   None,
    "active":       False,
    "paused":       False,
    "work_seconds": 0,
    "pause_start":  None,
    "work_start":   None,
    "pauses":       [],
}

@app.route("/session/start", methods=["POST"])
def session_start():
    # Creates a new session in BigQuery and initializes in-memory state.
    data    = request.get_json()
    card_id = data.get("card_id") if data else None

    if _session["active"]:
        return jsonify({"error": "Session already active"}), 400

    session_id = bq.start_session(card_id)
    if not session_id:
        return jsonify({"error": "Failed to create session"}), 500

    import time
    _session.update({
        "session_id":   session_id,
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
    # Records pause start time — work_seconds stops accumulating.
    import time
    if not _session["active"] or _session["paused"]:
        return jsonify({"error": "No active session to pause"}), 400

    _session["paused"]      = True
    _session["pause_start"] = time.time()
    print("[SESSION] Paused.")
    return jsonify({"status": "paused"}), 200

@app.route("/session/resume", methods=["POST"])
def session_resume():
    # Records pause duration and resumes work time accumulation.
    import time
    if not _session["active"] or not _session["paused"]:
        return jsonify({"error": "Session is not paused"}), 400

    pause_duration = time.time() - _session["pause_start"]
    _session["pauses"].append({
        "pause_start": _session["pause_start"],
        "pause_end":   time.time(),
        "duration_sec": pause_duration,
    })
    _session["paused"]      = False
    _session["pause_start"] = None
    print("[SESSION] Resumed. Pause duration:", pause_duration)
    return jsonify({"status": "resumed"}), 200

@app.route("/session/end", methods=["POST"])
def session_end():
    # Finalizes session — calculates total work time excluding pauses.
    # Updates BigQuery row via DML UPDATE.
    import time, ujson
    if not _session["active"]:
        return jsonify({"error": "No active session"}), 400

    # If still paused when ended, record the final pause
    if _session["paused"]:
        pause_duration = time.time() - _session["pause_start"]
        _session["pauses"].append({
            "pause_start":  _session["pause_start"],
            "pause_end":    time.time(),
            "duration_sec": pause_duration,
        })

    # Total work time = elapsed time - sum of all pause durations
    elapsed       = time.time() - _session["work_start"]
    total_pause   = sum(p["duration_sec"] for p in _session["pauses"])
    work_seconds  = elapsed - total_pause
    work_minutes  = round(work_seconds / 60, 2)

    bq.end_session(
        _session["session_id"],
        work_minutes,
        ujson.dumps(_session["pauses"])
    )

    print("[SESSION] Ended. Work minutes:", work_minutes)

    # Reset in-memory state
    _session.update({
        "session_id":   None,
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
    # Returns current session state for M5Stack A display
    # and for boot sync on M5Stack B.
    import time
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
# TTS — M5Stack A requests speech synthesis here
# ============================================================

@app.route("/speak", methods=["POST"])
def speak():
    # Converts text to speech via Google TTS.
    # Returns audio as base64-encoded string.
    data = request.get_json()
    text = data.get("text") if data else None

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        audio_b64 = text_to_speech(text)
        # Log alert to BigQuery if text is an alert message
        if any(kw in text.lower() for kw in ["warning", "alert", "poor", "low"]):
            bq.insert_alert("TTS_ALERT", text)
        return jsonify({"audio_b64": audio_b64}), 200
    except Exception as e:
        print("[TTS] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# STT + LLM — M5Stack A sends audio, gets spoken answer back
# ============================================================

@app.route("/ask", methods=["POST"])
def ask():
    # Full pipeline: audio → STT → LLM with BQ context → TTS → audio.
    # M5Stack A sends raw audio, receives base64 audio response.
    data      = request.get_json()
    audio_b64 = data.get("audio_b64") if data else None

    if not audio_b64:
        return jsonify({"error": "No audio provided"}), 400

    try:
        # Step 1: Convert audio to text
        question = speech_to_text(audio_b64)
        print("[ASK] Question:", question)

        # Step 2: Generate answer with BigQuery context
        answer_text = answer_question(question)
        print("[ASK] Answer:", answer_text)

        # Step 3: Convert answer to speech
        audio_response = text_to_speech(answer_text)

        return jsonify({
            "question":    question,
            "answer_text": answer_text,
            "audio_b64":   audio_response,
        }), 200

    except Exception as e:
        print("[ASK] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# DASHBOARD DATA — Streamlit fetches historical data here
# ============================================================

@app.route("/history/indoor", methods=["GET"])
def history_indoor():
    # Returns indoor sensor history for the last N days.
    days = request.args.get("days", 7, type=int)
    return jsonify(bq.get_indoor_history(days)), 200

@app.route("/history/outdoor", methods=["GET"])
def history_outdoor():
    # Returns outdoor weather history for the last N days.
    days = request.args.get("days", 7, type=int)
    return jsonify(bq.get_outdoor_history(days)), 200

@app.route("/history/sessions", methods=["GET"])
def history_sessions():
    # Returns recent completed work sessions.
    limit = request.args.get("limit", 20, type=int)
    return jsonify(bq.get_session_history(limit)), 200

@app.route("/history/session-stats", methods=["GET"])
def session_stats():
    # Returns aggregate session statistics for dashboard.
    return jsonify(bq.get_session_stats()), 200

@app.route("/history/alerts", methods=["GET"])
def history_alerts():
    # Returns recent alerts for dashboard.
    limit = request.args.get("limit", 10, type=int)
    return jsonify(bq.get_recent_alerts(limit)), 200

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)