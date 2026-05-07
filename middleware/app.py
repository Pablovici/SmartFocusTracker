# middleware/app.py
# Flask API — main entry point for the middleware layer.
# Receives data from M5Stack devices and serves data to Streamlit dashboard.
# All BigQuery operations are delegated to bigquery_client.py.
# Assigned to: Pablo

import os
import uuid
import json
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import bigquery_client as bq
from weather_service import get_weather
from speech_service import text_to_speech, text_to_speech_wav, speech_to_text
from llm_service import answer_question

# ============================================================
# APP INITIALIZATION
# ============================================================

load_dotenv()

app = Flask(__name__)

# ============================================================
# IN-MEMORY SESSION STATE
#
# The session dict is the single source of truth for the live session.
# BigQuery is written ONCE at session end via save_complete_session().
# This avoids the BigQuery streaming buffer UPDATE limitation —
# rows inserted via streaming cannot be updated with DML for ~90 minutes.
#
# Known limitation: if Cloud Run restarts mid-session, in-memory state
# is lost. The device will show idle on next boot sync. The user must
# start a new session manually. Acceptable trade-off for this design.
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

# Weather cache — avoids hammering OpenWeatherMap on every request.
# Both devices + Streamlit can call /weather independently;
# without caching this could trigger rate-limiting.
# Cache TTL matches the devices' WEATHER_INTERVAL (30 min).
_weather_cache = {"data": None, "ts": 0}
WEATHER_CACHE_TTL = 1800  # seconds (30 min)

# ============================================================
# HELPERS
# ============================================================

