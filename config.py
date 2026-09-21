import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

def database_url():
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://kareem:kareem@127.0.0.1:5432/kareem",
    )

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-in-production")
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = __import__("datetime").timedelta(days=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PWA_NAME = "سوق الجملة"
    PWA_SHORT_NAME = "سوق الجملة"
    DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "ريال يمني")
