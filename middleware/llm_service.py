# middleware/llm_service.py
# Handles LLM question answering using Google Gemini.
# Uses the project's own API key — billed to smart-focus-tracker.
# Assigned to: Pablo

import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"))

SYSTEM_PROMPT = """You are a helpful smart office assistant integrated into a weather and productivity monitor.
You have access to real-time sensor data about the room and the user's work session.
Answer questions clearly and concisely in 1-2 sentences.
Always use the data provided in the context — do not make up values.
If the data is unavailable, say so honestly.
Respond in the same language the user speaks."""

def answer_question(question, context=None):
    if not question:
        return "I did not catch that. Please try again."
    context_block = ""
    if context:
        context_block = "\n\nCurrent sensor data:\n{}".format(context)
    prompt = "{}{}\n\nQuestion: {}".format(SYSTEM_PROMPT, context_block, question)
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print("[LLM] Error:", e)
        return "Sorry, I could not process your question right now."
