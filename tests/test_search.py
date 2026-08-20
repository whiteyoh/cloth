"""Unit tests for search.py — normaliser, record-drop logic, cache integration."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cache
from search import SearchError, _normalise_result, _unwrap_google_url, search_products

_RETRIEVED_AT = datetime(2026, 8, 14, 14, 32, 0, tzinfo=timezone.utc)

_VALID_ITEM = {
    "title": "Blue Linen Shirt",
    "price": "£34.99",
    "imageUrl": "https://img.example.com/shirt.jpg",
    "source": "ASOS",
    "link": "https://www.asos.com/product/12345",
}



# ------------------------------------------------------------------ #
# _normalise_result                                                    #
# ------------------------------------------------------------------ #


class TestNormaliseResultHappyPath:
    def test_all_fields_present_returns_product(self):
        product = _normalise_result(_VALID_ITEM, _RETRIEVED_AT)
        assert product is not None
        assert product.name == "Blue Linen Shirt"
        assert product.price_display == "£34.99"
        assert product.price_value == pytest.approx(34.99)
        assert product.price_currency == "GBP"
        assert product.retailer_name == "ASOS"
        assert product.purchase_url == "https://www.asos.com/product/12345"
        assert product.image_url == "https://img.example.com/shirt.jpg"
        assert product.retrieved_at == _RETRIEVED_AT

    def test_id_is_deterministic(self):
        p1 = _normalise_result(_VALID_ITEM, _RETRIEVED_AT)
        p2 = _normalise_result(_VALID_ITEM, _RETRIEVED_AT)
        assert p1 is not None and p2 is not None
        assert p1.id == p2.id

    def test_missing_thumbnail_sets_image_url_to_none(self):
        item = {**_VALID_ITEM, "imageUrl": ""}
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.image_url is None

    def test_missing_price_sets_price_fields_to_none(self):
        item = dict(_VALID_ITEM)
        del item["price"]
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.price_value is None
        assert product.price_display is None


class TestNormaliseResultRecordDrop:
    def test_missing_title_returns_none(self, capsys):
        item = {**_VALID_ITEM, "title": ""}
        result = _normalise_result(item, _RETRIEVED_AT, position=0)
        assert result is None
        out = capsys.readouterr().out
        assert "record_dropped" in out
        assert "missing_name" in out

    def test_missing_source_returns_none(self, capsys):
        item = {**_VALID_ITEM, "source": ""}
        result = _normalise_result(item, _RETRIEVED_AT, position=1)
        assert result is None
        out = capsys.readouterr().out
        assert "record_dropped" in out
        assert "missing_retailer_name" in out

    def test_missing_link_returns_none(self, capsys):
        item = {**_VALID_ITEM, "link": ""}
        result = _normalise_result(item, _RETRIEVED_AT, position=2)
        assert result is None
        out = capsys.readouterr().out
        assert "record_dropped" in out
        assert "missing_purchase_url" in out

    def test_absent_title_key_returns_none(self, capsys):
        item = {k: v for k, v in _VALID_ITEM.items() if k != "title"}
        result = _normalise_result(item, _RETRIEVED_AT)
        assert result is None

    def test_absent_source_key_returns_none(self, capsys):
        item = {k: v for k, v in _VALID_ITEM.items() if k != "source"}
        result = _normalise_result(item, _RETRIEVED_AT)
        assert result is None

    def test_absent_link_key_returns_none(self, capsys):
        item = {k: v for k, v in _VALID_ITEM.items() if k != "link"}
        result = _normalise_result(item, _RETRIEVED_AT)
        assert result is None

    def test_position_logged_on_drop(self, capsys):
        item = {**_VALID_ITEM, "title": ""}
        _normalise_result(item, _RETRIEVED_AT, position=7)
        out = capsys.readouterr().out
        assert '"position": 7' in out


class TestNormaliseResultUrlSchemeValidation:
    def test_javascript_uri_drops_record(self, capsys):
        item = {**_VALID_ITEM, "link": "javascript:alert(1)"}
        result = _normalise_result(item, _RETRIEVED_AT, position=3)
        assert result is None
        out = capsys.readouterr().out
        assert "record_dropped" in out
        assert "invalid_purchase_url_scheme" in out

    def test_data_uri_drops_record(self, capsys):
        item = {**_VALID_ITEM, "link": "data:text/html,<script>alert(1)</script>"}
        result = _normalise_result(item, _RETRIEVED_AT, position=4)
        assert result is None
        out = capsys.readouterr().out
        assert "record_dropped" in out
        assert "invalid_purchase_url_scheme" in out

    def test_https_url_is_accepted(self):
        item = {**_VALID_ITEM, "link": "https://www.asos.com/product/123"}
        result = _normalise_result(item, _RETRIEVED_AT, position=5)
        assert result is not None
        assert result.purchase_url == "https://www.asos.com/product/123"


class TestNormaliseResultInStock:
    def test_in_stock_true_extracted(self):
        item = {**_VALID_ITEM, "in_stock": True}
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.in_stock is True

    def test_in_stock_false_extracted(self):
        item = {**_VALID_ITEM, "in_stock": False}
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.in_stock is False

    def test_in_stock_from_extensions(self):
        item = {**_VALID_ITEM, "extensions": {"in_stock": True}}
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.in_stock is True

    def test_in_stock_absent_returns_none(self):
        product = _normalise_result(_VALID_ITEM, _RETRIEVED_AT)
        assert product is not None
        assert product.in_stock is None

    def test_non_bool_in_stock_ignored(self):
        item = {**_VALID_ITEM, "in_stock": "yes"}
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.in_stock is None


class TestNormaliseResultNameTruncation:
    def test_long_name_is_truncated(self):
        """name[:197] + '…' (the ellipsis is one Unicode char → 198 chars total)."""
        long_name = "X" * 250
        item = {**_VALID_ITEM, "title": long_name}
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.name == "X" * 197 + "…"
        assert len(product.name) == 198
        assert product.name.endswith("…")


# ------------------------------------------------------------------ #
# search_products (integration with mocked httpx)                     #
# ------------------------------------------------------------------ #


def _make_mock_response(shopping_results):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"shopping": shopping_results}
    return mock_resp


def _make_mock_client(mock_response):
    """Return an AsyncMock that behaves like an httpx.AsyncClient."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


