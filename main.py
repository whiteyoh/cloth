"""Cloth — FastAPI application entry point."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
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


def _render_cards_html(products: list, try_on_enabled: bool = False) -> str:
    """Render a list of products as HTML card fragments using the card.html partial.

    Returns a single string containing concatenated <li> elements, ready to be
    inserted into a <ul class="product-grid"> by the client.
    """
    card_template = templates.env.get_template("card.html")
    return "".join(
        card_template.render(product=product, position=i, try_on_enabled=try_on_enabled)
        for i, product in enumerate(products)
    )


# Magic byte signatures for allowed image types
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}

_FASHN_AI_BASE = "https://api.fashn.ai/v1"

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
    "img-src 'self' https://*.google.com https://*.gstatic.com https://*.ggpht.com "
    "https://*.googleusercontent.com https://*.googleapis.com data:; "
    "style-src 'self' 'unsafe-inline'; "
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


async def _call_fashn_ai(image_bytes: bytes, garment_url: str, api_key: str) -> str:
    """Call Fashn.ai try-on API; return the result image URL.

    Sends the person photo as a base64 data URI and the garment as its URL.
    Polls up to 10 times with 3-second sleeps (30 second maximum wait).
    """
    mime = "image/png" if image_bytes[:8] == _PNG_MAGIC else "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode()
    data_uri = f"data:{mime};base64,{b64}"

    client = _get_http_client()
    start_resp = await client.post(
        f"{_FASHN_AI_BASE}/run",
        json={"model_image": data_uri, "garment_image": garment_url, "category": "tops"},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15.0,
    )
    start_resp.raise_for_status()
    job_id = start_resp.json()["id"]

    for _ in range(10):
        await asyncio.sleep(3)
        status_resp = await client.get(
            f"{_FASHN_AI_BASE}/status/{job_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        current_status = status_data.get("status", "")
        if current_status == "completed":
            outputs = status_data.get("output", [])
            if outputs:
                return outputs[0]
            raise RuntimeError("No output URL in completed response")
        if current_status in ("failed", "error"):
            raise RuntimeError(f"Try-on failed: {status_data.get('error', 'unknown')}")

    raise TimeoutError("Try-on timed out after 30 seconds")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate required environment variables at startup; clean up on shutdown."""
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        raise ValueError(
            "SERPAPI_KEY environment variable is not set. Cannot start application."
        )
    templates.env.globals["try_on_enabled"] = bool(os.environ.get("FASHN_API_KEY"))
    templates.env.globals["refine_enabled"] = bool(os.environ.get("ANTHROPIC_API_KEY"))

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

    api_key = os.environ.get("SERPAPI_KEY", "")

    try:
        if expand and os.environ.get("ANTHROPIC_API_KEY") and start == 0:
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
    if not products and not want_json and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            llm_suggestions = await suggest_alternatives(q_stripped)
        except (LLMError, LLMNotConfiguredError):
            pass

    if want_json:
        _try_on_enabled = bool(os.environ.get("FASHN_API_KEY"))
        return JSONResponse({
            "query": q_stripped,
            "products": [p.model_dump(mode="json") for p in products],
            "product_ids": [p.id for p in products],
            "cards_html": _render_cards_html(products, try_on_enabled=_try_on_enabled),
            "result_count": result_count,
            "cache_age_minutes": cache_age_minutes,
            "error_message": None,
            "llm_used": llm_used,
            "expand_available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "start": start,
            "has_more": result_count == 10,
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
    """Health check endpoint. Does not call SerpAPI (preserves quota)."""
    return {
        "status": "ok",
        "serpapi_key_configured": bool(os.environ.get("SERPAPI_KEY")),
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


@app.get("/outfits", response_class=HTMLResponse)
async def outfits(request: Request):
    """Render the outfit mood boards page (populated client-side from localStorage)."""
    return templates.TemplateResponse(request, "outfits.html")


class _OutfitItem(BaseModel):
    name: str


class _OutfitCompleteRequest(BaseModel):
    items: list[_OutfitItem]


@app.post("/outfits/complete")
async def outfit_complete(body: _OutfitCompleteRequest):
    """Return LLM-generated suggestions to complete an outfit.

    Returns {"suggestions": [...]} or {"suggestions": []} when unavailable.
    Requires ANTHROPIC_API_KEY.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
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


@app.post("/try-on")
async def try_on(
    request: Request,
    person_image: UploadFile | None = File(default=None),  # noqa: B008
    garment_url: str = Form(default=""),  # noqa: B008
):
    """Virtual try-on endpoint.

    Accepts multipart/form-data with a person photo and garment URL.
    Calls Fashn.ai to composite the garment onto the photo and returns
    the result image URL.

    Returns:
        {"result_url": "..."} on success
        {"error": "..."} on processing failure
        {"status": "unavailable"} when FASHN_API_KEY is not configured
        HTTP 400 for invalid input
        HTTP 429 when rate limit exceeded
    """
    api_key = os.environ.get("FASHN_API_KEY", "")
    if not api_key:
        return JSONResponse({"status": "unavailable"})

    client_ip = _get_client_ip(request)
    if not rate_limit.check_try_on(client_ip):
        _emit(
            {
                "event": "rate_limit_rejected",
                "ip": _hash_ip(client_ip),
                "limit_type": "try_on",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        return JSONResponse(
            {"error": "Rate limit exceeded. Maximum 3 try-ons per day."},
            status_code=429,
        )

    # Require a file upload
    if person_image is None or person_image.filename is None:
        return JSONResponse(
            {"error": "No image file provided."},
            status_code=400,
        )

    # Validate MIME type (client-supplied; checked first for fast rejection)
    if person_image.content_type not in _ALLOWED_CONTENT_TYPES:
        return JSONResponse(
            {"error": "Invalid image format. Please upload a JPEG or PNG."},
            status_code=400,
        )

    # Read the uploaded bytes; enforce size limit
    content = await person_image.read()
    if len(content) > _MAX_IMAGE_BYTES:
        return JSONResponse(
            {"error": "File too large. Maximum size is 5 MB."},
            status_code=400,
        )

    # Validate magic bytes (independent of client-supplied MIME type)
    if not (content[:3] == _JPEG_MAGIC or content[:8] == _PNG_MAGIC):
        return JSONResponse(
            {"error": "Invalid image format. File must be a JPEG or PNG."},
            status_code=400,
        )

    _emit(
        {
            "event": "try_on_requested",
            "ip": _hash_ip(client_ip),
            "image_size_bytes": len(content),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )

    start = time.monotonic()
    try:
        result_url = await _call_fashn_ai(content, garment_url, api_key)
        latency_ms = round((time.monotonic() - start) * 1000)
        _emit(
            {
                "event": "try_on_completed",
                "ip": _hash_ip(client_ip),
                "latency_ms": latency_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        return JSONResponse({"result_url": result_url})
    except Exception as exc:  # noqa: BLE001
        latency_ms = round((time.monotonic() - start) * 1000)
        _emit(
            {
                "event": "try_on_error",
                "ip": _hash_ip(client_ip),
                "error": str(exc),
                "latency_ms": latency_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        return JSONResponse({"error": "Try-on failed. Please try again."})


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

    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    start = time.monotonic()
    try:
        client = _get_http_client()
        resp = await client.get(url, timeout=8.0, follow_redirects=True)
        latency_ms = round((time.monotonic() - start) * 1000)
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            _emit({
                "event": "image_proxy_error",
                "error_type": "not_image",
                "url_hash": url_hash,
                "content_type": content_type,
            })
            return JSONResponse({"error": "Not an image"}, status_code=400)
        _emit({
            "event": "image_proxy_fetched",
            "url_hash": url_hash,
            "content_type": content_type,
            "size_bytes": len(resp.content),
            "latency_ms": latency_ms,
        })
        return Response(
            content=resp.content,
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
