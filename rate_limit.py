"""Simple in-process per-IP rate limiter using a sliding window."""
from __future__ import annotations

import time
from collections import defaultdict

# Maximum requests per window per IP for the search endpoint
_SEARCH_MAX_REQUESTS = 10
_SEARCH_WINDOW_SECONDS = 60

# Stricter limit for ?fresh=true
_FRESH_MAX_REQUESTS = 3
_FRESH_WINDOW_SECONDS = 60

# Per-IP limit for virtual try-on (cost control)
_TRY_ON_MAX_REQUESTS = 3
_TRY_ON_WINDOW_SECONDS = 86400  # 24 hours

_search_timestamps: dict[str, list[float]] = defaultdict(list)
_fresh_timestamps: dict[str, list[float]] = defaultdict(list)
_try_on_timestamps: dict[str, list[float]] = defaultdict(list)


def _sliding_window_check(
    store: dict, ip: str, max_requests: int, window_seconds: int
) -> bool:
    """Return True if the request is ALLOWED; False if rate limited.

    Prunes old timestamps and checks count against limit.
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    timestamps = store[ip]
    store[ip] = [t for t in timestamps if t > cutoff]
    if len(store[ip]) >= max_requests:
        return False
    store[ip].append(now)
    return True


def check_search(ip: str) -> bool:
    """Check rate limit for a regular search request. Returns True if allowed."""
    return _sliding_window_check(
        _search_timestamps, ip, _SEARCH_MAX_REQUESTS, _SEARCH_WINDOW_SECONDS
    )


def check_fresh(ip: str) -> bool:
    """Check rate limit for a fresh=True request. Returns True if allowed."""
    return _sliding_window_check(
        _fresh_timestamps, ip, _FRESH_MAX_REQUESTS, _FRESH_WINDOW_SECONDS
    )


def check_try_on(ip: str) -> bool:
    """Check rate limit for a virtual try-on request. Returns True if allowed.

    Limit is 3 try-on calls per 24-hour rolling window per IP.
    """
    return _sliding_window_check(
        _try_on_timestamps, ip, _TRY_ON_MAX_REQUESTS, _TRY_ON_WINDOW_SECONDS
    )
