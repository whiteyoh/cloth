"""SerpAPI Google Shopping integration and product normalisation."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx

import cache
from models import Product, _truncate_name, parse_price
from utils import _emit

SERPAPI_URL = "https://serpapi.com/search"
SOURCE_API = "serpapi_google_shopping"

_BUDGET_WARNING_THRESHOLD = 80
_BUDGET_EXHAUSTED_THRESHOLD = 100

# Track last search time to detect cold starts (Render.com spins down after ~15 min).
_last_search_time: float = 0.0
_COLD_START_GAP_SECONDS = 900  # 15 minutes

# Singleton httpx.AsyncClient — shared across all SerpAPI requests.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the module-level AsyncClient singleton, creating it if necessary."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


async def close_http_client() -> None:
    """Close the singleton AsyncClient. Call from app lifespan shutdown."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


class SearchError(Exception):
    """Raised when a SerpAPI call fails in a way that cannot be recovered in-process."""

    def __init__(self, message: str = "", error_type: str = "unknown") -> None:
        super().__init__(message)
        self.error_type = error_type


def _query_hash(normalised_key: str) -> str:
    return hashlib.sha256(normalised_key.encode()).hexdigest()[:12]


def _normalise_result(
    item: dict[str, Any], retrieved_at: datetime, position: int = 0
) -> Product | None:
    """Map one SerpAPI shopping_results entry to a Product, or return None to drop it.

    Emits record_dropped or price_parse_warning NDJSON events where appropriate.
    """
    title = item.get("title") or ""
    source = item.get("source") or ""
    link = item.get("link") or item.get("product_link") or ""
    thumbnail = item.get("thumbnail") or ""
    raw_price = item.get("price")

    now_iso = retrieved_at.isoformat()

    if not title:
        _emit(
            {
                "event": "record_dropped",
                "reason": "missing_name",
                "position": position,
                "timestamp_utc": now_iso,
            }
        )
        return None

    if not source:
        _emit(
            {
                "event": "record_dropped",
                "reason": "missing_retailer_name",
                "position": position,
                "title": title,
                "timestamp_utc": now_iso,
            }
        )
        return None

    if not link:
        _emit(
            {
                "event": "record_dropped",
                "reason": "missing_purchase_url",
                "position": position,
                "title": title,
                "timestamp_utc": now_iso,
            }
        )
        return None

    if not link.startswith(("http://", "https://")):
        _emit(
            {
                "event": "record_dropped",
                "reason": "invalid_purchase_url_scheme",
                "position": position,
                "url_prefix": link[:20],
                "timestamp_utc": now_iso,
            }
        )
        return None

    price_value, price_currency, price_display = parse_price(raw_price)

    if raw_price and price_display is not None and price_value is None:
        _emit(
            {
                "event": "price_parse_warning",
                "raw_price": raw_price,
                "position": position,
                "timestamp_utc": now_iso,
            }
        )

    name = _truncate_name(title)
    product_id = Product.generate_id(SOURCE_API, link)

    # Extract in_stock: may be a top-level boolean field or inside "extensions" dict.
    in_stock: bool | None = None
    if "in_stock" in item:
        raw_in_stock = item["in_stock"]
        if isinstance(raw_in_stock, bool):
            in_stock = raw_in_stock
    elif isinstance(item.get("extensions"), dict):
        ext_in_stock = item["extensions"].get("in_stock")
        if isinstance(ext_in_stock, bool):
            in_stock = ext_in_stock

    return Product(
        id=product_id,
        name=name,
        image_url=thumbnail if thumbnail else None,
        price_value=price_value,
        price_currency=price_currency,
        price_display=price_display,
        retailer_name=source,
        purchase_url=link,
        source_api=SOURCE_API,
        retrieved_at=retrieved_at,
        in_stock=in_stock,
    )


