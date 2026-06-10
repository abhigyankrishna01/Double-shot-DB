"""
Global test configuration.
Environment variables MUST be set before any backend module is imported,
so they appear at the top of this file before any local imports.
"""

import os

# Fake credentials — never real keys
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key-00000000000000000000")
os.environ.setdefault("GEMINI_MODEL", "gemini-2.5-flash")
os.environ.setdefault("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
os.environ.setdefault(
    "READONLY_DATABASE_URL",
    "postgresql://readonly_user:readonly_pass@localhost:5432/analyst_db",
)
os.environ.setdefault("MAX_RETRIES", "3")
os.environ.setdefault("MAX_STEPS", "4")
os.environ.setdefault("MAX_QUERY_ROWS", "500")
os.environ.setdefault("MAX_QUESTION_LENGTH", "500")
os.environ.setdefault("RATE_LIMIT", "100/minute")  # high limit so tests don't throttle

# Clear lru_cache on settings so the above env vars are picked up
from backend.config import get_settings
get_settings.cache_clear()
