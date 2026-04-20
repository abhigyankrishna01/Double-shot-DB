from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from functools import lru_cache
from backend.config import get_settings


@lru_cache
def get_readonly_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.readonly_dsn,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )


@lru_cache
def get_admin_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.admin_dsn,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
        echo=False,
    )
