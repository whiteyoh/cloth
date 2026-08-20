"""Cloth — FastAPI application entry point."""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import cache
import rate_limit
from llm import (
    LLMError,
    LLMNotConfiguredError,
    expand_query,
    generate_outfit_queries,
    refine_query,
    suggest_alternatives,
    suggest_outfit_completion,
)
from search import SearchError, _get_http_client, close_http_client, search_products
from utils import _emit, _hash_ip, _request_id

load_dotenv()

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _render_cards_html(products: list) -> str:
    """Render a list of products as HTML card fragments using the card.html partial.

    Returns a single string containing concatenated <li> elements, ready to be
    inserted into a <ul class="product-grid"> by the client.
    """
    card_template = templates.env.get_template("card.html")
    return "".join(
        card_template.render(product=product, position=i)
        for i, product in enumerate(products)
    )


def _get_client_ip(request: Request) -> str:
    """Return the real client IP, honouring X-Forwarded-For when TRUSTED_PROXY is set.

    When TRUSTED_PROXY env var is non-empty, the leftmost address in the
    X-Forwarded-For header is used (that is the original client IP added by
    the proxy before any internal hops). Without TRUSTED_PROXY set, the direct
    connection address is used to avoid IP spoofing via forged headers.
    """
    if os.environ.get("TRUSTED_PROXY"):
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            leftmost = xff.split(",")[0].strip()
            if leftmost:
                return leftmost
    return request.client.host if request.client else "unknown"


_SEARCH_ERROR_MESSAGES: dict[str, str] = {
    "serpapi_timeout": "Search took too long. Please try again.",
    "serpapi_rate_limit": "Too many searches. Please wait a moment and try again.",
    "serpapi_auth_error": "Search is temporarily unavailable. Please try again later.",
    "serpapi_schema_error": "Search service returned an unexpected response. Please try again.",
    "serpapi_budget_exhausted": "Search is temporarily unavailable. Please try again later.",
    "unknown": "We couldn't reach the search service. Please try again.",
}

_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://s.skimresources.com; "
    "img-src 'self' https://*.google.com https://*.gstatic.com https://*.ggpht.com "
    "https://*.googleusercontent.com https://*.googleapis.com data:; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' https://go.skimresources.com https://r.skimresources.com; "
    "frame-ancestors 'none';"
)

# Hostnames / prefixes that must never be fetched by the image proxy (SSRF guard).
_SSRF_PRIVATE = (
    "localhost",
    "127.", "0.", "10.",
    "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.",
    "172.31.",
    "192.168.", "169.254.",
    "::1", "[::1]",
)


