"""Tests for the virtual try-on endpoint (POST /try-on) and check_try_on() rate limiter.

Fashn.ai API calls are mocked — no real external calls are made.
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import rate_limit

# ------------------------------------------------------------------ #
# Shared fixtures                                                       #
# ------------------------------------------------------------------ #


@pytest.fixture()
def client(monkeypatch):
    """TestClient with SERPAPI_KEY set so lifespan passes; rate stores cleared."""
    monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
    rate_limit._search_timestamps.clear()
    rate_limit._fresh_timestamps.clear()
    rate_limit._try_on_timestamps.clear()
    import main

    with TestClient(main.app) as c:
        yield c
    rate_limit._search_timestamps.clear()
    rate_limit._fresh_timestamps.clear()
    rate_limit._try_on_timestamps.clear()


def _jpeg_bytes(size: int = 512) -> bytes:
    """Return a minimal valid JPEG payload (magic bytes only, padded to size)."""
    return b"\xff\xd8\xff" + b"\x00" * (size - 3)


def _png_bytes(size: int = 512) -> bytes:
    """Return a minimal valid PNG payload (magic bytes only, padded to size)."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * (size - 8)


# ------------------------------------------------------------------ #
# POST /try-on — FASHN_API_KEY absent                                  #
# ------------------------------------------------------------------ #


class TestTryOnKeyAbsent:
    def test_returns_status_unavailable_when_no_api_key(self, client, monkeypatch):
        """When FASHN_API_KEY is not set, return 200 with {"status": "unavailable"}."""
        monkeypatch.delenv("FASHN_API_KEY", raising=False)
        r = client.post(
            "/try-on",
            data={"garment_url": "http://example.com/garment.jpg"},
        )
        assert r.status_code == 200
        assert r.json() == {"status": "unavailable"}


# ------------------------------------------------------------------ #
# POST /try-on — input validation (FASHN_API_KEY present)             #
# ------------------------------------------------------------------ #


class TestTryOnValidation:
    @pytest.fixture(autouse=True)
    def _set_api_key(self, monkeypatch):
        monkeypatch.setenv("FASHN_API_KEY", "test-fashn-key")

    def test_missing_file_returns_400(self, client):
        """Request without a person_image file returns HTTP 400."""
        r = client.post(
            "/try-on",
            data={"garment_url": "http://example.com/garment.jpg"},
        )
        assert r.status_code == 400
        assert "error" in r.json()

    def test_invalid_mime_type_returns_400(self, client):
        """File with non-image MIME type returns HTTP 400."""
        r = client.post(
            "/try-on",
            files={"person_image": ("photo.txt", io.BytesIO(b"not an image"), "text/plain")},
            data={"garment_url": "http://example.com/garment.jpg"},
        )
        assert r.status_code == 400
        assert "error" in r.json()

    def test_invalid_magic_bytes_returns_400(self, client):
        """File with JPEG MIME type but wrong magic bytes returns HTTP 400."""
        r = client.post(
            "/try-on",
            files={
                "person_image": (
                    "photo.jpg",
                    io.BytesIO(b"GIF89a this is not a jpeg"),
                    "image/jpeg",
                )
            },
            data={"garment_url": "http://example.com/garment.jpg"},
        )
        assert r.status_code == 400
        assert "error" in r.json()

    def test_file_too_large_returns_400(self, client):
        """File larger than 5 MB returns HTTP 400."""
        large_content = _jpeg_bytes(size=5 * 1024 * 1024 + 1)
        r = client.post(
            "/try-on",
            files={
                "person_image": ("photo.jpg", io.BytesIO(large_content), "image/jpeg")
            },
            data={"garment_url": "http://example.com/garment.jpg"},
        )
        assert r.status_code == 400
        body = r.json()
        assert "error" in body
        assert "5" in body["error"]  # mentions 5 MB in the message


# ------------------------------------------------------------------ #
# POST /try-on — rate limiting                                         #
# ------------------------------------------------------------------ #


