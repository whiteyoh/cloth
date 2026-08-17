"""Shared pytest fixtures for the Cloth test suite."""
from __future__ import annotations

import pytest

import cache
import search


@pytest.fixture(autouse=True)
def _reset_cache(tmp_path, monkeypatch):
    """Reset the in-memory cache, counters, and http client singleton between tests."""
    monkeypatch.setattr(cache, "_COUNTER_FILE", tmp_path / ".serpapi_counter.json")
    cache._cache.clear()
    cache._hit_count = 0
    cache._miss_count = 0
    cache._serpapi_call_count = 0
    cache._counter_loaded = False
    search._http_client = None
    yield
    cache._cache.clear()
    cache._hit_count = 0
    cache._miss_count = 0
    cache._serpapi_call_count = 0
    cache._counter_loaded = False
    search._http_client = None
