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

    # ---- Optional Gemini (free tier) suggestions for /api/ai/plan ----
    # AI stays OFF until BOTH a key and a model are set in backend/.env (never commit .env). Without them, or when the
    # student has not ticked the consent box, /api/ai/plan returns the built-in template and nothing leaves the server.
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
    # Seconds to wait for Google. Kept between 3 and 12 so a plan still appears within the 15-second requirement.
    GEMINI_TIMEOUT_SECONDS = _bounded_float(os.getenv("GEMINI_TIMEOUT_SECONDS"), 10.0, 3.0, 12.0)

    # Per signed-in student. Only real Gemini requests count; the built-in template is never limited.
    AI_RATE_PER_MINUTE = 3
    AI_RATE_PER_DAY = 20
