"""Unit tests for models.parse_price and Product.generate_id."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models import Product, parse_price


class TestParsePriceGbp:
    def test_gbp_symbol(self):
        value, currency, display = parse_price("£29.99")
        assert value == pytest.approx(29.99)
        assert currency == "GBP"
        assert display == "£29.99"

    def test_gbp_no_symbol_defaults_to_gbp(self):
        value, currency, display = parse_price("29.99")
        assert value == pytest.approx(29.99)
        assert currency == "GBP"
        assert display == "29.99"


class TestParsePriceUsd:
    def test_usd_symbol(self):
        value, currency, display = parse_price("$149.00")
        assert value == pytest.approx(149.0)
        assert currency == "USD"
        assert display == "$149.00"


class TestParsePriceEur:
    def test_eur_symbol(self):
        value, currency, display = parse_price("€59.90")
        assert value == pytest.approx(59.9)
        assert currency == "EUR"
        assert display == "€59.90"

    def test_eur_with_space(self):
        value, currency, display = parse_price("€ 59.90")
        assert value == pytest.approx(59.9)
        assert currency == "EUR"

    def test_comma_as_decimal_separator(self):
        """Price like '59,90' uses comma as decimal, no period."""
        value, currency, display = parse_price("€59,90")
        assert value == pytest.approx(59.9)
        assert currency == "EUR"

    def test_comma_thousands_separator(self):
        """Price like '1,299.00' uses comma as thousands separator."""
        value, currency, display = parse_price("£1,299.00")
        assert value == pytest.approx(1299.0)
        assert currency == "GBP"


class TestParsePriceEdgeCases:
    def test_none_returns_none(self):
        value, currency, display = parse_price(None)
        assert value is None
        assert currency == "GBP"
        assert display is None

    def test_empty_string_returns_none(self):
        value, currency, display = parse_price("")
        assert value is None
        assert currency == "GBP"
        assert display is None

    def test_whitespace_only_returns_none(self):
        value, currency, display = parse_price("   ")
        assert value is None
        assert currency == "GBP"
        assert display is None

    def test_unparseable_numeric_returns_none_value(self):
        """Non-numeric after stripping currency symbols → value is None."""
        value, currency, display = parse_price("£abc")
        assert value is None
        assert currency == "GBP"
        assert display == "£abc"

    def test_aud_symbol(self):
        value, currency, display = parse_price("A$45.00")
        assert value == pytest.approx(45.0)
        assert currency == "AUD"

    def test_cad_symbol(self):
        value, currency, display = parse_price("C$30.00")
        assert value == pytest.approx(30.0)
        assert currency == "CAD"

    def test_inr_symbol(self):
        value, currency, display = parse_price("₹1500")
        assert value == pytest.approx(1500.0)
        assert currency == "INR"

    def test_dollar_does_not_match_aud_string(self):
        """Plain $ must not be confused with A$."""
        value, currency, display = parse_price("$20.00")
        assert currency == "USD"

    def test_price_with_trailing_text(self):
        """Extra non-numeric chars are stripped; numeric part is parsed."""
        value, currency, display = parse_price("£34.99 each")
        assert value == pytest.approx(34.99)
        assert currency == "GBP"


class TestNameTruncation:
    def test_short_name_unchanged(self):
        """Names within 200 chars are passed through unchanged."""
        from models import _truncate_name

        name = "Blue Linen Shirt"
        assert _truncate_name(name) == name

    def test_long_name_truncated_at_197_plus_ellipsis(self):
        """Names longer than 200 chars are truncated to name[:197] + '…' (198 chars total).

        The spec (DATA_MODEL.md) prescribes `name[:197] + '…'`. The ellipsis is a single
        Unicode character (U+2026), so the result is 198 code points — within the 200-char max.
        """
        from models import _truncate_name

        name = "A" * 201
        result = _truncate_name(name)
        assert result == "A" * 197 + "…"
        assert len(result) == 198
        assert result.endswith("…")

    def test_exactly_200_chars_unchanged(self):
        from models import _truncate_name

        name = "B" * 200
        assert _truncate_name(name) == name


class TestProductGenerateId:
    def test_deterministic(self):
        """Same inputs always produce the same ID."""
        id1 = Product.generate_id("serpapi_google_shopping", "https://example.com/item/1")
        id2 = Product.generate_id("serpapi_google_shopping", "https://example.com/item/1")
        assert id1 == id2

    def test_different_urls_give_different_ids(self):
        id1 = Product.generate_id("serpapi_google_shopping", "https://example.com/item/1")
        id2 = Product.generate_id("serpapi_google_shopping", "https://example.com/item/2")
        assert id1 != id2

    def test_id_is_16_hex_chars(self):
        product_id = Product.generate_id("serpapi_google_shopping", "https://example.com/")
        assert len(product_id) == 16
        assert all(c in "0123456789abcdef" for c in product_id)

    def test_different_source_api_gives_different_id(self):
        id1 = Product.generate_id("serpapi_google_shopping", "https://example.com/")
        id2 = Product.generate_id("other_api", "https://example.com/")
        assert id1 != id2


class TestProductModel:
    def test_construct_minimal_product(self):
        product = Product(
            id="abc123",
            name="Blue Shirt",
            retailer_name="ASOS",
            purchase_url="https://www.asos.com/product/1",
            retrieved_at=datetime.now(timezone.utc),
        )
        assert product.price_currency == "GBP"
        assert product.source_api == "serpapi_google_shopping"
        assert product.image_url is None
        assert product.price_value is None
        assert product.price_display is None