def _unix_to_iso(ts):
    """Converts a Unix float timestamp to a UTC ISO 8601 string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

def _compute_work_seconds():
    """
    Computes real-time elapsed work seconds for the active session.
    Subtracts all completed pauses and the ongoing pause (if any).
    Returns the accumulated value even when paused — not 0.
    """
    if not _session["active"] or not _session["work_start"]:
        return 0

    now         = time.time()
    elapsed     = now - _session["work_start"]
    total_pause = sum(p["duration_sec"] for p in _session["pauses"])

    if _session["paused"] and _session["pause_start"]:
        total_pause += now - _session["pause_start"]

    return max(0, elapsed - total_pause)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    # Used by Cloud Run for container health checks.
    return jsonify({"status": "ok"}), 200

# ============================================================
# SENSOR DATA
# ============================================================

@app.route("/data/indoor", methods=["POST"])
def post_indoor():
    # Accepts indoor sensor data from either M5Stack device.
    # Both devices post to the same endpoint — missing fields default to None.
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
    # Returns the most recent indoor sensor reading.
    # Called by M5Stack devices on boot to display last known values.
    data = bq.get_latest_indoor()
    return jsonify(data), 200

# ============================================================
# WEATHER
# ============================================================

@app.route("/weather", methods=["GET"])
def weather():
    """
    Returns current weather + forecast.
    Responses are cached for WEATHER_CACHE_TTL (30 min) to avoid
    hammering OpenWeatherMap on every poll from devices and Streamlit.
    If the external fetch fails but a cached response exists, the stale
    cache is returned with a 200 so devices always get usable data.
    """
    now = time.time()
    if _weather_cache["data"] and now - _weather_cache["ts"] < WEATHER_CACHE_TTL:
        return jsonify(_weather_cache["data"]), 200
    try:
        data = get_weather()
        bq.insert_outdoor(data["current"])
        _weather_cache["data"] = data
        _weather_cache["ts"]   = now
        return jsonify(data), 200
    except Exception as e:
        print("[WEATHER] Error:", e)
        if _weather_cache["data"]:
            print("[WEATHER] Returning stale cache")
            return jsonify(_weather_cache["data"]), 200
        return jsonify({"error": str(e)}), 500

# ============================================================
# SESSION MANAGEMENT
# ============================================================

@app.route("/session/start", methods=["POST"])
def session_start():
    """
    Starts a new work session.
    A UUID is generated and held in memory — no BigQuery write at session start.
    The full record is written at session end via save_complete_session().
    card_id is stored so /session/current can return it for device boot sync.
    """
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
    print("[SESSION] Started:", session_id, "card:", card_id)
    return jsonify({"status": "started", "session_id": session_id}), 200

@app.route("/session/pause", methods=["POST"])
def session_pause():
    """
    Pauses the active session.
    Records pause_start as a Unix timestamp for duration computation.
    """
    if not _session["active"] or _session["paused"]:
        return jsonify({"error": "No active session to pause"}), 400

    _session["paused"]      = True
    _session["pause_start"] = time.time()
    print("[SESSION] Paused.")
    return jsonify({"status": "paused"}), 200

@app.route("/session/resume", methods=["POST"])
def session_resume():
    """
    Resumes a paused session.
    Appends the completed pause to _session["pauses"] with:
    - pause_start / pause_end as human-readable ISO strings
    - duration_sec rounded to 1 decimal place
    The rounded float is still used for sum() in session_end().
    """
    if not _session["active"] or not _session["paused"]:
        return jsonify({"error": "Session is not paused"}), 400

    pause_end      = time.time()
    pause_duration = pause_end - _session["pause_start"]

    _session["pauses"].append({
        "pause_start":  _unix_to_iso(_session["pause_start"]),
        "pause_end":    _unix_to_iso(pause_end),
        "duration_sec": round(pause_duration, 1),
    })
    _session["paused"]      = False
    _session["pause_start"] = None
    print("[SESSION] Resumed. Pause duration: {:.1f}s".format(pause_duration))
    return jsonify({"status": "resumed"}), 200

@app.route("/session/end", methods=["POST"])
def session_end():
    """
    Ends the active session and writes the complete record to BigQuery.
    Calls bq.save_complete_session() — the only correct function for this.
    Work time = total elapsed - sum of all pause durations.
    If ended while paused, the current pause is closed first (with ISO timestamps).
    _session is fully reset after the BigQuery write.
    """
    if not _session["active"]:
        return jsonify({"error": "No active session"}), 400

    end_time = time.time()

    # Close the current pause if session ended while paused
    if _session["paused"] and _session["pause_start"]:
        pause_duration = end_time - _session["pause_start"]
        _session["pauses"].append({
            "pause_start":  _unix_to_iso(_session["pause_start"]),
            "pause_end":    _unix_to_iso(end_time),
            "duration_sec": round(pause_duration, 1),
        })

    # Compute actual work time (elapsed minus all pauses)
    elapsed      = end_time - _session["work_start"]
    total_pause  = sum(p["duration_sec"] for p in _session["pauses"])
    work_minutes = round((elapsed - total_pause) / 60, 2)

    # Convert Unix timestamps to ISO strings for BigQuery TIMESTAMP columns
    start_iso = _unix_to_iso(_session["work_start"])
    end_iso   = _unix_to_iso(end_time)

    # Write the complete session record to BigQuery in one atomic insert
    success = bq.save_complete_session(
        session_id         = _session["session_id"],
        card_id            = _session["card_id"],
        start_time         = start_iso,
        end_time           = end_iso,
        total_work_minutes = work_minutes,
        pauses             = _session["pauses"],
    )

    if not success:
        print("[SESSION] Warning: BigQuery write failed — session data may be lost")

    print("[SESSION] Ended. Work minutes: {:.2f}".format(work_minutes))

    # Full reset — _session returns to clean idle state
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
    """
    Returns real-time session state for M5Stack devices and Streamlit.
    card_id included for Device B boot sync (restores active_card_id).
    work_seconds computed live — correct even when paused.
    """
    return jsonify({
        "active":       _session["active"],
        "paused":       _session["paused"],
        "session_id":   _session["session_id"],
        "card_id":      _session["card_id"],
        "work_seconds": _compute_work_seconds(),
    }), 200

# ============================================================
# TTS
# ============================================================

@app.route("/speak-wav", methods=["POST"])
def speak_wav():
    # Returns raw LINEAR16 WAV bytes streamed directly to M5Stack flash.
    data = request.get_json()
    text = data.get("text") if data else None
    if not text:
        return jsonify({"error": "No text provided"}), 400
    try:
        wav_bytes = text_to_speech_wav(text)
        return wav_bytes, 200, {
            "Content-Type":   "audio/wav",
            "Content-Length": str(len(wav_bytes)),
        }
    except Exception as e:
        print("[TTS-WAV] Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/speak", methods=["POST"])
def speak():
    # Converts text to speech. Logs alert to BigQuery if keywords present.
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

@app.route("/llm", methods=["POST"])
def llm():
    # Text-only LLM endpoint with optional sensor context.
    data     = request.get_json()
    question = data.get("question") if data else None
    context  = data.get("context")  if data else None
    if not question:
        return jsonify({"error": "No question provided"}), 400
    try:
        answer = answer_question(question, context=context)
        print("[LLM] Q:", question, "| A:", answer)
        return jsonify({"answer": answer}), 200
    except Exception as e:
        print("[LLM] Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/ask", methods=["POST"])
def ask():
    # Full STT → LLM → TTS pipeline.
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
    days = request.args.get("days", 7, type=int)
    return jsonify(bq.get_indoor_history(days)), 200

@app.route("/history/outdoor", methods=["GET"])
def history_outdoor():
    days = request.args.get("days", 7, type=int)
    return jsonify(bq.get_outdoor_history(days)), 200

@app.route("/history/sessions", methods=["GET"])
def history_sessions():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(bq.get_session_history(limit)), 200

@app.route("/history/session-stats", methods=["GET"])
def session_stats():
    days = request.args.get("days", 30, type=int)
    return jsonify(bq.get_session_stats(days=days)), 200

@app.route("/history/alerts", methods=["GET"])
def history_alerts():
    limit = request.args.get("limit", 10, type=int)
    return jsonify(bq.get_recent_alerts(limit)), 200

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)