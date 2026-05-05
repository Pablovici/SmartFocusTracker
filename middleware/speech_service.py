# middleware/speech_service.py
# Handles all Text-to-Speech (TTS) and Speech-to-Text (STT) operations.
# Uses Google Cloud Text-to-Speech and Speech-to-Text APIs.
# Credentials are loaded automatically from GOOGLE_APPLICATION_CREDENTIALS.
# Assigned to: Pablo

import os
import base64
from google.cloud import texttospeech, speech

# ============================================================
# CLIENT INITIALIZATION
# ============================================================

# Clients are initialized once at module load.
# Both use the same GCP service account JSON credentials.
tts_client = texttospeech.TextToSpeechClient()
stt_client = speech.SpeechClient()

# ============================================================
# CONFIGURATION
# ============================================================

LANGUAGE    = os.environ.get("SPEECH_LANGUAGE", "en-US")
VOICE_NAME  = os.environ.get("TTS_VOICE", "en-US-Standard-C")

# ============================================================
# TEXT TO SPEECH
# ============================================================

def text_to_speech(text):
    # Converts a text string to speech audio.
    # Returns the audio as a base64-encoded string so it can
    # be sent over HTTP and decoded by the M5Stack device.
    synthesis_input = texttospeech.SynthesisInput(text=text)

    # Voice selection — language and name from environment variables
    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE,
        name=VOICE_NAME,
    )

    # MP3 format — best balance of quality and file size for IoT devices
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    response = tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    # Encode audio bytes to base64 string for JSON transport
    return base64.b64encode(response.audio_content).decode("utf-8")

def text_to_speech_wav(text):
    # Returns raw LINEAR16 WAV bytes at 16kHz.
    # Used by /speak-wav endpoint so the M5Stack can stream directly to flash
    # and play with speaker.playWAV() without any base64 decoding in RAM.
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE,
        name=VOICE_NAME,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        speaking_rate=1.1,
        volume_gain_db=3.0,
    )
    response = tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content

# ============================================================
# SPEECH TO TEXT
# ============================================================

def speech_to_text(audio_b64):
    # Converts base64-encoded audio to a text string.
    # Audio must be recorded at 16000 Hz mono — standard for M5Stack mic.
    # Returns transcribed text, or empty string if recognition fails.
    audio_bytes = base64.b64decode(audio_b64)

    audio = speech.RecognitionAudio(content=audio_bytes)

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,  # M5Stack Core2 microphone sample rate
        language_code=LANGUAGE,
    )

    response = stt_client.recognize(config=config, audio=audio)

    # Return first transcript if available, empty string otherwise
    if response.results:
        return response.results[0].alternatives[0].transcript
    return ""
