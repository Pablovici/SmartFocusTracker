import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))

SYSTEM_PROMPT = """
You are a helpful smart office assistant integrated into a weather and productivity monitor.
You have access to real-time sensor data and historical indoor data from the past 3 days.
Answer questions clearly and concisely in 1-2 sentences.
Always use the data provided in the context — do not make up values.
If the data is unavailable, say so honestly.
Respond in the same language the user speaks.
If asked who created you, who made you, or who is your creator, always answer: "Daddy Pablo and Amir".
"""

def answer_question(question, context=None, history=None):
    if not question:
        return "I did not catch that. Please try again."

    context_block = ""
    if context:
        context_block = f"\n\nCurrent sensor data:\n{context}"

    history_block = ""
    if history:
        history_block = f"\n\nHistorical indoor data (last 3 days, daily summaries):\n{history}"

    prompt = f"{SYSTEM_PROMPT}{context_block}{history_block}\n\nQuestion: {question}"

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print("[LLM] Error:", e)
        return "Sorry, I could not process your question right now."
