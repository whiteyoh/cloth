"""OpenAI ChatGPT integration for natural language query expansion and outfit generation."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import openai

from utils import _emit

_MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "You are a clothing search assistant. When given a natural language clothing description, "
    "expand it into 2–3 specific, targeted Google Shopping search terms.\n\n"
    "Return ONLY a JSON array of strings — no explanation, no markdown:\n"
    '[\"term one\", \"term two\"]\n\n'
    "Rules:\n"
    "- Terms should be specific enough to return relevant products\n"
    "- Include material, colour, style attributes where relevant\n"
    "- Keep each term under 60 characters\n"
    "- Return 2–3 terms, never more"
)


class LLMError(Exception):
    """Raised when OpenAI API call fails in a non-recoverable way."""

    def __init__(self, message: str = "", error_type: str = "unknown") -> None:
        super().__init__(message)
        self.error_type = error_type


class LLMNotConfiguredError(LLMError):
    """Raised when OPENAI_API_KEY is not set."""


_client: openai.AsyncOpenAI | None = None


def _get_client(api_key: str) -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=api_key)
    return _client


def _get_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not configured",
            error_type="not_configured",
        )
    return key


async def _chat(system: str, user: str, max_tokens: int = 256) -> str:
    """Make a single ChatGPT call. Returns the response text."""
    api_key = _get_api_key()
    client = _get_client(api_key)
    response = await client.chat.completions.create(
        model=_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    if not response.choices:
        raise LLMError("Empty response from OpenAI", error_type="schema_error")
    content = response.choices[0].message.content
    if not content:
        raise LLMError("Empty content from OpenAI", error_type="schema_error")
    return content


_SUGGEST_SYSTEM_PROMPT = (
    "You are a clothing search assistant. A user searched for something and got zero results. "
    "Suggest 3–4 alternative phrasings they could try instead.\n\n"
    "Return ONLY a JSON array of strings — no explanation, no markdown:\n"
    '[\"alternative one\", \"alternative two\", \"alternative three\"]\n\n'
    "Rules:\n"
    "- Use simpler or broader terms than the original query\n"
    "- Try different style, colour, or occasion angles\n"
    "- Keep each suggestion under 50 characters\n"
    "- Return 3–4 alternatives, never more"
)


async def suggest_alternatives(query: str) -> list[str]:
    """Suggest 3–4 alternative search queries when no results were found."""
    _get_api_key()  # raises LLMNotConfiguredError if absent
    start = time.monotonic()

    try:
        text = await _chat(_SUGGEST_SYSTEM_PROMPT, query)
        elapsed_ms = round((time.monotonic() - start) * 1000)

        suggestions = json.loads(text)
        if not isinstance(suggestions, list) or not all(isinstance(s, str) for s in suggestions):
            raise LLMError("Unexpected response format from OpenAI", error_type="schema_error")

        suggestions = [s.strip() for s in suggestions if s.strip()][:4]

        _emit({
            "event": "llm_no_results_suggested",
            "query_length": len(query),
            "suggestion_count": len(suggestions),
            "llm_latency_ms": elapsed_ms,
            "model": _MODEL,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        return suggestions

    except json.JSONDecodeError as exc:
        raise LLMError("OpenAI returned non-JSON response", error_type="json_parse_error") from exc
    except openai.APIError as exc:
        raise LLMError(f"OpenAI API error: {exc}", error_type="api_error") from exc


_OUTFIT_COMPLETE_SYSTEM_PROMPT = (
    "You are a fashion stylist. Given a list of clothing items a user has in an outfit, "
    "suggest 3–5 items that would complete the look.\n\n"
    "Return ONLY a JSON array of short item description strings — no explanation, no markdown:\n"
    '[\"white oxford shirt\", \"leather oxford shoes\"]\n\n'
    "Rules:\n"
    "- Suggest items the user does not already have\n"
    "- Keep each suggestion under 50 characters\n"
    "- Be specific (include colour, material, or style)\n"
    "- Return 3–5 suggestions, never more"
)


async def suggest_outfit_completion(item_names: list[str]) -> list[str]:
    """Suggest items to complete an outfit given existing item names."""
    _get_api_key()
    start = time.monotonic()
    user_content = "Outfit items: " + ", ".join(item_names)

    try:
        text = await _chat(_OUTFIT_COMPLETE_SYSTEM_PROMPT, user_content)
        elapsed_ms = round((time.monotonic() - start) * 1000)

        suggestions = json.loads(text)
        if not isinstance(suggestions, list) or not all(isinstance(s, str) for s in suggestions):
            raise LLMError("Unexpected response format from OpenAI", error_type="schema_error")

        suggestions = [s.strip() for s in suggestions if s.strip()][:5]

        _emit({
            "event": "llm_outfit_completion",
            "item_count": len(item_names),
            "suggestion_count": len(suggestions),
            "llm_latency_ms": elapsed_ms,
            "model": _MODEL,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        return suggestions

    except json.JSONDecodeError as exc:
        raise LLMError("OpenAI returned non-JSON response", error_type="json_parse_error") from exc
    except openai.APIError as exc:
        raise LLMError(f"OpenAI API error: {exc}", error_type="api_error") from exc


_REFINE_SYSTEM_PROMPT = (
    "You are a clothing search assistant. A user has refined their search. "
    "Combine their original query and refinement into a single, targeted Google Shopping search term.\n\n"
    "Return ONLY the new search query as a plain string — no explanation, no quotes, no JSON:\n\n"
    "Rules:\n"
    "- The result must be a single search query, not multiple\n"
    "- Keep it under 80 characters\n"
    "- Incorporate the refinement intent (price limit, colour change, brand preference, etc.)\n"
    "- Be specific but not overly long"
)


async def refine_query(original_query: str, refinement: str) -> str:
    """Combine an original query with a natural-language refinement into a new search term."""
    _get_api_key()
    start = time.monotonic()
    user_content = f'Original search: "{original_query}"\nRefinement: "{refinement}"'

    try:
        text = await _chat(_REFINE_SYSTEM_PROMPT, user_content, max_tokens=128)
        elapsed_ms = round((time.monotonic() - start) * 1000)

        new_query = text.strip().strip('"').strip("'")
        if not new_query:
            raise LLMError("OpenAI returned empty query", error_type="schema_error")

        _emit({
            "event": "llm_query_refined",
            "original_length": len(original_query),
            "refinement_length": len(refinement),
            "result_length": len(new_query),
            "llm_latency_ms": elapsed_ms,
            "model": _MODEL,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        return new_query

    except openai.APIError as exc:
        raise LLMError(f"OpenAI API error: {exc}", error_type="api_error") from exc


_OUTFIT_GENERATE_SYSTEM_PROMPT = (
    "You are a fashion stylist. Given a short style description, generate targeted Google Shopping "
    "search phrases for each of these clothing categories: shoes, pants, accessory, shirt, jacket, headwear.\n\n"
    'Return ONLY a JSON object with exactly these six keys — no explanation, no markdown:\n'
    '{"shoes": "...", "pants": "...", "accessory": "...", "shirt": "...", "jacket": "...", "headwear": "..."}\n\n'
    "Rules:\n"
    "- Each value must be a concrete, specific Google Shopping search phrase under 70 characters\n"
    "- Include gender, style, material or colour attributes where appropriate\n"
    "- Make all six items work together as a cohesive outfit\n"
    "- Do not return null or empty strings — always provide a search phrase for every category"
)

_OUTFIT_CATEGORIES = ("shoes", "pants", "accessory", "shirt", "jacket", "headwear")


async def generate_outfit_queries(description: str) -> dict[str, str]:
    """Generate 6 category-specific Google Shopping search phrases for a style description."""
    _get_api_key()
    start = time.monotonic()

    try:
        text = await _chat(_OUTFIT_GENERATE_SYSTEM_PROMPT, description, max_tokens=512)
        elapsed_ms = round((time.monotonic() - start) * 1000)

        queries = json.loads(text)
        if not isinstance(queries, dict):
            raise LLMError("OpenAI returned non-object response", error_type="schema_error")

        missing = [k for k in _OUTFIT_CATEGORIES if k not in queries or not queries[k]]
        if missing:
            raise LLMError(
                f"OpenAI response missing categories: {missing}", error_type="schema_error"
            )

        result = {k: str(queries[k]).strip()[:70] for k in _OUTFIT_CATEGORIES}

        _emit({
            "event": "llm_outfit_queries_generated",
            "description_length": len(description),
            "llm_latency_ms": elapsed_ms,
            "model": _MODEL,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        return result

    except json.JSONDecodeError as exc:
        raise LLMError("OpenAI returned non-JSON response", error_type="json_parse_error") from exc
    except openai.APIError as exc:
        raise LLMError(f"OpenAI API error: {exc}", error_type="api_error") from exc


async def expand_query(query: str) -> list[str]:
    """Expand a natural-language clothing query into 2–3 targeted search terms."""
    _get_api_key()
    start = time.monotonic()

    try:
        text = await _chat(_SYSTEM_PROMPT, query)
        elapsed_ms = round((time.monotonic() - start) * 1000)

        terms = json.loads(text)
        if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
            raise LLMError("Unexpected response format from OpenAI", error_type="schema_error")

        terms = [t.strip() for t in terms if t.strip()][:3]

        _emit({
            "event": "llm_query_expanded",
            "query_length": len(query),
            "term_count": len(terms),
            "llm_expand_latency_ms": elapsed_ms,
            "model": _MODEL,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        return terms

    except json.JSONDecodeError as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        _emit({
            "event": "llm_expand_error",
            "error_type": "json_parse_error",
            "llm_expand_latency_ms": elapsed_ms,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })
        raise LLMError("OpenAI returned non-JSON response", error_type="json_parse_error") from exc

    except openai.APIError as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        _emit({
            "event": "llm_expand_error",
            "error_type": "api_error",
            "llm_expand_latency_ms": elapsed_ms,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })
        raise LLMError(f"OpenAI API error: {exc}", error_type="api_error") from exc
