# middleware/llm_service.py
# Handles LLM question answering using Google Gemini.
# Builds a context from recent BigQuery data before calling the LLM,
# so the model can answer questions about current and historical data.
# Assigned to: Pablo

import os
import google.generativeai as genai
import bigquery_client as bq

# ============================================================
# CLIENT INITIALIZATION
# ============================================================

# Configure Gemini with API key from environment variables
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"))

# ============================================================
# CONTEXT BUILDER
# ============================================================

def _build_context():
    # Fetches recent data from BigQuery to inject into the LLM prompt.
    # Keeps context minimal — only last 5 readings per table — to avoid
    # exceeding token limits and to keep response times fast.
    context_parts = []

    # Latest indoor reading
    latest = bq.get_latest_indoor()
    if latest:
        context_parts.append(
            "Current indoor conditions: "
            "temperature={temp}°C, humidity={hum}%, "
            "CO2={co2}ppm, air quality={aq}.".format(
                temp=latest.get("temperature"),
                hum=latest.get("humidity"),
                co2=latest.get("co2_ppm"),
                aq=latest.get("air_quality_label"),
            )
        )

    # Indoor history — last 24 hours
    history = bq.get_indoor_history(days=1)
    if history:
        context_parts.append(
            "Indoor history (last 24h): {} readings available. "
            "First reading: temp={}°C, humidity={}%. "
            "Last reading: temp={}°C, humidity={}%.".format(
                len(history),
                history[0].get("temperature"),
                history[0].get("humidity"),
                history[-1].get("temperature"),
                history[-1].get("humidity"),
            )
        )

    # Current session
    session = bq.get_current_session()
    if session:
        pauses = session.get("pauses", "[]")
        context_parts.append(
            "Current work session: started at {}, "
            "session ID={}, pauses={}.".format(
                session.get("start_time"),
                session.get("session_id"),
                pauses,
            )
        )
    else:
        context_parts.append("No active work session.")

    # Session history — last 5 sessions
    sessions = bq.get_session_history(limit=5)
    if sessions:
        context_parts.append(
            "Recent sessions: {} completed. "
            "Last session work time: {} minutes.".format(
                len(sessions),
                sessions[0].get("total_work_minutes"),
            )
        )

    # Session stats
    stats = bq.get_session_stats()
    if stats:
        context_parts.append(
            "Session statistics: {} total sessions, "
            "average work time={} minutes, "
            "longest session={} minutes.".format(
                stats.get("total_sessions"),
                round(stats.get("avg_work_minutes") or 0, 1),
                round(stats.get("longest_session_minutes") or 0, 1),
            )
        )

    return "\n".join(context_parts)

# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are a helpful smart home assistant integrated into a weather and productivity monitor.
You have access to real-time and historical data about:
- Indoor temperature, humidity, and air quality
- Outdoor weather conditions
- Work session tracking via RFID badge

Answer questions clearly and concisely in 1-2 sentences.
Always use the data provided in the context — do not make up values.
If the data is unavailable, say so honestly.
Respond in the same language the user speaks.
"""

# ============================================================
# MAIN FUNCTION
# ============================================================

def answer_question(question):
    # Builds context from BigQuery, then sends question + context to Gemini.
    # Returns a natural language answer string.
    # Falls back to a generic error message if the LLM call fails.
    if not question:
        return "I did not catch that. Please try again."

    context = _build_context()

    prompt = "{}\n\nContext:\n{}\n\nQuestion: {}".format(
        SYSTEM_PROMPT, context, question
    )

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print("[LLM] Error:", e)
        return "Sorry, I could not process your question right now."