class TestTryOnRateLimit:
    @pytest.fixture(autouse=True)
    def _set_api_key(self, monkeypatch):
        monkeypatch.setenv("FASHN_API_KEY", "test-fashn-key")
        rate_limit._try_on_timestamps.clear()

    def test_rate_limit_exceeded_returns_429(self, client, monkeypatch):
        """When check_try_on returns False, the endpoint returns HTTP 429."""
        monkeypatch.setattr(rate_limit, "check_try_on", lambda ip: False)

        with patch("main._call_fashn_ai", new=AsyncMock(return_value="https://result.example.com/out.jpg")):
            r = client.post(
                "/try-on",
                files={"person_image": ("photo.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
                data={"garment_url": "http://example.com/garment.jpg"},
            )

        assert r.status_code == 429
        assert "error" in r.json()

    def test_successful_try_on_returns_result_url(self, client):
        """With valid input and mocked Fashn.ai, returns {"result_url": ...}."""
        with patch(
            "main._call_fashn_ai",
            new=AsyncMock(return_value="https://result.example.com/output.jpg"),
        ):
            r = client.post(
                "/try-on",
                files={"person_image": ("photo.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
                data={"garment_url": "http://example.com/garment.jpg"},
            )
        assert r.status_code == 200
        assert r.json() == {"result_url": "https://result.example.com/output.jpg"}

    def test_fashn_api_error_returns_error_json(self, client):
        """When Fashn.ai raises an exception, returns {"error": ...} not 500."""
        with patch(
            "main._call_fashn_ai",
            new=AsyncMock(side_effect=RuntimeError("Fashn.ai service unavailable")),
        ):
            r = client.post(
                "/try-on",
                files={"person_image": ("photo.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
                data={"garment_url": "http://example.com/garment.jpg"},
            )
        assert r.status_code == 200
        assert "error" in r.json()

    def test_png_file_accepted(self, client):
        """PNG files with correct magic bytes are accepted."""
        with patch(
            "main._call_fashn_ai",
            new=AsyncMock(return_value="https://result.example.com/output.jpg"),
        ):
            r = client.post(
                "/try-on",
                files={"person_image": ("photo.png", io.BytesIO(_png_bytes()), "image/png")},
                data={"garment_url": "http://example.com/garment.jpg"},
            )
        assert r.status_code == 200
        assert "result_url" in r.json()


# ------------------------------------------------------------------ #
# check_try_on() — rate limiter unit tests                            #
# ------------------------------------------------------------------ #


class TestCheckTryOn:
    def setup_method(self):
        rate_limit._try_on_timestamps.clear()

    def test_allows_up_to_limit(self):
        for _ in range(rate_limit._TRY_ON_MAX_REQUESTS):
            assert rate_limit.check_try_on("10.0.0.1") is True

    def test_blocks_at_limit(self):
        for _ in range(rate_limit._TRY_ON_MAX_REQUESTS):
            rate_limit.check_try_on("10.0.0.1")
        assert rate_limit.check_try_on("10.0.0.1") is False

    def test_different_ips_are_independent(self):
        for _ in range(rate_limit._TRY_ON_MAX_REQUESTS):
            rate_limit.check_try_on("10.0.0.1")
        assert rate_limit.check_try_on("10.0.0.2") is True

    def test_allows_after_window_expires(self):
        from unittest.mock import patch

        base_time = 1000.0
        with patch("rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = base_time
            for _ in range(rate_limit._TRY_ON_MAX_REQUESTS):
                rate_limit.check_try_on("10.0.0.1")
            # Advance beyond the 24-hour window
            mock_time.monotonic.return_value = (
                base_time + rate_limit._TRY_ON_WINDOW_SECONDS + 1
            )
            assert rate_limit.check_try_on("10.0.0.1") is True

    def test_window_is_24_hours(self):
        assert rate_limit._TRY_ON_WINDOW_SECONDS == 86400

    def test_limit_is_three(self):
        assert rate_limit._TRY_ON_MAX_REQUESTS == 3
