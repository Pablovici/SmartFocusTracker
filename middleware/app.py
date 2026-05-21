# middleware/app.py
# Flask API — main entry point for the middleware layer.
# Receives data from M5Stack devices and serves data to Streamlit dashboard.
# All BigQuery operations are delegated to bigquery_client.py.
# Assigned to: Pablo

import os
import re
import uuid
import json
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import bigquery_client as bq
from weather_service import get_weather, CITY as DEFAULT_CITY
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

# Per-city weather cache — each city has its own TTL slot.
# Key: lowercase city name. Avoids evicting device's default city
# when Streamlit fetches a different city.
# Structure: _weather_cache["lausanne"] = {"data": {...}, "ts": 1234567.89}
_weather_cache: dict = {}
WEATHER_CACHE_TTL = 1800  # seconds (30 min per city)

# ============================================================
# CITY EXTRACTION — for voice queries
# ============================================================

_WEATHER_KEYWORDS = [
    "météo", "meteo", "temps", "weather", "température", "temperature",
    "forecast", "pluie", "rain", "chaud", "froid", "soleil", "neige",
    "snow", "nuage", "cloud", "vent", "wind", "orage", "thunder",
    "humidité", "humidity", "brouillard", "fog", "ensoleillé", "sunny",
]

_CITY_PATTERNS = [
    r'\bà\s+([A-ZÀ-Ÿa-zà-ÿ][a-zA-Zà-ÿ\-]+(?:\s+[A-ZÀ-Ÿ][a-zA-Zà-ÿ\-]+){0,2})',
    r'\bde\s+([A-ZÀ-Ÿ][a-zA-Zà-ÿ\-]+(?:\s+[A-ZÀ-Ÿ][a-zA-Zà-ÿ\-]+){0,2})',
    r'\bin\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+){0,2})',
    r'\bfor\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+){0,2})',
    r'\bat\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+){0,2})',
]

_CITY_STOPWORDS = {
    "home", "here", "work", "the", "a", "an", "ma", "mon",
    "la", "le", "les", "une", "un", "des", "ce", "cet",
}


def _extract_city_from_question(question: str):
    """
    Returns a city name extracted from a weather voice query, or None.
    Pre-filters on weather keywords before running regex to avoid false positives.
    """
    q_lower = question.lower()
    if not any(kw in q_lower for kw in _WEATHER_KEYWORDS):
        return None
    for pattern in _CITY_PATTERNS:
        match = re.search(pattern, question)
        if match:
            city = match.group(1).strip()
            if city.lower() not in _CITY_STOPWORDS and len(city) >= 2:
                return city
    return None

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