class TestSearchProductsHappyPath:
    async def test_returns_product_list(self):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            products = await search_products("blue linen shirt", "fake-key")

        assert len(products) == 1
        assert products[0].name == "Blue Linen Shirt"

    async def test_result_stored_in_cache(self):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            await search_products("navy chinos", "fake-key")

        normalised = cache.normalise_key("navy chinos")
        assert cache.get(normalised) is not None

    async def test_empty_shopping_results_returns_empty_list(self):
        mock_resp = _make_mock_response([])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            products = await search_products("neon gilet", "fake-key")

        assert products == []

    async def test_search_completed_event_emitted(self, capsys):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            await search_products("blue shirt", "fake-key")

        out = capsys.readouterr().out
        assert "search_completed" in out
        assert '"cache_hit": false' in out.lower() or '"cache_hit": False' in out


class TestSearchProductsRecordDropping:
    async def test_invalid_item_dropped_valid_returned(self):
        items = [
            {**_VALID_ITEM, "title": ""},  # dropped — missing name
            _VALID_ITEM,  # valid
        ]
        mock_resp = _make_mock_response(items)
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            products = await search_products("blue shirt", "fake-key")

        assert len(products) == 1
        assert products[0].name == "Blue Linen Shirt"

    async def test_all_invalid_items_returns_empty_list(self):
        items = [
            {**_VALID_ITEM, "title": ""},
            {**_VALID_ITEM, "source": ""},
        ]
        mock_resp = _make_mock_response(items)
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            products = await search_products("query", "fake-key")

        assert products == []


class TestSearchProductsCaching:
    async def test_second_call_uses_cache(self):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            await search_products("blue shirt", "fake-key")
            await search_products("blue shirt", "fake-key")

        # HTTP POST should only have been called once (second call is cache hit)
        assert mock_client.post.call_count == 1

    async def test_case_insensitive_cache_hit(self):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            await search_products("Blue Shirt", "fake-key")
            await search_products("blue shirt", "fake-key")

        assert mock_client.post.call_count == 1

    async def test_fresh_true_bypasses_cache(self):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            await search_products("blue shirt", "fake-key")
            await search_products("blue shirt", "fake-key", fresh=True)

        # Both calls should have gone to the search API (2 HTTP POSTs)
        assert mock_client.post.call_count == 2

    async def test_cache_hit_emits_cache_hit_true(self, capsys):
        mock_resp = _make_mock_response([_VALID_ITEM])
        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            await search_products("navy chinos", "fake-key")
            capsys.readouterr()  # discard first call output
            await search_products("navy chinos", "fake-key")

        out = capsys.readouterr().out
        assert "search_completed" in out
        assert '"cache_hit": true' in out.lower() or '"cache_hit": True' in out


