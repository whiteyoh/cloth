"""Unit tests for llm.py — OpenAI ChatGPT integration."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

import llm
from llm import (
    LLMError,
    LLMNotConfiguredError,
    expand_query,
    generate_outfit_queries,
    refine_query,
    suggest_alternatives,
    suggest_outfit_completion,
)


@pytest.fixture(autouse=True)
def _reset_llm_client():
    """Reset the module-level AsyncOpenAI singleton between tests."""
    llm._client = None
    yield
    llm._client = None


# All LLM functions go through llm._chat; mock that rather than the SDK client.
def _patch_chat(return_value: str):
    """Return a context manager that patches llm._chat to return return_value."""
    return patch("llm._chat", new=AsyncMock(return_value=return_value))


def _patch_chat_error(exc):
    """Return a context manager that patches llm._chat to raise exc."""
    return patch("llm._chat", new=AsyncMock(side_effect=exc))


# ------------------------------------------------------------------ #
# expand_query — no API key                                            #
# ------------------------------------------------------------------ #

class TestExpandQueryNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await expand_query("blue denim jacket")

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await expand_query("blue denim jacket")


# ------------------------------------------------------------------ #
# expand_query — happy path                                            #
# ------------------------------------------------------------------ #

class TestExpandQueryHappyPath:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        terms = ["blue denim jacket men", "indigo trucker jacket", "denim outerwear men"]
        with _patch_chat(json.dumps(terms)):
            result = await expand_query("denim jacket")
        assert result == terms

    @pytest.mark.asyncio
    async def test_truncates_to_three_terms(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        terms = ["term one", "term two", "term three", "term four"]
        with _patch_chat(json.dumps(terms)):
            result = await expand_query("shirt")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_terms(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        terms = ["  white linen shirt  ", "cotton poplin shirt"]
        with _patch_chat(json.dumps(terms)):
            result = await expand_query("white shirt")
        assert result[0] == "white linen shirt"

    @pytest.mark.asyncio
    async def test_drops_empty_terms(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        terms = ["navy chinos", "", "slim fit chinos men"]
        with _patch_chat(json.dumps(terms)):
            result = await expand_query("chinos")
        assert "" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_emits_llm_query_expanded_event(self, monkeypatch, capsys):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        terms = ["navy chinos men", "slim navy trousers"]
        with _patch_chat(json.dumps(terms)):
            await expand_query("navy trousers")
        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["event"] == "llm_query_expanded"
        assert event["term_count"] == 2
        assert "llm_expand_latency_ms" in event


# ------------------------------------------------------------------ #
# expand_query — error handling                                        #
# ------------------------------------------------------------------ #

class TestExpandQueryErrors:
    @pytest.mark.asyncio
    async def test_json_parse_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("not valid json at all"):
            with pytest.raises(LLMError) as exc_info:
                await expand_query("shirt")
        assert exc_info.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_non_list_response_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat(json.dumps({"terms": ["shirt"]})):
            with pytest.raises(LLMError):
                await expand_query("shirt")

    @pytest.mark.asyncio
    async def test_api_error_raises_llm_error(self, monkeypatch):
        import openai as _openai
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat_error(LLMError("api error", error_type="api_error")):
            with pytest.raises(LLMError) as exc_info:
                await expand_query("shirt")
        assert exc_info.value.error_type == "api_error"

    @pytest.mark.asyncio
    async def test_schema_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat_error(LLMError("empty", error_type="schema_error")):
            with pytest.raises(LLMError) as exc_info:
                await expand_query("shirt")
        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_api_error_emits_llm_expand_error_event(self, monkeypatch, capsys):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("not valid json"):
            with pytest.raises(LLMError):
                await expand_query("shirt")
        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["event"] == "llm_expand_error"
        assert event["error_type"] == "json_parse_error"


# ------------------------------------------------------------------ #
# suggest_alternatives — no API key                                    #
# ------------------------------------------------------------------ #

class TestSuggestAlternativesNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await suggest_alternatives("invisible trousers")

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await suggest_alternatives("invisible trousers")


# ------------------------------------------------------------------ #
# suggest_alternatives — happy path                                    #
# ------------------------------------------------------------------ #

class TestSuggestAlternativesHappyPath:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["navy trousers", "dark blue chinos", "slim fit navy pants"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_alternatives("invisible trousers")
        assert result == suggestions

    @pytest.mark.asyncio
    async def test_truncates_to_four_suggestions(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["one", "two", "three", "four", "five"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_alternatives("query")
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_suggestions(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["  navy chinos  ", "dark trousers"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_alternatives("query")
        assert result[0] == "navy chinos"

    @pytest.mark.asyncio
    async def test_drops_empty_suggestions(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["navy chinos", "", "dark trousers"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_alternatives("query")
        assert "" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_emits_llm_no_results_suggested_event(self, monkeypatch, capsys):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["navy chinos", "dark blue trousers"]
        with _patch_chat(json.dumps(suggestions)):
            await suggest_alternatives("some query")
        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["event"] == "llm_no_results_suggested"
        assert event["suggestion_count"] == 2
        assert "llm_latency_ms" in event


# ------------------------------------------------------------------ #
# suggest_alternatives — error handling                                #
# ------------------------------------------------------------------ #

class TestSuggestAlternativesErrors:
    @pytest.mark.asyncio
    async def test_json_parse_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("not valid json"):
            with pytest.raises(LLMError) as exc_info:
                await suggest_alternatives("query")
        assert exc_info.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_non_list_response_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat(json.dumps({"suggestions": ["one", "two"]})):
            with pytest.raises(LLMError):
                await suggest_alternatives("query")

    @pytest.mark.asyncio
    async def test_api_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat_error(LLMError("api error", error_type="api_error")):
            with pytest.raises(LLMError) as exc_info:
                await suggest_alternatives("query")
        assert exc_info.value.error_type == "api_error"

    @pytest.mark.asyncio
    async def test_schema_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat_error(LLMError("empty", error_type="schema_error")):
            with pytest.raises(LLMError) as exc_info:
                await suggest_alternatives("query")
        assert exc_info.value.error_type == "schema_error"


# ------------------------------------------------------------------ #
# suggest_outfit_completion (WN-101)                                   #
# ------------------------------------------------------------------ #

class TestSuggestOutfitCompletionNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await suggest_outfit_completion(["white shirt"])

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await suggest_outfit_completion(["white shirt"])


class TestSuggestOutfitCompletionHappyPath:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["navy chinos", "leather belt", "oxford shoes"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_outfit_completion(["white shirt", "dark jeans"])
        assert result == suggestions

    @pytest.mark.asyncio
    async def test_truncates_to_five_suggestions(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["one", "two", "three", "four", "five", "six"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_outfit_completion(["shirt"])
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_drops_empty_strings(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        suggestions = ["navy chinos", "", "oxford shoes"]
        with _patch_chat(json.dumps(suggestions)):
            result = await suggest_outfit_completion(["shirt"])
        assert "" not in result
        assert len(result) == 2


class TestSuggestOutfitCompletionErrors:
    @pytest.mark.asyncio
    async def test_json_parse_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("not valid json"):
            with pytest.raises(LLMError) as exc_info:
                await suggest_outfit_completion(["shirt"])
        assert exc_info.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_schema_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat_error(LLMError("empty", error_type="schema_error")):
            with pytest.raises(LLMError) as exc_info:
                await suggest_outfit_completion(["shirt"])
        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_non_list_response_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat('"just a string"'):
            with pytest.raises(LLMError) as exc_info:
                await suggest_outfit_completion(["shirt"])
        assert exc_info.value.error_type == "schema_error"


# ------------------------------------------------------------------ #
# refine_query                                                         #
# ------------------------------------------------------------------ #

class TestRefineQueryNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await refine_query("navy chinos", "under 50")

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await refine_query("navy chinos", "under 50")


class TestRefineQueryHappyPath:
    @pytest.mark.asyncio
    async def test_returns_refined_query_string(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("navy chinos under £50"):
            result = await refine_query("navy chinos", "under 50")
        assert result == "navy chinos under £50"

    @pytest.mark.asyncio
    async def test_strips_surrounding_quotes_from_result(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat('"navy chinos under £50"'):
            result = await refine_query("navy chinos", "under 50")
        assert result == "navy chinos under £50"

    @pytest.mark.asyncio
    async def test_emits_llm_query_refined_event(self, monkeypatch, capsys):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("navy chinos budget"):
            await refine_query("navy chinos", "budget")
        out = capsys.readouterr().out
        events = [json.loads(line) for line in out.strip().splitlines() if line]
        assert any(e.get("event") == "llm_query_refined" for e in events)


class TestRefineQueryErrors:
    @pytest.mark.asyncio
    async def test_empty_result_after_strip_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("   "):
            with pytest.raises(LLMError) as exc_info:
                await refine_query("navy chinos", "under 50")
        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_api_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat_error(LLMError("api error", error_type="api_error")):
            with pytest.raises(LLMError) as exc_info:
                await refine_query("navy chinos", "under 50")
        assert exc_info.value.error_type == "api_error"


# ------------------------------------------------------------------ #
# generate_outfit_queries (WN-185)                                     #
# ------------------------------------------------------------------ #

class TestGenerateOutfitQueries:
    @pytest.mark.asyncio
    async def test_happy_path_returns_all_categories(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        payload = {
            "shoes": "white leather trainers",
            "pants": "slim chinos",
            "accessory": "leather belt",
            "shirt": "white oxford shirt",
            "jacket": "navy blazer",
            "headwear": "baseball cap",
        }
        with _patch_chat(json.dumps(payload)):
            result = await generate_outfit_queries("smart casual weekend")
        assert set(result.keys()) == {"shoes", "pants", "accessory", "shirt", "jacket", "headwear"}
        assert result["shoes"] == "white leather trainers"

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await generate_outfit_queries("smart casual")

    @pytest.mark.asyncio
    async def test_raises_llm_error_on_non_json(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with _patch_chat("not json"):
            with pytest.raises(LLMError) as exc:
                await generate_outfit_queries("smart casual")
        assert exc.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_raises_llm_error_on_missing_category(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        partial = {"shoes": "trainers", "pants": "chinos"}
        with _patch_chat(json.dumps(partial)):
            with pytest.raises(LLMError) as exc:
                await generate_outfit_queries("smart casual")
        assert exc.value.error_type == "schema_error"