@app.route("/time", methods=["GET"])
def get_server_time():
    # Returns UTC time pre-decomposed — avoids epoch conversion on MicroPython.
    now = datetime.now(timezone.utc)
    return jsonify({
        "utc_epoch": int(time.time()),
        "year":    now.year,
        "month":   now.month,
        "day":     now.day,
        "weekday": now.weekday(),   # 0=Mon … 6=Sun
        "hour":    now.hour,
        "minute":  now.minute,
        "second":  now.second,
    }), 200

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
    Returns current weather + forecast for the requested city.

    ?city=Paris  → fetches Paris weather (Streamlit city picker).
    No param     → uses DEFAULT_CITY (device default, env var).

    BigQuery outdoor insert only happens for DEFAULT_CITY to keep the
    outdoor_weather table consistent with the physical sensor location.
    Stale cache is returned on OWM failure so callers always get data.
    """
    city      = (request.args.get("city") or DEFAULT_CITY).strip()
    cache_key = city.lower()
    now       = time.time()

    slot = _weather_cache.get(cache_key)
    if slot and (now - slot["ts"]) < WEATHER_CACHE_TTL:
        return jsonify(slot["data"]), 200

    try:
        data = get_weather(city)
        if cache_key == DEFAULT_CITY.lower():
            bq.insert_outdoor(data["current"])
        _weather_cache[cache_key] = {"data": data, "ts": now}
        return jsonify(data), 200
    except Exception as e:
        print("[WEATHER] Error for '{}': {}".format(city, e))
        if slot:
            print("[WEATHER] Returning stale cache for '{}'".format(city))
            return jsonify(slot["data"]), 200
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

def _get_llm_history():
    # Fetches the cached BQ history summary for LLM context.
    # Returns None silently on failure so LLM still responds with live data.
    try:
        return bq.get_history_for_llm()
    except Exception as e:
        print("[HISTORY] BQ fetch failed:", e)
        return None

@app.route("/voice/transcribe", methods=["POST"])
def voice_transcribe():
    # STT only — receives base64 WAV, returns {"transcript": "..."}.
    data      = request.get_json()
    audio_b64 = data.get("audio_b64") if data else None
    if not audio_b64:
        return jsonify({"error": "No audio provided"}), 400
    try:
        transcript = speech_to_text(audio_b64)
        print("[STT] Transcript:", transcript)
        return jsonify({"transcript": transcript}), 200
    except Exception as e:
        print("[STT] Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/llm", methods=["POST"])
def llm():
    """
    Text-only LLM endpoint with city-aware weather enrichment and BQ history.

    1. Scans the question for a city name via _extract_city_from_question().
    2. If a foreign city is detected, fetches its weather and prepends it to context.
    3. Fetches the last 3-day BQ history summary and passes it to the LLM.
    """
    data     = request.get_json()
    question = data.get("question") if data else None
    context  = data.get("context")  if data else None
    if not question:
        return jsonify({"error": "No question provided"}), 400

    # ── City enrichment ──────────────────────────────────────
    city_in_question = _extract_city_from_question(question)
    if city_in_question and city_in_question.lower() != DEFAULT_CITY.lower():
        try:
            cur = get_weather(city_in_question).get("current", {})
            city_summary = "Weather in {}: {}, {}C, humidity {}%, wind {} m/s.".format(
                cur.get("city", city_in_question),
                cur.get("condition", "N/A"),
                round(cur.get("temperature", 0), 1),
                cur.get("humidity", "N/A"),
                cur.get("wind_speed", "N/A"),
            )
            context = "{}\n{}".format(city_summary, context or "").strip()
            print("[LLM] City enrichment: {} → {}".format(city_in_question, city_summary))
        except Exception as e:
            print("[LLM] City enrichment failed for '{}': {}".format(city_in_question, e))
            context = "Note: weather for {} unavailable.\n{}".format(
                city_in_question, context or "").strip()
    # ─────────────────────────────────────────────────────────

    try:
        history = _get_llm_history()
        answer  = answer_question(question, context=context, history=history)
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
        history        = _get_llm_history()
        answer_text    = answer_question(question, history=history)
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

@app.route("/voice/respond", methods=["POST"])
def voice_respond():
    """
    LLM + TTS in one call. Receives {question, context}, returns raw WAV.
    Saves one SSL handshake vs calling /llm then /speak-wav separately.
    X-Answer header carries the text answer (newlines stripped for HTTP safety).
    """
    data     = request.get_json()
    question = data.get("question") if data else None
    context  = data.get("context")  if data else None
    if not question:
        return jsonify({"error": "No question provided"}), 400
    try:
        history   = _get_llm_history()
        answer    = answer_question(question, context=context, history=history)
        wav_bytes = text_to_speech_wav(answer)
        safe_a    = ''.join(c if ord(c) < 256 else '?' for c in
                           answer.replace('\r', '').replace('\n', ' '))[:400]
        print("[RESPOND] Q:", question, "| A:", answer[:80])
        return wav_bytes, 200, {
            "Content-Type":   "audio/wav",
            "Content-Length": str(len(wav_bytes)),
            "X-Answer":       safe_a,
        }
    except Exception as e:
        print("[RESPOND] Error:", e)
        return jsonify({"error": str(e)}), 500

# ============================================================
# ALERT LOGGING
# ============================================================

@app.route("/alert/log", methods=["POST"])
def alert_log():
    # Logs a device-triggered alert to BigQuery alerts_log table.
    data       = request.get_json()
    alert_type = data.get("alert_type") if data else None
    message    = data.get("message")    if data else None
    if not alert_type or not message:
        return jsonify({"error": "alert_type and message required"}), 400
    success = bq.insert_alert(alert_type, message)
    return jsonify({"status": "ok" if success else "bq_error"}), 200

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