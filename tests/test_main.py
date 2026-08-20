"""HTTP-level tests for main.py route handlers.

Uses FastAPI TestClient with a mocked SERPAPI_KEY so lifespan validation passes
without making real SerpAPI calls. search_products is mocked throughout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from models import Product


@pytest.fixture()
def client(monkeypatch):
    """TestClient with SERPAPI_KEY set and rate limiter reset."""
    monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
    import rate_limit

    rate_limit._search_timestamps.clear()
    rate_limit._fresh_timestamps.clear()
    import main

    with TestClient(main.app) as c:
        yield c
    rate_limit._search_timestamps.clear()
    rate_limit._fresh_timestamps.clear()


def _make_product(name: str = "Blue Shirt") -> Product:
    return Product(
        id="abc123",
        name=name,
        image_url="https://img.example.com/shirt.jpg",
        price_value=34.99,
        price_currency="GBP",
        price_display="£34.99",
        retailer_name="ASOS",
        purchase_url="https://www.asos.com/product/12345",
        source_api="serpapi_google_shopping",
        retrieved_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


# ------------------------------------------------------------------ #
# GET /                                                                #
# ------------------------------------------------------------------ #


class TestHome:
    def test_returns_200(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_contains_search_form(self, client):
        r = client.get("/")
        assert "<form" in r.text


# ------------------------------------------------------------------ #
# GET /search — input validation                                       #
# ------------------------------------------------------------------ #


class TestGetSearchValidation:
    def test_empty_query_renders_index_with_error(self, client):
        r = client.get("/search?q=")
        assert r.status_code == 200
        assert "Please enter a search term" in r.text

    def test_whitespace_only_query_renders_index_with_error(self, client):
        r = client.get("/search?q=+++")
        assert r.status_code == 200
        assert "Please enter a search term" in r.text

    def test_overlong_query_renders_index_with_error(self, client):
        long_q = "a" * 501
        r = client.get(f"/search?q={long_q}")
        assert r.status_code == 200
        assert "too long" in r.text.lower()

    def test_exactly_500_chars_does_not_trigger_length_error(self, client):
        q = "a" * 500
        with patch("main.search_products", new=AsyncMock(return_value=[])):
            r = client.get(f"/search?q={q}")
        assert "too long" not in r.text.lower()


# ------------------------------------------------------------------ #
# GET /search — happy path                                            #
# ------------------------------------------------------------------ #


class TestGetSearchHappyPath:
    def test_results_rendered_when_products_returned(self, client):
        products = [_make_product("Blue Shirt"), _make_product("White Tee")]
        with patch("main.search_products", new=AsyncMock(return_value=products)):
            r = client.get("/search?q=blue+shirt")
        assert r.status_code == 200
        assert "Blue Shirt" in r.text

    def test_empty_results_renders_results_page_not_error(self, client):
        with patch("main.search_products", new=AsyncMock(return_value=[])):
            r = client.get("/search?q=blue+shirt")
        assert r.status_code == 200
        assert "blue shirt" in r.text.lower()

    def test_result_count_shown_in_response(self, client):
        products = [_make_product(f"Item {i}") for i in range(3)]
        with patch("main.search_products", new=AsyncMock(return_value=products)):
            r = client.get("/search?q=shirt")
        assert r.status_code == 200
        assert "3" in r.text


# ------------------------------------------------------------------ #
# GET /search — error handling                                         #
# ------------------------------------------------------------------ #


class TestGetSearchErrorHandling:
    @pytest.mark.parametrize(
        "error_type,expected_fragment",
        [
            ("serpapi_timeout", "too long"),
            ("serpapi_rate_limit", "many searches"),
            ("serpapi_auth_error", "temporarily unavailable"),
            ("serpapi_schema_error", "unexpected response"),
            ("serpapi_budget_exhausted", "temporarily unavailable"),
            ("unknown", "reach the search service"),
        ],
    )
    def test_search_error_renders_friendly_message(
        self, client, error_type, expected_fragment
    ):
        from search import SearchError

        with patch(
            "main.search_products",
            new=AsyncMock(side_effect=SearchError("fail", error_type=error_type)),
        ):
            r = client.get("/search?q=test")
        assert r.status_code == 200
        assert expected_fragment.lower() in r.text.lower()


# ------------------------------------------------------------------ #
# POST /search                                                         #
# ------------------------------------------------------------------ #


class TestPostSearch:
    def test_redirects_to_get_search(self, client):
        r = client.post("/search", data={"q": "navy chinos"}, follow_redirects=False)
        assert r.status_code == 303
        assert "/search?q=" in r.headers["location"]

    def test_empty_post_redirects(self, client):
        r = client.post("/search", data={"q": ""}, follow_redirects=False)
        assert r.status_code == 303


# ------------------------------------------------------------------ #
# GET /health                                                          #
# ------------------------------------------------------------------ #


class TestHealth:
    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_response_contains_status_ok(self, client):
        r = client.get("/health")
        data = r.json()
        assert data["status"] == "ok"

    def test_response_contains_cache_stats(self, client):
        r = client.get("/health")
        data = r.json()
        assert "cache" in data

    def test_serpapi_key_configured_true_when_key_set(self, client):
        r = client.get("/health")
        data = r.json()
        assert data["search_api_key_configured"] is True


# ------------------------------------------------------------------ #
# GET /saved                                                           #
# ------------------------------------------------------------------ #


class TestSaved:
    def test_returns_200(self, client):
        r = client.get("/saved")
        assert r.status_code == 200


# ------------------------------------------------------------------ #
# GET /privacy                                                         #
# ------------------------------------------------------------------ #


class TestPrivacy:
    def test_returns_200(self, client):
        r = client.get("/privacy")
        assert r.status_code == 200

    def test_contains_privacy_content(self, client):
        r = client.get("/privacy")
        assert "privacy" in r.text.lower()


# ------------------------------------------------------------------ #
# GET /search?format=json — ajax endpoint (WN-066)                     #
# ------------------------------------------------------------------ #


class TestGetSearchJsonFormat:
    def test_returns_json_content_type(self, client):
        with patch("main.search_products", new=AsyncMock(return_value=[])):
            r = client.get("/search?q=shirt&format=json")
        assert "application/json" in r.headers["content-type"]

    def test_empty_results_returns_json(self, client):
        with patch("main.search_products", new=AsyncMock(return_value=[])):
            r = client.get("/search?q=shirt&format=json")
        data = r.json()
        assert data["query"] == "shirt"
        assert data["products"] == []
        assert data["result_count"] == 0
        assert data["error_message"] is None

    def test_results_returned_as_json(self, client):
        products = [_make_product("Blue Shirt")]
        with patch("main.search_products", new=AsyncMock(return_value=products)):
            r = client.get("/search?q=shirt&format=json")
        data = r.json()
        assert data["result_count"] == 1
        assert data["products"][0]["name"] == "Blue Shirt"

    def test_empty_query_returns_json_error(self, client):
        r = client.get("/search?q=&format=json")
        data = r.json()
        assert data["error_message"] is not None

    def test_search_error_returns_json_error(self, client):
        from search import SearchError

        with patch("main.search_products", new=AsyncMock(side_effect=SearchError("fail", error_type="serpapi_timeout"))):
            r = client.get("/search?q=shirt&format=json")
        data = r.json()
        assert data["error_message"] is not None
        assert "too long" in data["error_message"].lower()


# ------------------------------------------------------------------ #
# Security headers                                                      #
# ------------------------------------------------------------------ #


class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        r = client.get("/")
        assert "content-security-policy" in r.headers

    def test_x_content_type_options_header(self, client):
        r = client.get("/")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_header(self, client):
        r = client.get("/")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_csp_header_includes_frame_ancestors(self, client):
        r = client.get("/")
        csp = r.headers.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp

    def test_csp_img_src_tightened_to_known_domains(self, client):
        r = client.get("/")
        csp = r.headers.get("content-security-policy", "")
        assert "img-src *" not in csp
        assert "https://*.google.com" in csp
        assert "https://*.gstatic.com" in csp
        assert "https://*.googleusercontent.com" in csp


# ------------------------------------------------------------------ #
# Rate-limit structured event emission (WN-074)                        #
# ------------------------------------------------------------------ #


class TestRateLimitEvents:
    def test_search_rate_limit_emits_structured_event(self, monkeypatch, capsys):
        import json as _json

        import rate_limit

        monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
        rate_limit._search_timestamps.clear()
        rate_limit._fresh_timestamps.clear()

        import main

        with TestClient(main.app) as c:
            # Exhaust the search rate limit (10 searches per 60s)
            for _ in range(10):
                with patch("main.search_products", new=AsyncMock(return_value=[])):
                    c.get("/search?q=shirt")
            # This request should be rejected and emit the event
            capsys.readouterr()  # clear accumulated output
            c.get("/search?q=shirt")

        captured = capsys.readouterr()
        events = [_json.loads(line) for line in captured.out.strip().splitlines() if line]
        rl_events = [e for e in events if e.get("event") == "rate_limit_rejected"]
        assert rl_events, "Expected rate_limit_rejected event"
        event = rl_events[0]
        assert event["limit_type"] == "search"
        assert "ip" in event
        assert "timestamp_utc" in event


# ------------------------------------------------------------------ #
# GET /outfits (WN-099)                                                #
# ------------------------------------------------------------------ #


class TestOutfitsPage:
    def test_returns_200(self, client):
        r = client.get("/outfits")
        assert r.status_code == 200

    def test_contains_heading(self, client):
        r = client.get("/outfits")
        assert "Outfit boards" in r.text

    def test_contains_new_outfit_button(self, client):
        r = client.get("/outfits")
        assert "new-outfit-btn" in r.text

    def test_contains_build_a_look_link_in_header(self, client):
        """WN-238: nav reduced to logo / Build a look / Saved. Outfits link removed."""
        r = client.get("/outfits")
        assert 'href="/outfit-generator"' in r.text

    def test_security_headers_present(self, client):
        r = client.get("/outfits")
        assert "content-security-policy" in r.headers


# ------------------------------------------------------------------ #
# POST /outfits/complete (WN-101)                                      #
# ------------------------------------------------------------------ #


class TestOutfitComplete:
    def test_returns_empty_when_no_api_key(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = client.post("/outfits/complete", json={"items": [{"name": "white shirt"}]})
        assert r.status_code == 200
        assert r.json()["suggestions"] == []

    def test_returns_suggestions_when_key_set(self, client, monkeypatch):
        from unittest.mock import AsyncMock, patch

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        expected = ["navy chinos", "leather belt", "oxford shoes"]
        with patch("main.suggest_outfit_completion", new=AsyncMock(return_value=expected)):
            r = client.post("/outfits/complete", json={"items": [{"name": "white shirt"}]})
        assert r.status_code == 200
        assert r.json()["suggestions"] == expected

    def test_returns_empty_on_llm_error(self, client, monkeypatch):
        from unittest.mock import AsyncMock, patch

        from llm import LLMError

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with patch("main.suggest_outfit_completion", new=AsyncMock(side_effect=LLMError("fail"))):
            r = client.post("/outfits/complete", json={"items": [{"name": "white shirt"}]})
        assert r.status_code == 200
        assert r.json()["suggestions"] == []

    def test_requires_items_field(self, client):
        r = client.post("/outfits/complete", json={})
        assert r.status_code == 422


# ------------------------------------------------------------------ #
# _expanded_search unit tests (WN-067)                                 #
# ------------------------------------------------------------------ #


class TestExpandedSearchUnit:
    """Unit tests for _expanded_search() via direct import."""

    @pytest.mark.asyncio
    async def test_llm_expansion_merges_and_deduplicates(self, monkeypatch):
        """LLM succeeds → parallel searches run, products merged and deduplicated."""
        from main import _expanded_search

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        product_a = _make_product("Blue Shirt")
        product_a = product_a.model_copy(update={"id": "id-a"})
        product_b = _make_product("White Tee")
        product_b = product_b.model_copy(update={"id": "id-b"})
        product_c = _make_product("Blue Shirt Duplicate")
        product_c = product_c.model_copy(update={"id": "id-a"})  # same id as product_a

        terms = ["blue shirt", "white tee"]
        search_results = [[product_a, product_c], [product_b]]

        call_count = 0

        async def _mock_expand(query):
            return terms

        async def _mock_search(term, api_key, fresh=False):
            nonlocal call_count
            idx = call_count % len(search_results)
            call_count += 1
            return search_results[idx]

        with (
            patch("main.expand_query", new=AsyncMock(side_effect=_mock_expand)),
            patch("main.search_products", new=AsyncMock(side_effect=_mock_search)),
        ):
            products, llm_used = await _expanded_search("shirts", "test-api-key", fresh=False)

        assert llm_used is True
        ids = [p.id for p in products]
        assert ids.count("id-a") == 1, "Duplicate product should appear only once"
        assert "id-b" in ids

    @pytest.mark.asyncio
    async def test_llm_not_configured_falls_back_to_direct_search(self, monkeypatch):
        """LLMNotConfiguredError → falls back to direct search, llm_used=False."""
        from llm import LLMNotConfiguredError
        from main import _expanded_search

        fallback_product = _make_product("Fallback Item")

        with (
            patch("main.expand_query", new=AsyncMock(side_effect=LLMNotConfiguredError("no key"))),
            patch("main.search_products", new=AsyncMock(return_value=[fallback_product])),
        ):
            products, llm_used = await _expanded_search("shirts", "test-api-key", fresh=False)

        assert llm_used is False
        assert len(products) == 1
        assert products[0].name == "Fallback Item"

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_direct_search(self, monkeypatch):
        """LLMError → falls back to direct search, llm_used=False."""
        from llm import LLMError
        from main import _expanded_search

        fallback_product = _make_product("Fallback Item")

        with (
            patch("main.expand_query", new=AsyncMock(side_effect=LLMError("api error"))),
            patch("main.search_products", new=AsyncMock(return_value=[fallback_product])),
        ):
            products, llm_used = await _expanded_search("shirts", "test-api-key", fresh=False)

        assert llm_used is False
        assert products[0].name == "Fallback Item"

    @pytest.mark.asyncio
    async def test_all_parallel_searches_fail_falls_back_to_direct_search(self, monkeypatch):
        """All parallel searches raise exceptions → second fallback to direct search."""
        from main import _expanded_search
        from search import SearchError

        fallback_product = _make_product("Direct Fallback")
        direct_call_count = 0

        async def _mock_search(term, api_key, fresh=False):
            nonlocal direct_call_count
            # First two calls (parallel expanded) fail; third (direct fallback) succeeds
            direct_call_count += 1
            if direct_call_count <= 2:
                raise SearchError("fail", error_type="serpapi_timeout")
            return [fallback_product]

        with (
            patch("main.expand_query", new=AsyncMock(return_value=["term1", "term2"])),
            patch("main.search_products", new=AsyncMock(side_effect=_mock_search)),
        ):
            products, llm_used = await _expanded_search("shirts", "test-api-key", fresh=False)

        assert llm_used is False
        assert products[0].name == "Direct Fallback"

    @pytest.mark.asyncio
    async def test_partial_parallel_success_returns_successful_results(self, monkeypatch):
        """One parallel search fails, one succeeds → only successful results returned."""
        from main import _expanded_search
        from search import SearchError

        good_product = _make_product("Good Item")
        good_product = good_product.model_copy(update={"id": "good-id"})
        call_count = 0

        async def _mock_search(term, api_key, fresh=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SearchError("fail", error_type="serpapi_timeout")
            return [good_product]

        with (
            patch("main.expand_query", new=AsyncMock(return_value=["fail-term", "good-term"])),
            patch("main.search_products", new=AsyncMock(side_effect=_mock_search)),
        ):
            products, llm_used = await _expanded_search("shirts", "test-api-key", fresh=False)

        assert llm_used is True
        assert len(products) == 1
        assert products[0].name == "Good Item"


# ------------------------------------------------------------------ #
# GET /search?expand=false + llm_used in JSON response (WN-067)        #
# ------------------------------------------------------------------ #


class TestGetClientIp:
    """WN-081: X-Forwarded-For IP reading for rate limiting."""

    def test_returns_direct_ip_without_trusted_proxy(self, client, monkeypatch):
        """Without TRUSTED_PROXY, X-Forwarded-For is ignored."""
        monkeypatch.delenv("TRUSTED_PROXY", raising=False)
        # The TestClient always sends requests from testclient; just verify it doesn't crash
        with patch("main.search_products", new=AsyncMock(return_value=[])):
            r = client.get("/search?q=shirt", headers={"X-Forwarded-For": "1.2.3.4"})
        assert r.status_code == 200

    def test_uses_xff_leftmost_ip_when_trusted_proxy_set(self, monkeypatch):
        """With TRUSTED_PROXY set, leftmost X-Forwarded-For IP is used for rate limiting."""
        from unittest.mock import MagicMock

        from main import _get_client_ip
        monkeypatch.setenv("TRUSTED_PROXY", "10.0.0.1")
        req = MagicMock()
        req.headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
        req.client = MagicMock()
        req.client.host = "10.0.0.1"
        assert _get_client_ip(req) == "203.0.113.5"

    def test_falls_back_to_direct_ip_when_xff_absent(self, monkeypatch):
        """With TRUSTED_PROXY set but no XFF header, falls back to direct IP."""
        from unittest.mock import MagicMock

        from main import _get_client_ip
        monkeypatch.setenv("TRUSTED_PROXY", "10.0.0.1")
        req = MagicMock()
        req.headers = {}
        req.client = MagicMock()
        req.client.host = "10.0.0.1"
        assert _get_client_ip(req) == "10.0.0.1"

    def test_falls_back_when_trusted_proxy_not_set(self, monkeypatch):
        """Without TRUSTED_PROXY, always uses direct connection IP."""
        from unittest.mock import MagicMock

        from main import _get_client_ip
        monkeypatch.delenv("TRUSTED_PROXY", raising=False)
        req = MagicMock()
        req.headers = {"x-forwarded-for": "203.0.113.5"}
        req.client = MagicMock()
        req.client.host = "10.0.0.1"
        assert _get_client_ip(req) == "10.0.0.1"


class TestExpandedSearchLogEvents:
    """WN-075: expanded_search_completed and llm_expansion_skipped events."""

    @pytest.mark.asyncio
    async def test_expanded_search_completed_emitted_on_success(self, capsys):
        import json as _json

        from main import _expanded_search

        product = _make_product("Shirt")
        product = product.model_copy(update={"id": "p1"})

        with (
            patch("main.expand_query", new=AsyncMock(return_value=["term1", "term2"])),
            patch("main.search_products", new=AsyncMock(return_value=[product])),
        ):
            await _expanded_search("shirts", "key", fresh=False)

        out = capsys.readouterr().out
        events = [_json.loads(line) for line in out.strip().splitlines() if line]
        completed = [e for e in events if e.get("event") == "expanded_search_completed"]
        assert completed, "expected expanded_search_completed event"
        ev = completed[0]
        assert ev["term_count"] == 2
        assert ev["successful_search_count"] == 2
        assert ev["failed_search_count"] == 0
        assert "merged_product_count" in ev
        assert ev["fallback_used"] is False
        assert "total_latency_ms" in ev

    @pytest.mark.asyncio
    async def test_llm_expansion_skipped_emitted_when_not_configured(self, capsys):
        import json as _json

        from llm import LLMNotConfiguredError
        from main import _expanded_search

        with (
            patch("main.expand_query", new=AsyncMock(side_effect=LLMNotConfiguredError("no key"))),
            patch("main.search_products", new=AsyncMock(return_value=[])),
        ):
            await _expanded_search("shirts", "key", fresh=False)

        out = capsys.readouterr().out
        events = [_json.loads(line) for line in out.strip().splitlines() if line]
        skipped = [e for e in events if e.get("event") == "llm_expansion_skipped"]
        assert skipped, "expected llm_expansion_skipped event"
        assert skipped[0]["reason"] == "not_configured"

    @pytest.mark.asyncio
    async def test_llm_error_does_not_emit_skipped(self, capsys):
        import json as _json

        from llm import LLMError
        from main import _expanded_search

        with (
            patch("main.expand_query", new=AsyncMock(side_effect=LLMError("api error"))),
            patch("main.search_products", new=AsyncMock(return_value=[])),
        ):
            await _expanded_search("shirts", "key", fresh=False)

        out = capsys.readouterr().out
        events = [_json.loads(line) for line in out.strip().splitlines() if line]
        skipped = [e for e in events if e.get("event") == "llm_expansion_skipped"]
        assert not skipped, "llm_expansion_skipped should NOT be emitted on LLMError"

    @pytest.mark.asyncio
    async def test_expanded_search_completed_fallback_used_true(self, capsys):
        import json as _json

        from main import _expanded_search
        from search import SearchError

        fallback = _make_product("Fallback")
        call_count = 0

        async def _mock_search(term, api_key, fresh=False):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise SearchError("fail")
            return [fallback]

        with (
            patch("main.expand_query", new=AsyncMock(return_value=["t1", "t2"])),
            patch("main.search_products", new=AsyncMock(side_effect=_mock_search)),
        ):
            await _expanded_search("shirts", "key", fresh=False)

        out = capsys.readouterr().out
        events = [_json.loads(line) for line in out.strip().splitlines() if line]
        completed = [e for e in events if e.get("event") == "expanded_search_completed"]
        assert completed
        assert completed[0]["fallback_used"] is True


class TestExpandParam:
    def test_expand_false_bypasses_llm(self, client, monkeypatch):
        """expand=false should call search_products directly, not _expanded_search."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with (
            patch("main._expanded_search", new=AsyncMock(return_value=([], True))) as mock_exp,
            patch("main.search_products", new=AsyncMock(return_value=[])) as mock_search,
        ):
            r = client.get("/search?q=shirt&expand=false&format=json")
        assert r.status_code == 200
        mock_exp.assert_not_called()
        mock_search.assert_called_once()

    def test_expand_true_uses_expanded_search_when_key_present(self, client, monkeypatch):
        """expand=true (default) with OPENAI_API_KEY should call _expanded_search."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with patch("main._expanded_search", new=AsyncMock(return_value=([], True))) as mock_exp:
            r = client.get("/search?q=shirt&expand=true&format=json")
        assert r.status_code == 200
        mock_exp.assert_called_once()

    def test_json_response_includes_llm_used_true(self, client, monkeypatch):
        """When _expanded_search returns llm_used=True, JSON response includes it."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with patch("main._expanded_search", new=AsyncMock(return_value=([], True))):
            r = client.get("/search?q=shirt&format=json")
        data = r.json()
        assert data["llm_used"] is True

    def test_json_response_includes_llm_used_false_when_no_key(self, client, monkeypatch):
        """Without OPENAI_API_KEY, llm_used must be False in JSON response."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("main.search_products", new=AsyncMock(return_value=[])):
            r = client.get("/search?q=shirt&format=json")
        data = r.json()
        assert data["llm_used"] is False


# ------------------------------------------------------------------ #
# GET /image-proxy (WN-117)                                           #
# ------------------------------------------------------------------ #


class TestImageProxy:
    """Image proxy tests — uses client.stream() async context manager."""

    def _make_stream_mock(self, headers: dict, chunks: list[bytes] | None = None, exc=None):
        """Build a mock that supports `async with client.stream(...) as resp`."""
        from unittest.mock import AsyncMock, MagicMock
        import contextlib

        async def _aiter_bytes(chunk_size=65536):  # noqa: ARG001
            if chunks:
                for chunk in chunks:
                    yield chunk

        mock_resp = MagicMock()
        mock_resp.headers = headers
        mock_resp.aiter_bytes = _aiter_bytes

        @contextlib.asynccontextmanager
        async def _stream(*args, **kwargs):  # noqa: ARG001
            if exc:
                raise exc
            yield mock_resp

        mock_client = MagicMock()
        mock_client.stream = _stream
        return mock_client

    def test_valid_image_returns_bytes(self, client):
        image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        mock_client = self._make_stream_mock(
            {"content-type": "image/jpeg"},
            chunks=[image_bytes],
        )
        with patch("main._get_http_client", return_value=mock_client):
            r = client.get("/image-proxy?url=https://example.com/img.jpg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/jpeg")
        assert r.content == image_bytes

    def test_non_http_url_returns_400(self, client):
        r = client.get("/image-proxy?url=ftp://example.com/img.jpg")
        assert r.status_code == 400
        assert "Invalid URL" in r.json()["error"]

    def test_private_ip_returns_400(self, client):
        r = client.get("/image-proxy?url=http://127.0.0.1/img.jpg")
        assert r.status_code == 400
        assert "Forbidden" in r.json()["error"]

    def test_non_image_content_type_returns_400(self, client):
        mock_client = self._make_stream_mock({"content-type": "text/html"}, chunks=[b"<html>"])
        with patch("main._get_http_client", return_value=mock_client):
            r = client.get("/image-proxy?url=https://example.com/page.html")
        assert r.status_code == 400
        assert "Not an image" in r.json()["error"]

    def test_timeout_returns_504(self, client):
        import httpx
        mock_client = self._make_stream_mock({}, exc=httpx.TimeoutException("timed out"))
        with patch("main._get_http_client", return_value=mock_client):
            r = client.get("/image-proxy?url=https://example.com/slow.jpg")
        assert r.status_code == 504
        assert "timeout" in r.json()["error"].lower()

    def test_upstream_error_returns_502(self, client):
        mock_client = self._make_stream_mock({}, exc=OSError("connection refused"))
        with patch("main._get_http_client", return_value=mock_client):
            r = client.get("/image-proxy?url=https://example.com/img.jpg")
        assert r.status_code == 502
        assert "Upstream error" in r.json()["error"]

    def test_content_length_over_10mb_returns_413(self, client):
        """Content-Length header > 10MB → 413 without streaming body."""
        mock_client = self._make_stream_mock(
            {"content-type": "image/jpeg", "content-length": str(11 * 1024 * 1024)},
            chunks=[],
        )
        with patch("main._get_http_client", return_value=mock_client):
            r = client.get("/image-proxy?url=https://example.com/huge.jpg")
        assert r.status_code == 413
        assert "too large" in r.json()["error"].lower()

    def test_streaming_over_10mb_returns_413(self, client):
        """No Content-Length but accumulated bytes > 10MB → 413."""
        big_chunk = b"\x00" * (11 * 1024 * 1024)
        mock_client = self._make_stream_mock(
            {"content-type": "image/jpeg"},
            chunks=[big_chunk],
        )
        with patch("main._get_http_client", return_value=mock_client):
            r = client.get("/image-proxy?url=https://example.com/stream.jpg")
        assert r.status_code == 413


# ------------------------------------------------------------------ #
# WN-069: Multi-worker startup warning                                 #
# ------------------------------------------------------------------ #


class TestRequestCorrelationId:
    def test_request_id_present_in_log_events(self, client, capsys):
        client.get("/")
        out = capsys.readouterr().out
        import json as _json
        events = [_json.loads(line) for line in out.strip().splitlines() if line.strip()]
        assert any("request_id" in e for e in events), "No log event contained request_id"

    def test_request_id_is_uuid_format(self, client, capsys):
        import re
        import json as _json
        client.get("/")
        out = capsys.readouterr().out
        events = [_json.loads(line) for line in out.strip().splitlines() if line.strip()]
        rid = next((e["request_id"] for e in events if "request_id" in e), None)
        assert rid is not None
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", rid)


class TestMultiWorkerStartupWarning:
    def test_no_warning_when_web_concurrency_not_set(self, monkeypatch, capsys):
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
        import main
        import rate_limit

        rate_limit._search_timestamps.clear()
        rate_limit._fresh_timestamps.clear()
        with TestClient(main.app):
            pass
        out = capsys.readouterr().out
        assert "WEB_CONCURRENCY" not in out

    def test_no_warning_when_web_concurrency_is_one(self, monkeypatch, capsys):
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
        import main
        import rate_limit

        rate_limit._search_timestamps.clear()
        rate_limit._fresh_timestamps.clear()
        with TestClient(main.app):
            pass
        out = capsys.readouterr().out
        assert "WARNING" not in out

    def test_warning_emitted_when_web_concurrency_gt_one(self, monkeypatch, capsys):
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
        import main
        import rate_limit

        rate_limit._search_timestamps.clear()
        rate_limit._fresh_timestamps.clear()
        with TestClient(main.app):
            out = capsys.readouterr().out
        assert "WARNING" in out
        assert "WEB_CONCURRENCY=4" in out

    def test_startup_warning_event_emitted(self, monkeypatch, capsys):
        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        monkeypatch.setenv("SERPAPI_KEY", "test-key-12345")
        import main
        import rate_limit

        rate_limit._search_timestamps.clear()
        rate_limit._fresh_timestamps.clear()
        with TestClient(main.app):
            out = capsys.readouterr().out
        assert "startup_warning" in out
        assert "multi_worker_in_process_state" in out


class TestSearchRefine:
    """Tests for POST /search/refine."""

    def test_returns_new_query_on_success(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with patch("main.refine_query", new=AsyncMock(return_value="navy chinos under 50")):
            resp = client.post(
                "/search/refine",
                json={"original_query": "navy chinos", "refinement": "under 50"},
            )
        assert resp.status_code == 200
        assert resp.json()["new_query"] == "navy chinos under 50"

    def test_graceful_degradation_when_no_api_key(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from llm import LLMNotConfiguredError
        with patch("main.refine_query", new=AsyncMock(side_effect=LLMNotConfiguredError("no key"))):
            resp = client.post(
                "/search/refine",
                json={"original_query": "navy chinos", "refinement": "under 50"},
            )
        assert resp.status_code == 200
        assert resp.json()["new_query"] == "navy chinos"

    def test_graceful_degradation_on_llm_error(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        from llm import LLMError
        with patch("main.refine_query", new=AsyncMock(side_effect=LLMError("api error"))):
            resp = client.post(
                "/search/refine",
                json={"original_query": "navy chinos", "refinement": "under 50"},
            )
        assert resp.status_code == 200
        assert resp.json()["new_query"] == "navy chinos"

    def test_missing_original_query_returns_400(self, client):
        resp = client.post(
            "/search/refine",
            json={"original_query": "", "refinement": "under 50"},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_missing_refinement_returns_400(self, client):
        resp = client.post(
            "/search/refine",
            json={"original_query": "navy chinos", "refinement": ""},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_original_query_truncated_to_500_chars(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        long_query = "x" * 600
        with patch("main.refine_query", new=AsyncMock(return_value="truncated result")) as mock_refine:
            resp = client.post(
                "/search/refine",
                json={"original_query": long_query, "refinement": "something"},
            )
        assert resp.status_code == 200
        called_original = mock_refine.call_args[0][0]
        assert len(called_original) <= 500

    def test_refinement_truncated_to_200_chars(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        long_refinement = "r" * 300
        with patch("main.refine_query", new=AsyncMock(return_value="result")) as mock_refine:
            resp = client.post(
                "/search/refine",
                json={"original_query": "navy chinos", "refinement": long_refinement},
            )
        assert resp.status_code == 200
        called_refinement = mock_refine.call_args[0][1]
        assert len(called_refinement) <= 200


# ------------------------------------------------------------------ #
# GET /list (WN-046)                                                   #
# ------------------------------------------------------------------ #


class TestCuratedList:
    def test_list_page_renders(self, client):
        r = client.get("/list")
        assert r.status_code == 200

    def test_list_page_with_v_param(self, client):
        import base64, json
        items = [{"id": "1", "name": "Test Shirt", "price": "£30", "retailer": "ASOS", "image": "", "url": "https://example.com"}]
        encoded = base64.b64encode(json.dumps(items).encode()).decode()
        r = client.get(f"/list?v={encoded}")
        assert r.status_code == 200
        assert "curated-list-page" in r.text

    def test_list_page_empty_v_shows_empty(self, client):
        r = client.get("/list?v=")
        assert r.status_code == 200
        assert "curated-list-empty" in r.text


class TestOutfitGenerator:
    def test_generator_page_renders(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-anthropic-key")
        r = client.get("/outfit-generator")
        assert r.status_code == 200
        assert "outfit-gen-form" in r.text

    def test_generator_page_shows_unavailable_without_llm(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = client.get("/outfit-generator")
        assert r.status_code == 200
        assert "outfit-gen-unavailable" in r.text

    def test_generate_happy_path(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        queries = {
            "shoes": "white leather trainers", "pants": "slim chinos",
            "accessory": "leather belt", "shirt": "white oxford shirt",
            "jacket": "navy blazer", "headwear": "baseball cap",
        }
        product = _make_product("White Trainers")
        with (
            patch("main.generate_outfit_queries", new=AsyncMock(return_value=queries)),
            patch("main.search_products", new=AsyncMock(return_value=[product])),
        ):
            r = client.post("/outfit/generate", json={"description": "smart casual weekend"})
        assert r.status_code == 200
        data = r.json()
        assert data["description"] == "smart casual weekend"
        assert set(data["items"].keys()) == {"shoes", "pants", "accessory", "shirt", "jacket", "headwear"}
        assert data["items"]["shoes"]["name"] == "White Trainers"

    def test_generate_partial_empty_categories(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        queries = {
            "shoes": "trainers", "pants": "chinos", "accessory": "belt",
            "shirt": "oxford shirt", "jacket": "blazer", "headwear": "cap",
        }
        product = _make_product()

        async def mock_search(q, key, **kw):
            if q == "cap":
                return []
            return [product]

        with (
            patch("main.generate_outfit_queries", new=AsyncMock(return_value=queries)),
            patch("main.search_products", new=mock_search),
        ):
            r = client.post("/outfit/generate", json={"description": "casual"})
        assert r.status_code == 200
        data = r.json()
        assert data["items"]["headwear"] is None
        assert data["items"]["shoes"]["name"] == "Blue Shirt"

    def test_generate_empty_description_returns_422(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        r = client.post("/outfit/generate", json={"description": ""})
        assert r.status_code == 422

    def test_generate_too_long_description_returns_422(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        r = client.post("/outfit/generate", json={"description": "x" * 101})
        assert r.status_code == 422

    def test_generate_no_llm_key_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = client.post("/outfit/generate", json={"description": "casual summer"})
        assert r.status_code == 503

    def test_generate_llm_not_configured_returns_503(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        from llm import LLMNotConfiguredError
        with patch("main.generate_outfit_queries", new=AsyncMock(side_effect=LLMNotConfiguredError())):
            r = client.post("/outfit/generate", json={"description": "smart casual"})
        assert r.status_code == 503

    def test_generate_rate_limited(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        import rate_limit, time
        # TestClient uses "testclient" as the request client host
        rate_limit._search_timestamps["testclient"] = [time.monotonic()] * 10
        r = client.post("/outfit/generate", json={"description": "smart casual"})
        assert r.status_code == 429
