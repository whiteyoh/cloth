"""Unit tests for llm.py — Claude API integration and expand_query()."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm
from llm import LLMError, LLMNotConfiguredError, expand_query, refine_query, suggest_alternatives, suggest_outfit_completion


@pytest.fixture(autouse=True)
def _reset_llm_client():
    """Reset the module-level AsyncAnthropic singleton between tests."""
    llm._client = None
    yield
    llm._client = None


def _mock_message(text: str) -> MagicMock:
    """Build a minimal mock of the Anthropic Message response."""
    content_block = MagicMock()
    content_block.text = text
    message = MagicMock()
    message.content = [content_block]
    return message


# ------------------------------------------------------------------ #
# No API key                                                           #
# ------------------------------------------------------------------ #


class TestExpandQueryNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await expand_query("blue denim jacket")

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await expand_query("blue denim jacket")


# ------------------------------------------------------------------ #
# Happy path                                                            #
# ------------------------------------------------------------------ #


class TestExpandQueryHappyPath:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        terms = ["blue denim jacket men", "indigo trucker jacket", "denim outerwear men"]
        mock_msg = _mock_message(json.dumps(terms))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await expand_query("denim jacket")

        assert result == terms

    @pytest.mark.asyncio
    async def test_truncates_to_three_terms(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        # Claude returns 4 terms — should be truncated to 3
        terms = ["term one", "term two", "term three", "term four"]
        mock_msg = _mock_message(json.dumps(terms))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await expand_query("shirt")

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_terms(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        terms = ["  white linen shirt  ", "cotton poplin shirt"]
        mock_msg = _mock_message(json.dumps(terms))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await expand_query("white shirt")

        assert result[0] == "white linen shirt"

    @pytest.mark.asyncio
    async def test_drops_empty_terms(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        terms = ["navy chinos", "", "slim fit chinos men"]
        mock_msg = _mock_message(json.dumps(terms))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await expand_query("chinos")

        assert "" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_emits_llm_query_expanded_event(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        terms = ["navy chinos men", "slim navy trousers"]
        mock_msg = _mock_message(json.dumps(terms))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            await expand_query("navy trousers")

        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["event"] == "llm_query_expanded"
        assert event["term_count"] == 2
        assert "llm_expand_latency_ms" in event


# ------------------------------------------------------------------ #
# Error handling                                                        #
# ------------------------------------------------------------------ #


class TestExpandQueryErrors:
    @pytest.mark.asyncio
    async def test_json_parse_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message("not valid json at all")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await expand_query("shirt")

        assert exc_info.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_non_list_response_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        # Claude returns a dict instead of a list
        mock_msg = _mock_message(json.dumps({"terms": ["shirt"]}))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError):
                await expand_query("shirt")

    @pytest.mark.asyncio
    async def test_api_error_raises_llm_error(self, monkeypatch):
        import anthropic as anthropic_module

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(
                side_effect=anthropic_module.APIConnectionError(request=MagicMock())
            )
            with pytest.raises(LLMError) as exc_info:
                await expand_query("shirt")

        assert exc_info.value.error_type == "api_error"

    @pytest.mark.asyncio
    async def test_empty_content_list_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = MagicMock()
        mock_msg.content = []  # empty content list — malformed API response

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await expand_query("shirt")

        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_empty_content_list_emits_error_event(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = MagicMock()
        mock_msg.content = []

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError):
                await expand_query("shirt")

        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["event"] == "llm_expand_error"
        assert event["error_type"] == "schema_error"

    @pytest.mark.asyncio
    async def test_api_error_emits_llm_expand_error_event(self, monkeypatch, capsys):
        import anthropic as anthropic_module

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(
                side_effect=anthropic_module.APIConnectionError(request=MagicMock())
            )
            with pytest.raises(LLMError):
                await expand_query("shirt")

        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["event"] == "llm_expand_error"
        assert event["error_type"] == "api_error"


# ------------------------------------------------------------------ #
# suggest_alternatives — no API key                                    #
# ------------------------------------------------------------------ #


class TestSuggestAlternativesNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await suggest_alternatives("invisible trousers")

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await suggest_alternatives("invisible trousers")


# ------------------------------------------------------------------ #
# suggest_alternatives — happy path                                    #
# ------------------------------------------------------------------ #


class TestSuggestAlternativesHappyPath:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["navy trousers", "dark blue chinos", "slim fit navy pants"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_alternatives("invisible trousers")

        assert result == suggestions

    @pytest.mark.asyncio
    async def test_truncates_to_four_suggestions(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["one", "two", "three", "four", "five"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_alternatives("query")

        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_suggestions(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["  navy chinos  ", "dark trousers"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_alternatives("query")

        assert result[0] == "navy chinos"

    @pytest.mark.asyncio
    async def test_drops_empty_suggestions(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["navy chinos", "", "dark trousers"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_alternatives("query")

        assert "" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_emits_llm_no_results_suggested_event(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["navy chinos", "dark blue trousers"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
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
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message("not valid json")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await suggest_alternatives("query")

        assert exc_info.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_non_list_response_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message(json.dumps({"suggestions": ["one", "two"]}))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError):
                await suggest_alternatives("query")

    @pytest.mark.asyncio
    async def test_api_error_raises_llm_error(self, monkeypatch):
        import anthropic as anthropic_module

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(
                side_effect=anthropic_module.APIConnectionError(request=MagicMock())
            )
            with pytest.raises(LLMError) as exc_info:
                await suggest_alternatives("query")

        assert exc_info.value.error_type == "api_error"

    @pytest.mark.asyncio
    async def test_empty_content_list_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = MagicMock()
        mock_msg.content = []

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await suggest_alternatives("query")

        assert exc_info.value.error_type == "schema_error"


# ------------------------------------------------------------------ #
# suggest_outfit_completion (WN-101)                                   #
# ------------------------------------------------------------------ #


class TestSuggestOutfitCompletionNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await suggest_outfit_completion(["white shirt"])

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await suggest_outfit_completion(["white shirt"])


class TestSuggestOutfitCompletionHappyPath:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["navy chinos", "leather belt", "oxford shoes"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_outfit_completion(["white shirt", "dark jeans"])

        assert result == suggestions

    @pytest.mark.asyncio
    async def test_truncates_to_five_suggestions(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["one", "two", "three", "four", "five", "six"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_outfit_completion(["shirt"])

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_drops_empty_strings(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        suggestions = ["navy chinos", "", "oxford shoes"]
        mock_msg = _mock_message(json.dumps(suggestions))

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await suggest_outfit_completion(["shirt"])

        assert "" not in result
        assert len(result) == 2


class TestSuggestOutfitCompletionErrors:
    @pytest.mark.asyncio
    async def test_json_parse_error_raises_llm_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message("not valid json")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await suggest_outfit_completion(["shirt"])

        assert exc_info.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_empty_content_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = MagicMock()
        mock_msg.content = []

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await suggest_outfit_completion(["shirt"])

        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_non_list_response_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message('"just a string"')

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await suggest_outfit_completion(["shirt"])

        assert exc_info.value.error_type == "schema_error"


class TestRefineQueryNoKey:
    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await refine_query("navy chinos", "under 50")

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_key_empty(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            await refine_query("navy chinos", "under 50")


class TestRefineQueryHappyPath:
    @pytest.mark.asyncio
    async def test_returns_refined_query_string(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message("navy chinos under £50")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await refine_query("navy chinos", "under 50")

        assert result == "navy chinos under £50"

    @pytest.mark.asyncio
    async def test_strips_surrounding_quotes_from_result(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message('"navy chinos under £50"')

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            result = await refine_query("navy chinos", "under 50")

        assert result == "navy chinos under £50"

    @pytest.mark.asyncio
    async def test_emits_llm_query_refined_event(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message("navy chinos budget")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            await refine_query("navy chinos", "budget")

        out = capsys.readouterr().out
        import json as _json
        events = [_json.loads(line) for line in out.strip().splitlines() if line]
        assert any(e.get("event") == "llm_query_refined" for e in events)


class TestRefineQueryErrors:
    @pytest.mark.asyncio
    async def test_empty_content_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = MagicMock()
        mock_msg.content = []

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await refine_query("navy chinos", "under 50")

        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_empty_result_after_strip_raises_schema_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _mock_message('   ')

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=mock_msg)
            with pytest.raises(LLMError) as exc_info:
                await refine_query("navy chinos", "under 50")

        assert exc_info.value.error_type == "schema_error"

    @pytest.mark.asyncio
    async def test_api_error_raises_llm_error(self, monkeypatch):
        import anthropic as _anthropic
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(
                side_effect=_anthropic.APIStatusError(
                    "server error",
                    response=MagicMock(status_code=500),
                    body={},
                )
            )
            with pytest.raises(LLMError) as exc_info:
                await refine_query("navy chinos", "under 50")

        assert exc_info.value.error_type == "api_error"


class TestGenerateOutfitQueries:
    def _mock_message(self, content: str):
        msg = MagicMock()
        msg.content = [MagicMock(text=content)]
        return msg

    @pytest.mark.asyncio
    async def test_happy_path_returns_all_categories(self, monkeypatch):
        from llm import generate_outfit_queries
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        payload = {
            "shoes": "white leather trainers",
            "pants": "slim chinos",
            "accessory": "leather belt",
            "shirt": "white oxford shirt",
            "jacket": "navy blazer",
            "headwear": "baseball cap",
        }
        msg = self._mock_message(json.dumps(payload))
        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=msg)
            result = await generate_outfit_queries("smart casual weekend")
        assert set(result.keys()) == {"shoes", "pants", "accessory", "shirt", "jacket", "headwear"}
        assert result["shoes"] == "white leather trainers"

    @pytest.mark.asyncio
    async def test_raises_not_configured_when_no_key(self, monkeypatch):
        from llm import generate_outfit_queries
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMNotConfiguredError):
            await generate_outfit_queries("smart casual")

    @pytest.mark.asyncio
    async def test_raises_llm_error_on_non_json(self, monkeypatch):
        from llm import generate_outfit_queries
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        msg = self._mock_message("not json")
        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=msg)
            with pytest.raises(LLMError) as exc:
                await generate_outfit_queries("smart casual")
        assert exc.value.error_type == "json_parse_error"

    @pytest.mark.asyncio
    async def test_raises_llm_error_on_missing_category(self, monkeypatch):
        from llm import generate_outfit_queries
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        partial = {"shoes": "trainers", "pants": "chinos"}
        msg = self._mock_message(json.dumps(partial))
        with patch("llm.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages = MagicMock()
            instance.messages.create = AsyncMock(return_value=msg)
            with pytest.raises(LLMError) as exc:
                await generate_outfit_queries("smart casual")
        assert exc.value.error_type == "schema_error"
