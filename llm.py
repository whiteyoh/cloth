"""Claude API integration for natural language query expansion."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import anthropic

from utils import _emit

_MODEL = "claude-haiku-4-5-20251001"

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
    """Raised when Claude API call fails in a non-recoverable way."""

    def __init__(self, message: str = "", error_type: str = "unknown") -> None:
        super().__init__(message)
        self.error_type = error_type


class LLMNotConfiguredError(LLMError):
    """Raised when ANTHROPIC_API_KEY is not set."""


_client: anthropic.AsyncAnthropic | None = None


def _get_client(api_key: str) -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


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
    """Suggest 3–4 alternative search queries when no results were found.

    Returns a list of alternative query strings.
    Raises LLMNotConfiguredError if ANTHROPIC_API_KEY is absent.
    Raises LLMError on API or parse failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not configured",
            error_type="not_configured",
        )

    start = time.monotonic()

    try:
        client = _get_client(api_key)
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=256,
            system=_SUGGEST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
        elapsed_ms = round((time.monotonic() - start) * 1000)

        if not message.content:
            raise LLMError("Empty response from Claude", error_type="schema_error")

        response_text = message.content[0].text
        suggestions = json.loads(response_text)

        if not isinstance(suggestions, list) or not all(isinstance(s, str) for s in suggestions):
            raise LLMError("Unexpected response format from Claude", error_type="schema_error")

        suggestions = [s.strip() for s in suggestions if s.strip()][:4]

        _emit(
            {
                "event": "llm_no_results_suggested",
                "query_length": len(query),
                "suggestion_count": len(suggestions),
                "llm_latency_ms": elapsed_ms,
                "model": _MODEL,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        return suggestions

    except json.JSONDecodeError as exc:
        raise LLMError("Claude returned non-JSON response", error_type="json_parse_error") from exc

    except anthropic.APIError as exc:
        raise LLMError(f"Claude API error: {exc}", error_type="api_error") from exc


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
    """Suggest items to complete an outfit given existing item names.

    Returns a list of item description strings.
    Raises LLMNotConfiguredError if ANTHROPIC_API_KEY is absent.
    Raises LLMError on API or parse failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not configured",
            error_type="not_configured",
        )

    start = time.monotonic()
    user_content = "Outfit items: " + ", ".join(item_names)

    try:
        client = _get_client(api_key)
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=256,
            system=_OUTFIT_COMPLETE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        elapsed_ms = round((time.monotonic() - start) * 1000)

        if not message.content:
            raise LLMError("Empty response from Claude", error_type="schema_error")

        response_text = message.content[0].text
        suggestions = json.loads(response_text)

        if not isinstance(suggestions, list) or not all(isinstance(s, str) for s in suggestions):
            raise LLMError("Unexpected response format from Claude", error_type="schema_error")

        suggestions = [s.strip() for s in suggestions if s.strip()][:5]

        _emit(
            {
                "event": "llm_outfit_completion",
                "item_count": len(item_names),
                "suggestion_count": len(suggestions),
                "llm_latency_ms": elapsed_ms,
                "model": _MODEL,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        return suggestions

    except json.JSONDecodeError as exc:
        raise LLMError("Claude returned non-JSON response", error_type="json_parse_error") from exc

    except anthropic.APIError as exc:
        raise LLMError(f"Claude API error: {exc}", error_type="api_error") from exc


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
    """Combine an original query with a natural-language refinement into a new search term.

    Returns the refined query string.
    Raises LLMNotConfiguredError if ANTHROPIC_API_KEY is absent.
    Raises LLMError on API or parse failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not configured",
            error_type="not_configured",
        )

    start = time.monotonic()
    user_content = f'Original search: "{original_query}"\nRefinement: "{refinement}"'

    try:
        client = _get_client(api_key)
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=128,
            system=_REFINE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        elapsed_ms = round((time.monotonic() - start) * 1000)

        if not message.content:
            raise LLMError("Empty response from Claude", error_type="schema_error")

        new_query = message.content[0].text.strip().strip('"').strip("'")
        if not new_query:
            raise LLMError("Claude returned empty query", error_type="schema_error")

        _emit(
            {
                "event": "llm_query_refined",
                "original_length": len(original_query),
                "refinement_length": len(refinement),
                "result_length": len(new_query),
                "llm_latency_ms": elapsed_ms,
                "model": _MODEL,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        return new_query

    except anthropic.APIError as exc:
        raise LLMError(f"Claude API error: {exc}", error_type="api_error") from exc


async def expand_query(query: str) -> list[str]:
    """Expand a natural-language clothing query into 2–3 targeted search terms.

    Returns a list of search strings suitable for passing to search_products().
    Raises LLMNotConfiguredError if ANTHROPIC_API_KEY is absent.
    Raises LLMError on API or parse failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not configured — LLM query expansion unavailable",
            error_type="not_configured",
        )

    start = time.monotonic()

    try:
        client = _get_client(api_key)
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
        elapsed_ms = round((time.monotonic() - start) * 1000)

        if not message.content:
            _emit(
                {
                    "event": "llm_expand_error",
                    "error_type": "schema_error",
                    "llm_expand_latency_ms": elapsed_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            raise LLMError("Empty response from Claude", error_type="schema_error")

        response_text = message.content[0].text
        terms = json.loads(response_text)

        if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
            raise LLMError(
                "Unexpected response format from Claude", error_type="schema_error"
            )

        terms = [t.strip() for t in terms if t.strip()][:3]

        _emit(
            {
                "event": "llm_query_expanded",
                "query_length": len(query),
                "term_count": len(terms),
                "llm_expand_latency_ms": elapsed_ms,
                "model": _MODEL,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        return terms

    except json.JSONDecodeError as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        _emit(
            {
                "event": "llm_expand_error",
                "error_type": "json_parse_error",
                "llm_expand_latency_ms": elapsed_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise LLMError("Claude returned non-JSON response", error_type="json_parse_error") from exc

    except anthropic.APIError as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        _emit(
            {
                "event": "llm_expand_error",
                "error_type": "api_error",
                "llm_expand_latency_ms": elapsed_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise LLMError(f"Claude API error: {exc}", error_type="api_error") from exc