async def _expanded_search(
    query: str, api_key: str, fresh: bool
) -> tuple[list, bool]:
    """Run LLM query expansion then parallel SerpAPI calls.

    Returns (products, llm_used). Falls back to a single direct search if the
    LLM is unavailable or fails.
    """
    start = time.monotonic()

    # Try LLM expansion, capped at 5s so a slow Anthropic response never stalls the user
    try:
        terms = await asyncio.wait_for(expand_query(query), timeout=5.0)
    except asyncio.TimeoutError:
        _emit(
            {
                "event": "llm_expansion_skipped",
                "reason": "timeout",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        products = await search_products(query, api_key, fresh=fresh)
        return products, False
    except LLMNotConfiguredError:
        # LLM not configured — emit skipped event and fall back to direct search
        _emit(
            {
                "event": "llm_expansion_skipped",
                "reason": "not_configured",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        products = await search_products(query, api_key, fresh=fresh)
        return products, False
    except LLMError:
        # LLM failed — fall back to direct search without emitting skipped
        products = await search_products(query, api_key, fresh=fresh)
        return products, False

    # Run one search per expanded term in parallel
    results = await asyncio.gather(
        *[search_products(term, api_key, fresh=fresh) for term in terms],
        return_exceptions=True,
    )

    # Merge, deduplicate by product ID, preserve order
    successful_count = 0
    failed_count = 0
    seen: set[str] = set()
    merged: list = []
    for result in results:
        if isinstance(result, Exception):
            failed_count += 1
            continue
        successful_count += 1
        for product in result:
            if product.id not in seen:
                seen.add(product.id)
                merged.append(product)

    # If all expanded searches failed, fall back to direct search
    if not merged and not seen:
        products = await search_products(query, api_key, fresh=fresh)
        total_ms = round((time.monotonic() - start) * 1000)
        _emit(
            {
                "event": "expanded_search_completed",
                "term_count": len(terms),
                "successful_search_count": successful_count,
                "failed_search_count": failed_count,
                "merged_product_count": len(products),
                "fallback_used": True,
                "total_latency_ms": total_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        return products, False

    total_ms = round((time.monotonic() - start) * 1000)
    _emit(
        {
            "event": "expanded_search_completed",
            "term_count": len(terms),
            "successful_search_count": successful_count,
            "failed_search_count": failed_count,
            "merged_product_count": len(merged),
            "fallback_used": False,
            "total_latency_ms": total_ms,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    return merged, True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate required environment variables at startup; clean up on shutdown."""
    serpapi_key = os.environ.get("SERPER_API_KEY") or os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        raise ValueError(
            "SERPER_API_KEY environment variable is not set. Cannot start application."
        )
    templates.env.globals["refine_enabled"] = bool(os.environ.get("OPENAI_API_KEY"))
    templates.env.globals["skimlinks_pub_id"] = os.environ.get("SKIMLINKS_PUB_ID", "")

    web_concurrency_str = os.environ.get("WEB_CONCURRENCY", "")
    if web_concurrency_str:
        try:
            web_concurrency = int(web_concurrency_str)
        except ValueError:
            web_concurrency = 0
        if web_concurrency > 1:
            warning_msg = (
                f"WARNING: WEB_CONCURRENCY={web_concurrency} detected. "
                "cloth uses in-process state for cache and rate limiting. "
                "Each worker maintains independent counters, so effective rate limits "
                f"and budget tracking multiply by {web_concurrency}. "
                "Run with a single worker (WEB_CONCURRENCY=1) or migrate to a "
                "shared store (Redis) before scaling. See OPERATIONS.md."
            )
            print(warning_msg, flush=True)
            _emit(
                {
                    "event": "startup_warning",
                    "warning_type": "multi_worker_in_process_state",
                    "web_concurrency": web_concurrency,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

    yield
    await close_http_client()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.middleware("http")
async def timing_and_csp_middleware(request: Request, call_next):
    """Record per-request latency and add CSP header to every response."""
    _request_id.set(str(uuid.uuid4()))
    start = time.monotonic()
    response = await call_next(request)
    total_ms = round((time.monotonic() - start) * 1000)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    _emit(
        {
            "event": "request_completed",
            "method": request.method,
            "path": str(request.url.path),
            "status_code": response.status_code,
            "total_latency_ms": total_ms,
        }
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions; return a friendly error page (HTTP 200)."""
    _emit(
        {
            "event": "unhandled_exception",
            "exception_class": type(exc).__name__,
            "exception_message": str(exc),
            "path": str(request.url.path),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "query": request.query_params.get("q", ""),
                "products": [],
                "error_message": "Something went wrong. Please try again.",
                "result_count": 0,
                "cache_age_minutes": None,
            },
        )
    except Exception:  # noqa: BLE001
        return HTMLResponse(
            content="<h1>Something went wrong. Please try again.</h1>",
            status_code=200,
        )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the dress.me commercial / landing page."""
    from fastapi.responses import FileResponse as _FR
    return _FR(os.path.join(_TEMPLATES_DIR, "advert.html"), media_type="text/html")


@app.get("/find", response_class=HTMLResponse)
async def find(request: Request):
    """Render the search home page."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/search", response_class=HTMLResponse)
async def get_search(request: Request, q: str = "", fresh: bool = False, format: str = "html", expand: bool = True, start: int = 0):  # noqa: A002
    """Execute a product search and render the results page."""
    q_stripped = q.strip()
    want_json = format == "json"

    if not q_stripped:
        if want_json:
            return JSONResponse({"query": q, "products": [], "result_count": 0, "cache_age_minutes": None, "error_message": "Please enter a search term"})
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "query": q,
                "error": "Please enter a search term",
            },
        )

    if len(q) > 500:  # noqa: PLR2004
        if want_json:
            return JSONResponse({"query": q, "products": [], "result_count": 0, "cache_age_minutes": None, "error_message": "Search query is too long (maximum 500 characters)"})
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "query": q,
                "error": "Search query is too long (maximum 500 characters)",
            },
        )

    client_ip = _get_client_ip(request)

    if fresh and not rate_limit.check_fresh(client_ip):
        _emit(
            {
                "event": "rate_limit_rejected",
                "ip": _hash_ip(client_ip),
                "limit_type": "fresh",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        msg = "Too many refresh requests. Please wait a moment before refreshing again."
        if want_json:
            return JSONResponse({"query": q_stripped, "products": [], "result_count": 0, "cache_age_minutes": None, "error_message": msg})
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "query": q_stripped,
                "products": [],
                "error_message": msg,
                "result_count": 0,
                "cache_age_minutes": None,
            },
        )

    if not rate_limit.check_search(client_ip):
        _emit(
            {
                "event": "rate_limit_rejected",
                "ip": _hash_ip(client_ip),
                "limit_type": "search",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        msg = "Too many searches. Please wait a moment and try again."
        if want_json:
            return JSONResponse({"query": q_stripped, "products": [], "result_count": 0, "cache_age_minutes": None, "error_message": msg})
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "query": q_stripped,
                "products": [],
                "error_message": msg,
                "result_count": 0,
                "cache_age_minutes": None,
            },
        )

    api_key = os.environ.get("SERPER_API_KEY") or os.environ.get("SERPAPI_KEY", "")

    try:
        if expand and os.environ.get("OPENAI_API_KEY") and start == 0:
            products, llm_used = await _expanded_search(q_stripped, api_key, fresh=fresh)
        else:
            products = await search_products(q_stripped, api_key, fresh=fresh, start=start)
            llm_used = False
    except SearchError as exc:
        error_msg = _SEARCH_ERROR_MESSAGES.get(exc.error_type, _SEARCH_ERROR_MESSAGES["unknown"])
        if want_json:
            return JSONResponse({"query": q_stripped, "products": [], "result_count": 0, "cache_age_minutes": None, "error_message": error_msg})
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "query": q_stripped,
                "products": [],
                "error_message": error_msg,
                "result_count": 0,
                "cache_age_minutes": None,
                "llm_used": False,
            },
        )

    retrieved_at = products[0].retrieved_at if products else None
    result_count = len(products)
    cache_age_minutes = None
    if retrieved_at is not None:
        delta_seconds = (datetime.now(timezone.utc) - retrieved_at).total_seconds()
        cache_age_minutes = max(0, round(delta_seconds / 60))

    # When no results, ask Claude for alternative query suggestions (degrades gracefully)
    llm_suggestions: list[str] = []
    if not products and os.environ.get("OPENAI_API_KEY"):
        try:
            llm_suggestions = await suggest_alternatives(q_stripped)
        except (LLMError, LLMNotConfiguredError):
            pass

    if want_json:
        return JSONResponse({
            "query": q_stripped,
            "products": [p.model_dump(mode="json") for p in products],
            "product_ids": [p.id for p in products],
            "cards_html": _render_cards_html(products),
            "result_count": result_count,
            "cache_age_minutes": cache_age_minutes,
            "error_message": None,
            "llm_used": llm_used,
            "expand_available": bool(os.environ.get("OPENAI_API_KEY")),
            "start": start,
            "has_more": result_count == 10,
            "llm_suggestions": llm_suggestions,
        })

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": q_stripped,
            "products": products,
            "retrieved_at": retrieved_at,
            "result_count": result_count,
            "cache_age_minutes": cache_age_minutes,
            "llm_used": llm_used,
            "llm_suggestions": llm_suggestions,
        },
    )


