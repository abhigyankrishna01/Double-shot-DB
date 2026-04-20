"""
Async-safe, in-memory TTL cache for query results.
Keyed on a SHA-256 hash of the normalized SQL string.
Prevents redundant LLM + DB round-trips for identical queries within a session.
"""

import asyncio
import hashlib
import time
from typing import Any, Optional


class QueryCache:
    def __init__(self, ttl_seconds: int = 300, max_size: int = 128) -> None:
        self._store: dict[str, tuple[list[dict[str, Any]], float]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(sql: str) -> str:
        normalized = " ".join(sql.strip().lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    async def get(self, sql: str) -> Optional[list[dict[str, Any]]]:
        async with self._lock:
            key = self._key(sql)
            entry = self._store.get(key)
            if entry is None:
                return None
            results, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return results

    async def set(self, sql: str, results: list[dict[str, Any]]) -> None:
        async with self._lock:
            if len(self._store) >= self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
            self._store[self._key(sql)] = (results, time.monotonic())

    async def invalidate(self, sql: str) -> None:
        async with self._lock:
            self._store.pop(self._key(sql), None)


# Module-level singleton — shared across all requests in the process
query_cache = QueryCache()
