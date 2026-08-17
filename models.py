from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Currency symbol → ISO 4217 code. Order matters: A$ and C$ before $ to avoid false match.
_CURRENCY_MAP: dict[str, str] = {
    "A$": "AUD",
    "C$": "CAD",
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
    "¢": "JPY",
    "₹": "INR",
}

_AMBIGUOUS_SYMBOLS = {"¥", "¢"}
_NUMERIC_STRIP_RE = re.compile(r"[^\d.,]")


def parse_price(price_str: str | None) -> tuple[float | None, str, str | None]:
    """Parse a SerpAPI price string into (price_value, price_currency, price_display).

    price_display is the verbatim raw string (or None when absent/empty).
    price_currency defaults to GBP when symbol is absent or unrecognised.
    price_value is None when the string cannot be parsed to a float.
    """
    if not price_str or not price_str.strip():
        return None, "GBP", None

    price_display: str | None = price_str.strip()

    # Infer currency from the first recognised symbol found in the string.
    price_currency = "GBP"
    for symbol, currency in _CURRENCY_MAP.items():
        if symbol in price_str:
            if symbol in _AMBIGUOUS_SYMBOLS:
                logger.warning(
                    "Ambiguous currency symbol %r in price %r; defaulting to %s",
                    symbol,
                    price_str,
                    currency,
                )
            price_currency = currency
            break

    # Extract only digits, commas and periods for numeric parsing.
    numeric = _NUMERIC_STRIP_RE.sub("", price_str)
    if not numeric:
        return None, price_currency, price_display

    if "," in numeric and "." in numeric:
        # Both separators present → comma is the thousands separator (e.g. "1,299.00").
        numeric = numeric.replace(",", "")
    elif "," in numeric:
        # Only comma present → it is the decimal separator (e.g. "59,90").
        numeric = numeric.replace(",", ".")

    try:
        price_value: float | None = float(numeric)
    except ValueError:
        return None, price_currency, price_display

    return price_value, price_currency, price_display


def _truncate_name(name: Any) -> str:
    """Truncate name to 200 chars with ellipsis, preserving unicode boundaries."""
    if not isinstance(name, str):
        name = str(name)
    if len(name) > 200:
        return name[:197] + "…"
    return name


class Product(BaseModel):
    id: str
    name: str
    image_url: str | None = None
    price_value: float | None = None
    price_currency: str = "GBP"
    price_display: str | None = None
    retailer_name: str
    purchase_url: str
    source_api: str = "serpapi_google_shopping"
    retrieved_at: datetime
    in_stock: bool | None = None

    @classmethod
    def generate_id(cls, source_api: str, purchase_url: str) -> str:
        """Derive a stable 16-hex-char ID from source API name and purchase URL."""
        return hashlib.sha256(f"{source_api}:{purchase_url}".encode()).hexdigest()[:16]