@app.post("/search")
async def post_search(q: str = Form(default="")):
    """Accept a POST form submission and redirect to GET /search."""
    return RedirectResponse(url=f"/search?q={quote(q)}", status_code=303)


class _RefineRequest(BaseModel):
    original_query: str
    refinement: str


@app.post("/search/refine")
async def search_refine(body: _RefineRequest) -> JSONResponse:
    """Combine original_query + refinement via Claude to produce a new targeted query.

    Returns {"new_query": "..."} on success.
    Returns {"new_query": original_query} when LLM is unavailable (graceful degradation).
    """
    original = body.original_query.strip()[:500]
    refinement = body.refinement.strip()[:200]

    if not original or not refinement:
        return JSONResponse({"error": "original_query and refinement are required"}, status_code=400)

    try:
        new_query = await refine_query(original, refinement)
        return JSONResponse({"new_query": new_query})
    except LLMNotConfiguredError:
        return JSONResponse({"new_query": original})
    except LLMError:
        return JSONResponse({"new_query": original})


@app.get("/health")
async def health():
    """Health check endpoint. Does not make a search API call (preserves quota)."""
    return {
        "status": "ok",
        "search_api_key_configured": bool(os.environ.get("SERPER_API_KEY") or os.environ.get("SERPAPI_KEY")),
        "cache": cache.stats(),
    }


