"""Unit tests for the async TTL query cache."""

import asyncio
import pytest
from backend.tools.query_cache import QueryCache


@pytest.fixture
def cache() -> QueryCache:
    return QueryCache(ttl_seconds=60, max_size=4)


async def test_miss_on_empty_cache(cache: QueryCache):
    assert await cache.get("SELECT 1") is None


async def test_set_and_get(cache: QueryCache):
    data = [{"id": 1, "name": "Alice"}]
    await cache.set("SELECT 1", data)
    result = await cache.get("SELECT 1")
    assert result == data


async def test_hit_returns_same_reference(cache: QueryCache):
    data = [{"id": 1}]
    await cache.set("SELECT id FROM orders", data)
    assert await cache.get("SELECT id FROM orders") is data


async def test_ttl_expiry():
    cache = QueryCache(ttl_seconds=0)  # expires immediately
    await cache.set("SELECT 1", [{"id": 1}])
    await asyncio.sleep(0.01)
    assert await cache.get("SELECT 1") is None


async def test_normalizes_whitespace(cache: QueryCache):
    data = [{"id": 1}]
    await cache.set("SELECT   id   FROM orders", data)
    # Different whitespace should hit the same cache entry
    result = await cache.get("SELECT id FROM orders")
    assert result == data


async def test_normalizes_case(cache: QueryCache):
    data = [{"id": 1}]
    await cache.set("SELECT ID FROM ORDERS", data)
    result = await cache.get("select id from orders")
    assert result == data


async def test_evicts_oldest_when_full(cache: QueryCache):
    for i in range(4):
        await cache.set(f"SELECT {i}", [{"i": i}])
    # Insert a 5th — should evict one
    await cache.set("SELECT 99", [{"i": 99}])
    assert len(cache._store) == 4


async def test_invalidate(cache: QueryCache):
    await cache.set("SELECT 1", [{"id": 1}])
    await cache.invalidate("SELECT 1")
    assert await cache.get("SELECT 1") is None


async def test_invalidate_nonexistent_is_safe(cache: QueryCache):
    # Should not raise
    await cache.invalidate("SELECT 999")


async def test_concurrent_writes_are_safe(cache: QueryCache):
    async def write(n: int) -> None:
        await cache.set(f"SELECT {n}", [{"n": n}])

    await asyncio.gather(*[write(i) for i in range(20)])
    assert len(cache._store) <= 4  # max_size respected
