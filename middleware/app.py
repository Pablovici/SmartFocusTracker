# app.py
# Main Flask API serving as the middleware between the M5Stack device
# and BigQuery. All device communication passes through these routes.
# The Streamlit dashboard also calls this API to fetch historical data.

import os
from flask import Flask, request, jsonify
from bigquery_client import (
    insert_sensor_reading,
    fetch_latest_sensor,
    insert_focus_session,
    fetch_sensor_history,
    insert_weather
)

app = Flask(__name__)


# ----------------------------------------------------------
# SENSOR DATA
# ----------------------------------------------------------

@app.route("/data", methods=["POST"])
def receive_data():
    # Receives sensor readings from the M5Stack every 60 seconds.
    # Validates that the payload is JSON before attempting to insert.
    # Returns 400 if the payload is malformed, 500 if the insert fails.
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    success = insert_sensor_reading(payload)
    if success:
        return jsonify({"status": "ok"}), 200
    return jsonify({"error": "Failed to insert into BigQuery"}), 500


@app.route("/latest", methods=["GET"])
def get_latest():
    # Returns the most recent sensor row from BigQuery.
    # Called by the device at boot to restore the last known state,
    # and by the dashboard to display current conditions.
    data = fetch_latest_sensor()
    if data:
        return jsonify(data), 200
    return jsonify({"error": "No data found"}), 404


@app.route("/history", methods=["GET"])
def get_history():
    # Returns sensor readings for the last N hours.
    # The 'hours' query parameter defaults to 24 if not provided.
    # Example: GET /history?hours=48
    hours = request.args.get("hours", 24, type=int)
    data  = fetch_sensor_history(hours=hours)
    return jsonify(data), 200


# ----------------------------------------------------------
# FOCUS SESSIONS
# ----------------------------------------------------------

@app.route("/session", methods=["POST"])
def receive_session():
    # Receives a completed focus session from the device.
    # Called when the user ends a session or the device reboots.
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    success = insert_focus_session(payload)
    if success:
        return jsonify({"status": "ok"}), 200
    return jsonify({"error": "Failed to insert session"}), 500


# ----------------------------------------------------------
# WEATHER
# ----------------------------------------------------------

@app.route("/weather", methods=["GET"])
def get_weather():
    # Fetches current weather and 7-day forecast from OpenWeatherMap,
    # stores a snapshot in BigQuery, and returns the data to the caller.
    # Imported here to keep weather logic isolated in its own module.
    from weather_service import fetch_weather
    data = fetch_weather()
    if not data:
        return jsonify({"error": "Failed to fetch weather data"}), 500

    insert_weather(data)
    return jsonify(data), 200


# ----------------------------------------------------------
# VOICE ASSISTANT
# ----------------------------------------------------------

@app.route("/ask", methods=["POST"])
def ask():
    # Receives a base64-encoded audio clip from the device (Push-to-Talk).
    # Pipeline: audio → STT → LLM (+ BigQuery context) → TTS → response.
    # Returns both the answer text and a base64-encoded audio response.
    payload = request.get_json()
    if not payload or "audio_b64" not in payload:
        return jsonify({"error": "Missing audio_b64 in payload"}), 400

    from speech_service import transcribe_audio, synthesize_speech
    from llm_service import answer_question

    # Step 1 — Transcribe the audio to text
    question = transcribe_audio(payload["audio_b64"])
    if not question:
        return jsonify({"error": "Could not transcribe audio"}), 500

    # Step 2 — Generate an answer using the LLM and BigQuery context
    answer_text = answer_question(question)

    # Step 3 — Convert the answer to speech
    answer_audio = synthesize_speech(answer_text)

    return jsonify({
        "answer_text":      answer_text,
        "answer_audio_b64": answer_audio
    }), 200


# ----------------------------------------------------------
# HEALTH CHECK
# ----------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    # Simple liveness check used by Cloud Run to verify the service
    # is running. Returns 200 as long as the Flask process is alive.
    return jsonify({"status": "healthy"}), 200


# ----------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------

if __name__ == "__main__":
    # PORT is set automatically by Cloud Run at runtime.
    # Locally it defaults to 8080 to match the Cloud Run environment.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