@app.get("/saved", response_class=HTMLResponse)
async def saved_items(request: Request):
    """Render the saved items page (populated client-side from localStorage)."""
    return templates.TemplateResponse(request, "saved.html")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    """Render the privacy notice page."""
    return templates.TemplateResponse(request, "privacy.html")


@app.get("/how-it-works", response_class=HTMLResponse)
async def how_it_works(request: Request):
    """Render the how it works page."""
    return templates.TemplateResponse(request, "how_it_works.html")


@app.get("/advert", response_class=HTMLResponse)
async def advert(request: Request):
    """Render the dress.me commercial page."""
    from fastapi.responses import FileResponse
    import os
    path = os.path.join(_TEMPLATES_DIR, "advert.html")
    return FileResponse(path, media_type="text/html")


@app.get("/outfits", response_class=HTMLResponse)
async def outfits(request: Request):
    """Render the outfit mood boards page (populated client-side from localStorage)."""
    return templates.TemplateResponse(request, "outfits.html")


@app.get("/list", response_class=HTMLResponse)
async def curated_list(request: Request, v: str = ""):
    """Render a shareable curated list page. Items are encoded as base64 JSON in ?v=."""
    return templates.TemplateResponse(request, "list.html", {"v": v})


class _OutfitItem(BaseModel):
    name: str


class _OutfitCompleteRequest(BaseModel):
    items: list[_OutfitItem]


