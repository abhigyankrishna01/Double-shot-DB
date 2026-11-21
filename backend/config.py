from pydantic_settings import BaseSettings
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class Settings(BaseSettings):
    # Gemini (Google Generative Language API — OpenAI-compatible endpoint)
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Database — full connection URLs (Neon, Render, local Postgres, etc.)
    # READONLY_DATABASE_URL is the only DB env var the runtime requires.
    # ADMIN_DATABASE_URL is optional; falls back to readonly when unset.
    readonly_database_url: str
    admin_database_url: str | None = None

    # App
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    max_retries: int = 3
    max_steps: int = 4           # cap on plan_steps per query
    max_query_rows: int = 500    # auto-injected LIMIT if absent
    query_timeout_ms: int = 5000 # per-query statement_timeout (kills pg_sleep / runaway scans)
    max_question_length: int = 500
    rate_limit: str = "15/minute"

    @staticmethod
    def _normalize_dsn(url: str) -> tuple[str, bool]:
        """
        Normalize a Postgres connection URL for SQLAlchemy + asyncpg.
          - Force the +asyncpg driver scheme.
          - Strip sslmode= (asyncpg rejects it); return ssl_required separately.
        Returns (normalized_url, ssl_required).
        """
        parts = urlsplit(url)
        scheme = parts.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+asyncpg"
        elif scheme == "postgresql+psycopg2":
            scheme = "postgresql+asyncpg"

        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        ssl_required = False
        cleaned_pairs = []
        for k, v in query_pairs:
            if k.lower() == "sslmode":
                if v.lower() in ("require", "verify-ca", "verify-full"):
                    ssl_required = True
                # drop sslmode entirely — asyncpg does not accept it
                continue
            cleaned_pairs.append((k, v))

        return urlunsplit((scheme, parts.netloc, parts.path, urlencode(cleaned_pairs), parts.fragment)), ssl_required

    @property
    def readonly_dsn_and_ssl(self) -> tuple[str, bool]:
        return self._normalize_dsn(self.readonly_database_url)

    @property
    def admin_dsn_and_ssl(self) -> tuple[str, bool]:
        return self._normalize_dsn(self.admin_database_url or self.readonly_database_url)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
