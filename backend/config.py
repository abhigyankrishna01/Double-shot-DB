from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str = "gpt-4o-mini"
    azure_openai_api_version: str = "2024-02-01"

    # PostgreSQL admin (schema init only)
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "analyst_db"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # PostgreSQL read-only (sql_executor ONLY)
    postgres_readonly_user: str
    postgres_readonly_password: str

    # App
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    max_retries: int = 3
    max_steps: int = 4           # cap on plan_steps per query
    max_query_rows: int = 500    # auto-injected LIMIT if absent
    max_question_length: int = 500
    rate_limit: str = "15/minute"

    @property
    def admin_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def readonly_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_readonly_user}:{self.postgres_readonly_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
