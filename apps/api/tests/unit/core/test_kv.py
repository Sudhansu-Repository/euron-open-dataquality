"""The in-process key value store used when Redis is absent (and by unit tests)."""

from __future__ import annotations

import pytest

from dataquality.core import kv as kv_module
from dataquality.core.kv import MemoryKV, RedisKV, create_kv

pytestmark = pytest.mark.asyncio


async def test_values_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(kv_module.time, "monotonic", lambda: clock[0])
    kv = MemoryKV()
    await kv.set("a", b"1", ttl_s=10)
    assert await kv.get("a") == b"1"
    clock[0] += 11
    assert await kv.get("a") is None
    assert await kv.get("missing") is None


async def test_the_least_recently_used_entry_is_evicted() -> None:
    kv = MemoryKV(max_entries=2)
    await kv.set("a", b"1", 60)
    await kv.set("b", b"2", 60)
    await kv.get("a")  # a is now the most recently used
    await kv.set("c", b"3", 60)
    assert await kv.get("b") is None and await kv.get("a") == b"1" and await kv.get("c") == b"3"


async def test_the_byte_budget_is_kept() -> None:
    kv = MemoryKV(max_entries=100, max_bytes=50)
    await kv.set("big", b"x" * 100, 60)  # larger than the whole budget: not stored
    assert await kv.get("big") is None
    for k in range(10):
        await kv.set(f"k{k}", b"x" * 10, 60)
    assert await kv.get("k9") == b"x" * 10 and await kv.get("k0") is None
    await kv.close()
    assert await kv.get("k9") is None


async def test_counters_increment() -> None:
    kv = MemoryKV()
    assert [await kv.incr("n") for _ in range(3)] == [1, 2, 3]
    await kv.ping()


async def test_rate_limits_refuse_past_the_limit_and_reset_next_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [6000.0]
    monkeypatch.setattr(kv_module.time, "time", lambda: now[0])
    kv = MemoryKV()
    for _ in range(3):
        assert (await kv.hit("ip", 3)).allowed
    refused = await kv.hit("ip", 3)
    assert not refused.allowed and refused.retry_after_s >= 1 and refused.observed == 3
    assert (await kv.hit("other", 3)).allowed  # limits are per key
    now[0] += 60
    assert (await kv.hit("ip", 3)).allowed


async def test_old_windows_are_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [6000.0]
    monkeypatch.setattr(kv_module.time, "time", lambda: now[0])
    kv = MemoryKV()
    for k in range(10_001):
        await kv.hit(f"k{k}", 5)
    now[0] += 60
    await kv.hit("fresh", 5)
    assert len(kv._windows) == 1


async def test_the_backend_follows_the_redis_url() -> None:
    assert isinstance(create_kv(""), MemoryKV)
    assert isinstance(create_kv("redis://localhost:6379/0"), RedisKV)