class TestSearchProductsErrors:
    async def test_timeout_raises_search_error(self):
        import httpx

        mock_client = _make_mock_client(MagicMock())
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("search._get_http_client", return_value=mock_client):
            with pytest.raises(SearchError) as exc_info:
                await search_products("query", "fake-key")

        assert exc_info.value.error_type == "serpapi_timeout"

    async def test_http_401_raises_auth_error(self):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        http_error = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)

        mock_client = _make_mock_client(MagicMock())
        mock_client.post = AsyncMock(side_effect=http_error)

        with patch("search._get_http_client", return_value=mock_client):
            with pytest.raises(SearchError) as exc_info:
                await search_products("query", "fake-key")

        assert exc_info.value.error_type == "serpapi_auth_error"

    async def test_http_429_raises_rate_limit_error(self):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 429
        http_error = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_response)

        mock_client = _make_mock_client(MagicMock())
        mock_client.post = AsyncMock(side_effect=http_error)

        with patch("search._get_http_client", return_value=mock_client):
            with pytest.raises(SearchError) as exc_info:
                await search_products("query", "fake-key")

        assert exc_info.value.error_type == "serpapi_rate_limit"

    async def test_missing_shopping_results_key_raises_schema_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"error": "unexpected"}

        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            with pytest.raises(SearchError) as exc_info:
                await search_products("query", "fake-key")

        assert exc_info.value.error_type == "serpapi_schema_error"

    async def test_non_dict_json_response_raises_schema_error(self):
        """If SerpAPI returns valid JSON that is not a dict (e.g. an array), treat as schema error."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"unexpected": "array"}]

        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            with pytest.raises(SearchError) as exc_info:
                await search_products("query", "fake-key")

        assert exc_info.value.error_type == "serpapi_schema_error"

    async def test_json_decode_error_raises_schema_error(self, capsys):
        import json

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError("expecting value", "", 0)

        mock_client = _make_mock_client(mock_resp)

        with patch("search._get_http_client", return_value=mock_client):
            with pytest.raises(SearchError) as exc_info:
                await search_products("query", "fake-key")

        assert exc_info.value.error_type == "serpapi_schema_error"
        out = capsys.readouterr().out
        assert "search_error" in out
        assert "serpapi_schema_error" in out


# ------------------------------------------------------------------ #
# _unwrap_google_url                                                   #
# ------------------------------------------------------------------ #


class TestUnwrapGoogleUrl:
    def test_non_google_url_returned_unchanged(self):
        url = "https://www.asos.com/product/12345"
        assert _unwrap_google_url(url) == url

    def test_google_redirect_url_unwrapped(self):
        actual = "https://www.asos.com/product/12345"
        redirect = f"https://www.google.com/url?q={actual}&sa=U&ved=abc"
        assert _unwrap_google_url(redirect) == actual

    def test_google_redirect_url_unwrapped_co_uk(self):
        actual = "https://www.next.co.uk/product/99"
        redirect = f"https://www.google.co.uk/url?q={actual}&sa=U"
        assert _unwrap_google_url(redirect) == actual

    def test_google_shopping_product_page_returned_unchanged(self):
        """Shopping product pages can't be unwrapped — return as-is."""
        url = "https://www.google.com/shopping/product/12345/specs?q=coat"
        assert _unwrap_google_url(url) == url

    def test_non_http_q_param_not_used(self):
        """q= param that isn't http/https must not be returned."""
        url = "https://www.google.com/url?q=javascript:alert(1)"
        result = _unwrap_google_url(url)
        assert result == url  # can't unwrap, returned as-is

    def test_google_redirect_to_google_not_returned(self):
        """If q= points back to Google, don't unwrap."""
        inner = "https://www.google.com/search?q=something"
        redirect = f"https://www.google.com/url?q={inner}"
        assert _unwrap_google_url(redirect) == redirect

    def test_retailer_link_preferred_over_google_link_in_normalise(self):
        """When link= is a Google URL, productLink= direct retailer is used instead."""
        item = {
            **_VALID_ITEM,
            "link": "https://www.google.com/shopping/product/99",
            "productLink": "https://www.next.co.uk/p/coat",
        }
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.purchase_url == "https://www.next.co.uk/p/coat"

    def test_google_redirect_link_unwrapped_in_normalise(self):
        """Google /url?q= redirect in link= is resolved to the real product URL."""
        actual = "https://www.asos.com/product/99"
        item = {
            **_VALID_ITEM,
            "link": f"https://www.google.com/url?q={actual}&sa=U&ved=xyz",
        }
        product = _normalise_result(item, _RETRIEVED_AT)
        assert product is not None
        assert product.purchase_url == actual
