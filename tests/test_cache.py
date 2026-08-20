"""Unit tests for cache.py — get/set/eviction/TTL/stats."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import cache


@pytest.fixture(autouse=True)
def reset_cache(tmp_path, monkeypatch):
    """Reset all module-level cache state before every test."""
    monkeypatch.setattr(cache, "_COUNTER_FILE", tmp_path / ".serpapi_counter.json")
    cache._cache.clear()
    cache._hit_count = 0
    cache._miss_count = 0
    cache._serpapi_call_count = 0
    cache._counter_loaded = False
    yield
    cache._cache.clear()
    cache._hit_count = 0
    cache._miss_count = 0
    cache._serpapi_call_count = 0
    cache._counter_loaded = False


class TestNormaliseKey:
    def test_lowercases(self):
        assert cache.normalise_key("Blue Linen Shirt") == "blue linen shirt"

    def test_strips_leading_trailing_whitespace(self):
        assert cache.normalise_key("  blue linen shirt  ") == "blue linen shirt"

    def test_collapses_internal_whitespace(self):
        assert cache.normalise_key("blue  linen   shirt") == "blue linen shirt"

    def test_combined(self):
        assert cache.normalise_key("  Blue  LINEN  Shirt  ") == "blue linen shirt"

    def test_empty_string(self):
        assert cache.normalise_key("") == ""


class TestGetAndSet:
    def test_get_missing_key_returns_none(self):
        result = cache.get("nonexistent_key")
        assert result is None

    def test_set_then_get_returns_same_list(self):
        products = [{"id": "1", "name": "Blue Shirt"}]
        cache.set("blue shirt", products)
        result = cache.get("blue shirt")
        assert result == products

    def test_get_increments_hit_count(self):
        cache.set("key", [])
        cache.get("key")
        assert cache._hit_count == 1

    def test_miss_increments_miss_count(self):
        cache.get("nonexistent")
        assert cache._miss_count == 1

    def test_overwrite_existing_key(self):
        cache.set("key", [{"name": "old"}])
        cache.set("key", [{"name": "new"}])
        result = cache.get("key")
        assert result == [{"name": "new"}]


class TestTtlExpiry:
    def test_expired_entry_returns_none(self, monkeypatch):
        """An entry past its TTL is evicted and get() returns None."""
        cache.set("expiring_key", [{"name": "item"}])

        future = datetime.now(timezone.utc) + timedelta(minutes=31)
        monkeypatch.setattr(cache, "_now", lambda: future)

        result = cache.get("expiring_key")
        assert result is None

    def test_expired_entry_is_removed_from_cache(self, monkeypatch):
        cache.set("expiring_key", [{"name": "item"}])

        future = datetime.now(timezone.utc) + timedelta(minutes=31)
        monkeypatch.setattr(cache, "_now", lambda: future)

        cache.get("expiring_key")
        assert "expiring_key" not in cache._cache

    def test_unexpired_entry_still_accessible(self, monkeypatch):
        cache.set("live_key", [{"name": "item"}])

        near_future = datetime.now(timezone.utc) + timedelta(minutes=29)
        monkeypatch.setattr(cache, "_now", lambda: near_future)

        result = cache.get("live_key")
        assert result is not None


class TestLruEviction:
    def test_oldest_entry_evicted_when_at_capacity(self):
        """When the cache reaches _MAX_SIZE, adding a new entry evicts the LRU entry."""
        original_max = cache._MAX_SIZE
        cache._MAX_SIZE = 3

        try:
            cache.set("a", [1])
            cache.set("b", [2])
            cache.set("c", [3])
            # Access 'a' to move it to MRU position.
            cache.get("a")
            # Add a fourth entry; 'b' is now LRU and should be evicted.
            cache.set("d", [4])

            assert cache.get("b") is None
            assert cache.get("a") is not None
            assert cache.get("c") is not None
            assert cache.get("d") is not None
        finally:
            cache._MAX_SIZE = original_max

    def test_cache_does_not_exceed_max_size(self):
        original_max = cache._MAX_SIZE
        cache._MAX_SIZE = 5

        try:
            for i in range(10):
                cache.set(f"key{i}", [i])
            assert len(cache._cache) <= 5
        finally:
            cache._MAX_SIZE = original_max


class TestInvalidate:
    def test_invalidate_removes_key(self):
        cache.set("target", [{"name": "item"}])
        cache.invalidate("target")
        assert cache.get("target") is None

    def test_invalidate_nonexistent_key_does_not_raise(self):
        cache.invalidate("does_not_exist")  # should not raise


class TestStats:
    def test_stats_structure(self):
        result = cache.stats()
        assert "cache_size" in result
        assert "hit_count" in result
        assert "miss_count" in result
        assert "max_size" in result
        assert "ttl_minutes" in result
        assert "serpapi_call_count" in result

    def test_stats_reflects_cache_size(self):
        cache.set("a", [])
        cache.set("b", [])
        stats = cache.stats()
        assert stats["cache_size"] == 2

    def test_stats_reflects_hit_and_miss_counts(self):
        cache.set("key", [])
        cache.get("key")        # hit
        cache.get("missing")    # miss
        stats = cache.stats()
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1

    def test_stats_ttl_and_max_size_values(self):
        stats = cache.stats()
        assert stats["ttl_minutes"] == 30
        assert stats["max_size"] == 500


class TestIncrementSearchCallCount:
    def test_increment_returns_new_count(self):
        assert cache.increment_search_call_count() == 1
        assert cache.increment_search_call_count() == 2

    def test_count_reflected_in_stats(self):
        cache.increment_search_call_count()
        cache.increment_search_call_count()
        assert cache.stats()["serpapi_call_count"] == 2
