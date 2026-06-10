from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from functools import lru_cache
from backend.config import get_settings


def _connect_args(ssl_required: bool) -> dict:
    # asyncpg uses connect_args["ssl"]=True for managed Postgres (Neon, Render, etc.)
    return {"ssl": True} if ssl_required else {}


@lru_cache
def get_readonly_engine() -> AsyncEngine:
    settings = get_settings()
    dsn, ssl_required = settings.readonly_dsn_and_ssl
    return create_async_engine(
        dsn,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
        connect_args=_connect_args(ssl_required),
    )


@lru_cache
def get_admin_engine() -> AsyncEngine:
    settings = get_settings()
    dsn, ssl_required = settings.admin_dsn_and_ssl
    return create_async_engine(
        dsn,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
        echo=False,
        connect_args=_connect_args(ssl_required),
    )