@app.post("/outfits/complete")
async def outfit_complete(body: _OutfitCompleteRequest):
    """Return LLM-generated suggestions to complete an outfit.

    Returns {"suggestions": [...]} or {"suggestions": []} when unavailable.
    Requires OPENAI_API_KEY.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return JSONResponse({"suggestions": []})

    _emit(
        {
            "event": "llm_outfit_completion",
            "item_count": len(body.items),
        }
    )

    try:
        suggestions = await suggest_outfit_completion([item.name for item in body.items])
    except (LLMError, LLMNotConfiguredError):
        return JSONResponse({"suggestions": []})

    return JSONResponse({"suggestions": suggestions})


@app.get("/image-proxy")
async def image_proxy(url: str):
    """Proxy a remote image through the server to bypass browser CORS restrictions.

    Fetches the upstream image using the shared httpx singleton and returns it
    same-origin so canvas.toBlob() can draw it without tainting the canvas.
    """
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "Invalid URL"}, status_code=400)

    hostname = urlparse(url).hostname or ""
    if any(hostname == p or hostname.startswith(p) for p in _SSRF_PRIVATE):
        return JSONResponse({"error": "Forbidden"}, status_code=400)

    _PROXY_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    start = time.monotonic()
    try:
        client = _get_http_client()
        # Stream the response so we can enforce a size cap without buffering excess data
        async with client.stream("GET", url, timeout=8.0, follow_redirects=True) as resp:
            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                _emit({
                    "event": "image_proxy_error",
                    "error_type": "not_image",
                    "url_hash": url_hash,
                    "content_type": content_type,
                })
                return JSONResponse({"error": "Not an image"}, status_code=400)

            # Reject immediately if Content-Length header exceeds cap
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > _PROXY_MAX_BYTES:
                _emit({"event": "image_proxy_size_exceeded", "url_hash": url_hash, "size_bytes": int(content_length)})
                return JSONResponse({"error": "Image too large"}, status_code=413)

            chunks: list[bytes] = []
            accumulated = 0
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                accumulated += len(chunk)
                if accumulated > _PROXY_MAX_BYTES:
                    _emit({"event": "image_proxy_size_exceeded", "url_hash": url_hash, "size_bytes": accumulated})
                    return JSONResponse({"error": "Image too large"}, status_code=413)
                chunks.append(chunk)

        content = b"".join(chunks)
        latency_ms = round((time.monotonic() - start) * 1000)
        _emit({
            "event": "image_proxy_fetched",
            "url_hash": url_hash,
            "content_type": content_type,
            "size_bytes": len(content),
            "latency_ms": latency_ms,
        })
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except httpx.TimeoutException:
        _emit({"event": "image_proxy_error", "error_type": "timeout", "url_hash": url_hash})
        return JSONResponse({"error": "Upstream timeout"}, status_code=504)
    except Exception as exc:  # noqa: BLE001
        _emit({
            "event": "image_proxy_error",
            "error_type": "upstream_error",
            "url_hash": url_hash,
            "exception": type(exc).__name__,
        })
        return JSONResponse({"error": "Upstream error"}, status_code=502)


# ------------------------------------------------------------------ #
# WN-185 + WN-186 — Outfit generator                                  #
# ------------------------------------------------------------------ #

class OutfitGenerateRequest(BaseModel):
    description: str


@app.get("/outfit-generator", response_class=HTMLResponse)
async def get_outfit_generator(request: Request):
    return templates.TemplateResponse(request, "outfit_generator.html", {
        "llm_enabled": bool(os.environ.get("OPENAI_API_KEY")),
    })


@app.post("/outfit/generate")
async def post_outfit_generate(request: Request, body: OutfitGenerateRequest):
    description = body.description.strip()
    if not description:
        return JSONResponse({"error": "description is required"}, status_code=422)
    if len(description) > 100:
        return JSONResponse({"error": "description must be 100 characters or fewer"}, status_code=422)

    api_key = os.environ.get("SERPER_API_KEY") or os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        return JSONResponse({"error": "Search service unavailable"}, status_code=503)

    client_ip = _get_client_ip(request)
    if not rate_limit.check_search(client_ip):
        _emit({
            "event": "rate_limit_rejected",
            "ip_hash": _hash_ip(client_ip),
            "limit_type": "outfit_generate",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })
        return JSONResponse(
            {"error": "Too many requests. Please wait a moment and try again."},
            status_code=429,
        )

    start = time.monotonic()

    # LLM generates one search phrase per category
    try:
        queries = await asyncio.wait_for(generate_outfit_queries(description), timeout=8.0)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "AI took too long. Please try again."}, status_code=504)
    except LLMNotConfiguredError:
        return JSONResponse({"error": "AI not configured"}, status_code=503)
    except LLMError as exc:
        return JSONResponse({"error": f"AI error: {exc}"}, status_code=500)

    # Run 6 parallel SerpAPI searches, one per category
    categories = list(queries.keys())
    results = await asyncio.gather(
        *[search_products(queries[cat], api_key, fresh=False) for cat in categories],
        return_exceptions=True,
    )

    items: dict[str, dict | None] = {}
    success_count = 0
    fail_count = 0
    for cat, result in zip(categories, results):
        if isinstance(result, Exception) or not result:
            items[cat] = None
            fail_count += 1
        else:
            p = result[0]
            items[cat] = {
                "id": p.id,
                "name": p.name,
                "price_display": p.price_display,
                "price_value": p.price_value,
                "retailer_name": p.retailer_name,
                "purchase_url": p.purchase_url,
                "image_url": p.image_url,
                "in_stock": p.in_stock,
                "search_query": queries[cat],
            }
            success_count += 1

    latency_ms = round((time.monotonic() - start) * 1000)
    _emit({
        "event": "outfit_generate_completed",
        "description_length": len(description),
        "success_count": success_count,
        "fail_count": fail_count,
        "latency_ms": latency_ms,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    })

    return JSONResponse({
        "description": description,
        "items": items,
    })
