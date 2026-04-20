"""
Global test configuration.
Environment variables MUST be set before any backend module is imported,
so they appear at the top of this file before any local imports.
"""

import os

# Fake credentials — never real keys
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-api-key-00000000000000000000000000")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-02-01")
os.environ.setdefault("POSTGRES_READONLY_USER", "readonly_user")
os.environ.setdefault("POSTGRES_READONLY_PASSWORD", "readonly_pass")
os.environ.setdefault("MAX_RETRIES", "3")
os.environ.setdefault("MAX_STEPS", "4")
os.environ.setdefault("MAX_QUERY_ROWS", "500")
os.environ.setdefault("MAX_QUESTION_LENGTH", "500")
os.environ.setdefault("RATE_LIMIT", "100/minute")  # high limit so tests don't throttle

# Clear lru_cache on settings so the above env vars are picked up
from backend.config import get_settings
get_settings.cache_clear()
