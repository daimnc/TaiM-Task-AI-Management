import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _split_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


class Config:
    BASE_DIR = Path(__file__).resolve().parent

    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")

    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")

    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Browser origins allowed to call the API (comma-separated in .env if you need more).
    CORS_ORIGINS = _split_csv(os.getenv("CORS_ORIGINS", "http://localhost:5500"))

    # "Today" for deadlines is calculated in this timezone. 8 = Philippines (UTC+8, no daylight saving).
    UTC_OFFSET_HOURS = float(os.getenv("TAIM_UTC_OFFSET_HOURS", "8"))

    # Reject request bodies larger than 64 KB (Flask returns 413).
    MAX_CONTENT_LENGTH = 64 * 1024
