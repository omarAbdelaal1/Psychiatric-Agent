"""
Configuration and audio constants for Fadfada Psychiatric Agent.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Server Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8005"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

def _clean_env(val: str, default: str = "") -> str:
    if not val:
        return default
    return val.strip().strip("\"'").strip()

# API Keys (Loaded strictly from environment variables/.env)
GEMINI_API_KEY = _clean_env(os.getenv("GEMINI_API_KEY", ""))

# Candidate API key pool for resilient failover
_env_keys_raw = os.getenv("GEMINI_API_KEYS", "")
if _env_keys_raw:
    GEMINI_API_KEYS = [_clean_env(k) for k in _env_keys_raw.split(",") if _clean_env(k)]
elif GEMINI_API_KEY:
    GEMINI_API_KEYS = [GEMINI_API_KEY]
else:
    GEMINI_API_KEYS = []

# AI Models (Verified active with BidiGenerateContent on Google Gemini Live API)
_raw_model_live = _clean_env(os.getenv("MODEL_LIVE", "gemini-3.8-live"), "gemini-3.8-live")
if _raw_model_live.startswith("models/"):
    _raw_model_live = _raw_model_live[len("models/"):]
MODEL_LIVE = _raw_model_live

_raw_model_flash = _clean_env(os.getenv("MODEL_FLASH", "gemini-3.8-flash"), "gemini-3.8-flash")
if _raw_model_flash.startswith("models/"):
    _raw_model_flash = _raw_model_flash[len("models/"):]
MODEL_FLASH = _raw_model_flash

DEFAULT_VOICE = _clean_env(os.getenv("DEFAULT_VOICE", "Aoede"), "Aoede")

# Gemini Live WebSocket Endpoint
GEMINI_WS_URL = (
    f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
)

# Audio Pipeline Specifications (Adhering to PIPELINE_DOCUMENTATION.md Section 3)
AUDIO_INPUT_SAMPLE_RATE = 16000     # 16kHz PCM mono uplink from client
AUDIO_OUTPUT_SAMPLE_RATE = 24000    # 24kHz PCM mono downlink from model
AUDIO_CHANNELS = 1                  # Mono
AUDIO_SAMPLE_WIDTH = 2              # 16-bit PCM (2 bytes per sample)
AUDIO_CHUNK_SAMPLES = 1600          # 100ms frame at 16kHz
AUDIO_CHUNK_BYTES = AUDIO_CHUNK_SAMPLES * AUDIO_SAMPLE_WIDTH  # 3200 bytes

# VAD and Turn Timing (Studio-grade debounced cadence)
VAD_SILENCE_TIMEOUT_MS = 1600       # 1600ms silence hangtime for natural clinical pauses
VAD_ENERGY_THRESHOLD = 0.018        # RMS energy threshold for speech

# Storage
if os.getenv("VERCEL"):
    DATABASE_PATH = Path("/tmp/fadfada.db")
else:
    DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "fadfada.db")))
