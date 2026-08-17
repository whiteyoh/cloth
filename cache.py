"""In-memory LRU+TTL cache for SerpAPI search results.

Implemented as a module-level OrderedDict singleton (ADR-007).
The SerpAPI monthly call counter is persisted to .serpapi_counter.json
so it survives process restarts (WN-029).
"""
from __future__ import annotations

import json
import pathlib
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

_MAX_SIZE = 500
_TTL_MINUTES = 30

_cache: OrderedDict[str, tuple[list, datetime]] = OrderedDict()
_hit_count: int = 0
_miss_count: int = 0
_serpapi_call_count: int = 0

_COUNTER_FILE = pathlib.Path(__file__).parent / ".serpapi_counter.json"
_counter_loaded: bool = False


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load_counter() -> None:
    """Load the persisted call count from disk; reset if month has changed."""
    global _serpapi_call_count, _counter_loaded
    if _counter_loaded:
        return
    _counter_loaded = True
    try:
        data = json.loads(_COUNTER_FILE.read_text())
        if data.get("month") == _current_month():
            _serpapi_call_count = int(data.get("count", 0))
        else:
            _serpapi_call_count = 0
    except (OSError, ValueError, KeyError):
        _serpapi_call_count = 0


def _persist_counter() -> None:
    """Write the current call count to disk."""
    try:
        _COUNTER_FILE.write_text(
            json.dumps({"month": _current_month(), "count": _serpapi_call_count})
        )
    except OSError:
        pass


def _now() -> datetime:
    """Return current UTC time. Extracted so tests can monkeypatch it."""
    return datetime.now(timezone.utc)


def normalise_key(query: str) -> str:
    """Lowercase, strip, and collapse internal whitespace."""
    return " ".join(query.lower().strip().split())


def get(key: str) -> list | None:
    """Return cached products for *key*, or None on miss or expiry.

    A hit moves the entry to the most-recently-used position.
    Expired entries are evicted lazily on access.
    """
    global _hit_count, _miss_count

    entry = _cache.get(key)
    if entry is None:
        _miss_count += 1
        return None

    products, expiry = entry
    if _now() >= expiry:
        del _cache[key]
        _miss_count += 1
        return None

    _cache.move_to_end(key)
    _hit_count += 1
    return products


def set(key: str, products: list) -> None:  # noqa: A001
    """Store *products* under *key* with a fresh TTL.

    Evicts the LRU entry when the cache is at capacity.
    If the key already exists it is overwritten and moved to MRU.
    """
    if key in _cache:
        _cache.move_to_end(key)
    elif len(_cache) >= _MAX_SIZE:
        _cache.popitem(last=False)

    expiry = _now() + timedelta(minutes=_TTL_MINUTES)
    _cache[key] = (products, expiry)


def invalidate(key: str) -> None:
    """Remove *key* from the cache (used for ?fresh=true bypass)."""
    _cache.pop(key, None)


def increment_serpapi_call_count() -> int:
    """Increment the SerpAPI call counter, persist to disk, and return the new value."""
    global _serpapi_call_count
    _load_counter()
    _serpapi_call_count += 1
    _persist_counter()
    return _serpapi_call_count


def stats() -> dict:
    """Return cache diagnostics for the /health endpoint."""
    return {
        "cache_size": len(_cache),
        "hit_count": _hit_count,
        "miss_count": _miss_count,
        "max_size": _MAX_SIZE,
        "ttl_minutes": _TTL_MINUTES,
        "serpapi_call_count": _serpapi_call_count,
    }
