import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _split_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def _bounded_float(value, default, low, high):
    """A number from the environment, kept inside [low, high]. Missing or invalid values use the default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high) if number == number else default  # NaN -> default


class Config:
    BASE_DIR = Path(__file__).resolve().parent

    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")

    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")

    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Browser origins allowed to call the API (comma-separated in .env if you need more).
    CORS_ORIGINS = _split_csv(os.getenv("CORS_ORIGINS", "http://localhost:5500"))

    # "Today" for deadlines is calculated in this timezone. 8 = Philippines (UTC+8, no daylight saving).
    UTC_OFFSET_HOURS = float(os.getenv("TAIM_UTC_OFFSET_HOURS", "8"))

    # Feature gate for the new students/subjects/tasks data layout. OFF by default: the new data routes answer 503
    # until the legacy data has been migrated and verified. Turn on with TAIM_ENABLE_V2=true in backend/.env.
    ENABLE_V2 = os.getenv("TAIM_ENABLE_V2", "false").strip().lower() == "true"

    # Reject request bodies larger than 64 KB (Flask returns 413).
    MAX_CONTENT_LENGTH = 64 * 1024

    # ---- Optional AI providers for /api/ai/plan ----
    # Groq is primary; Gemini is secondary. A single shared timeout covers both attempts.
    # Keys remain in backend/.env and must never be committed.
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_MODEL = os.getenv("GROQ_MODEL", "").strip()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
    AI_TOTAL_TIMEOUT_SECONDS = _bounded_float(os.getenv("AI_TOTAL_TIMEOUT_SECONDS"), 12.0, 3.0, 12.0)
    # Retained for direct Gemini-provider tests and backwards-compatible configuration.
    GEMINI_TIMEOUT_SECONDS = _bounded_float(os.getenv("GEMINI_TIMEOUT_SECONDS"), 10.0, 3.0, 12.0)

    # Per signed-in student. One real planning request counts once, regardless of provider failover.
    AI_RATE_PER_MINUTE = 3
    AI_RATE_PER_DAY = 20

    # Phase 4.2 AI Insights: its own limiter, separate from the planner's. Counts only real provider requests.
    INSIGHTS_RATE_PER_MINUTE = 2
    INSIGHTS_RATE_PER_DAY = 10
