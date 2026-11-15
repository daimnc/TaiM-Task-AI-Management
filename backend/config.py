import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


class Config:
    BASE_DIR = Path(__file__).resolve().parent

    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")

    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")

    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"