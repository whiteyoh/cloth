"""Unit tests for rate_limit.py — sliding window per-IP rate limiting."""
from __future__ import annotations

from unittest.mock import patch

import rate_limit


def _reset_stores():
    """Clear module-level state between tests."""
    rate_limit._search_timestamps.clear()
    rate_limit._fresh_timestamps.clear()


class TestCheckSearch:
    def setup_method(self):
        _reset_stores()

    def test_allows_up_to_limit(self):
        for _ in range(rate_limit._SEARCH_MAX_REQUESTS):
            assert rate_limit.check_search("1.2.3.4") is True

    def test_blocks_at_limit(self):
        for _ in range(rate_limit._SEARCH_MAX_REQUESTS):
            rate_limit.check_search("1.2.3.4")
        assert rate_limit.check_search("1.2.3.4") is False

    def test_different_ips_are_independent(self):
        for _ in range(rate_limit._SEARCH_MAX_REQUESTS):
            rate_limit.check_search("1.2.3.4")
        assert rate_limit.check_search("9.9.9.9") is True

    def test_allows_after_window_expires(self):
        base_time = 1000.0
        with patch("rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = base_time
            for _ in range(rate_limit._SEARCH_MAX_REQUESTS):
                rate_limit.check_search("1.2.3.4")
            # Advance time beyond the window
            mock_time.monotonic.return_value = (
                base_time + rate_limit._SEARCH_WINDOW_SECONDS + 1
            )
            assert rate_limit.check_search("1.2.3.4") is True


class TestCheckFresh:
    def setup_method(self):
        _reset_stores()

    def test_allows_up_to_fresh_limit(self):
        for _ in range(rate_limit._FRESH_MAX_REQUESTS):
            assert rate_limit.check_fresh("1.2.3.4") is True

    def test_blocks_at_fresh_limit(self):
        for _ in range(rate_limit._FRESH_MAX_REQUESTS):
            rate_limit.check_fresh("1.2.3.4")
        assert rate_limit.check_fresh("1.2.3.4") is False

    def test_fresh_and_search_limits_are_independent(self):
        for _ in range(rate_limit._FRESH_MAX_REQUESTS):
            rate_limit.check_fresh("1.2.3.4")
        # Regular search limit is separate; should still be allowed
        assert rate_limit.check_search("1.2.3.4") is True

    def test_allows_after_window_expires(self):
        base_time = 1000.0
        with patch("rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = base_time
            for _ in range(rate_limit._FRESH_MAX_REQUESTS):
                rate_limit.check_fresh("1.2.3.4")
            # Advance time beyond the window
            mock_time.monotonic.return_value = (
                base_time + rate_limit._FRESH_WINDOW_SECONDS + 1
            )
            assert rate_limit.check_fresh("1.2.3.4") is True