async def search_products(query: str, api_key: str, fresh: bool = False, start: int = 0) -> list[Product]:
    """Search for products matching *query*.

    Returns a (possibly empty) list of Product objects.
    Raises SearchError on unrecoverable API failures.
    Uses the in-memory cache unless fresh=True or start > 0.
    """
    global _last_search_time
    now = time.monotonic()
    cold_start = _last_search_time == 0.0 or (now - _last_search_time) > _COLD_START_GAP_SECONDS
    _last_search_time = now
    t_start = now
    normalised_key = cache.normalise_key(query)
    q_hash = _query_hash(normalised_key)

    if fresh:
        _emit(
            {
                "event": "cache_bypass_fresh",
                "query_hash": q_hash,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        cache.invalidate(normalised_key)

    if start == 0:
        cached = cache.get(normalised_key)
    else:
        cached = None

    if cached is not None:
        total_ms = round((time.monotonic() - t_start) * 1000)
        _emit(
            {
                "event": "search_completed",
                "query_hash": q_hash,
                "cache_hit": True,
                "result_count": len(cached),
                "serpapi_latency_ms": None,
                "total_latency_ms": total_ms,
                "cold_start": cold_start,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        return cached

    # Budget guard: check before making the call.
    call_count = cache.increment_serpapi_call_count()

    _emit(
        {
            "event": "serpapi_call_made",
            "query_hash": q_hash,
            "num_requested": 10,
            "monthly_call_count": call_count,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )

    if call_count == _BUDGET_WARNING_THRESHOLD:
        _emit(
            {
                "event": "serpapi_budget_warning",
                "monthly_call_count": call_count,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    if call_count >= _BUDGET_EXHAUSTED_THRESHOLD:
        _emit(
            {
                "event": "serpapi_budget_exhausted",
                "monthly_call_count": call_count,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise SearchError("SerpAPI monthly budget exhausted", error_type="serpapi_budget_exhausted")

    serpapi_start = time.monotonic()
    _search_event_emitted = False

    try:
        try:
            client = _get_http_client()
            response = await client.get(
                SERPAPI_URL,
                params={
                    "engine": "google_shopping",
                    "q": query,
                    "api_key": api_key,
                    "gl": "gb",
                    "hl": "en",
                    "num": "10",
                    **({"start": str(start)} if start else {}),
                },
            )
            response.raise_for_status()
            serpapi_ms = round((time.monotonic() - serpapi_start) * 1000)
            data = response.json()

        except httpx.TimeoutException as exc:
            total_ms = round((time.monotonic() - t_start) * 1000)
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": "serpapi_timeout",
                    "http_status_returned": 200,
                    "serpapi_status_code": None,
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            _search_event_emitted = True
            raise SearchError("SerpAPI request timed out", error_type="serpapi_timeout") from exc

        except httpx.HTTPStatusError as exc:
            total_ms = round((time.monotonic() - t_start) * 1000)
            status_code = exc.response.status_code
            if status_code == 429:  # noqa: PLR2004
                error_type = "serpapi_rate_limit"
            elif status_code in (401, 403):
                error_type = "serpapi_auth_error"
            else:
                error_type = "unknown"
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": error_type,
                    "http_status_returned": 200,
                    "serpapi_status_code": status_code,
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            _search_event_emitted = True
            raise SearchError(f"SerpAPI returned HTTP {status_code}", error_type=error_type) from exc

        except httpx.RequestError as exc:
            total_ms = round((time.monotonic() - t_start) * 1000)
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": "unknown",
                    "http_status_returned": 200,
                    "serpapi_status_code": None,
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            _search_event_emitted = True
            raise SearchError("SerpAPI request failed", error_type="unknown") from exc

        except json.JSONDecodeError as exc:
            total_ms = round((time.monotonic() - t_start) * 1000)
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": "serpapi_schema_error",
                    "http_status_returned": 200,
                    "serpapi_status_code": None,
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            _search_event_emitted = True
            raise SearchError(
                "SerpAPI returned non-JSON response", error_type="serpapi_schema_error"
            ) from exc

        if not isinstance(data, dict):
            total_ms = round((time.monotonic() - t_start) * 1000)
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": "serpapi_schema_error",
                    "http_status_returned": 200,
                    "serpapi_status_code": None,
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            _search_event_emitted = True
            raise SearchError("SerpAPI response is not a JSON object", error_type="serpapi_schema_error")

        shopping_results = data.get("shopping_results")
        if not isinstance(shopping_results, list):
            total_ms = round((time.monotonic() - t_start) * 1000)
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": "serpapi_schema_error",
                    "http_status_returned": 200,
                    "serpapi_status_code": None,
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            _search_event_emitted = True
            raise SearchError("Unexpected SerpAPI response schema", error_type="serpapi_schema_error")

        retrieved_at = datetime.now(timezone.utc)
        products: list[Product] = []
        for i, item in enumerate(shopping_results):
            product = _normalise_result(item, retrieved_at, position=i)
            if product is not None:
                products.append(product)

        if start == 0:
            cache.set(normalised_key, products)

        total_ms = round((time.monotonic() - t_start) * 1000)
        _emit(
            {
                "event": "search_completed",
                "query_hash": q_hash,
                "cache_hit": False,
                "result_count": len(products),
                "serpapi_latency_ms": serpapi_ms,
                "total_latency_ms": total_ms,
                "cold_start": cold_start,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        _search_event_emitted = True
        return products

    finally:
        if not _search_event_emitted:
            total_ms = round((time.monotonic() - t_start) * 1000)
            _emit(
                {
                    "event": "search_error",
                    "query_hash": q_hash,
                    "error_type": "unknown",
                    "total_latency_ms": total_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
