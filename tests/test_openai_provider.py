"""OpenAI provider: block translation, strict schema, selection, extraction.

All of it runs against a fake client, so the suite needs no key and costs
nothing. What it cannot prove is that OpenAI accepts the request shape --
only a live call does that.
"""

from __future__ import annotations

import base64
import types

import pytest

from gooddeed_agent.config import Settings
from gooddeed_agent.providers import MockLLMProvider, get_llm_provider
from gooddeed_agent.providers.base import ProviderError
from gooddeed_agent.providers.images import build_image_block
from gooddeed_agent.providers.openai_llm import (
    OpenAILLMProvider,
    _is_reasoning_model,
    to_openai_content,
    to_strict_schema,
)

from conftest import TINY_PNG


def _settings(**overrides) -> Settings:
    base = dict(
        openai_api_key="sk-test",
        google_maps_api_key=None,
        model="gpt-5",
        force_mocks=False,
        request_timeout_s=60.0,
    )
    base.update(overrides)
    return Settings(**base)


class FakeResponses:
    """Records the request and replays a canned response."""

    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def fake_client(response):
    return types.SimpleNamespace(responses=FakeResponses(response))


def text_response(payload: str):
    return types.SimpleNamespace(output_text=payload, output=[], status="completed")


SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


# --- content translation --------------------------------------------------

class TestContentTranslation:
    def test_text_block(self):
        assert to_openai_content([{"type": "text", "text": "hi"}]) == [
            {"type": "input_text", "text": "hi"}
        ]

    def test_url_image_passes_through_by_reference(self):
        block = build_image_block("https://example.com/a.jpg")
        assert to_openai_content([block]) == [
            {"type": "input_image", "image_url": "https://example.com/a.jpg"}
        ]

    def test_base64_image_becomes_a_data_url(self):
        """The shared builder sniffs the media type; it must survive the hop."""
        block = build_image_block(TINY_PNG)
        out = to_openai_content([block])[0]
        assert out["type"] == "input_image"
        assert out["image_url"].startswith("data:image/png;base64,")
        # and the payload still decodes to the original bytes
        b64 = out["image_url"].split(",", 1)[1]
        assert base64.b64decode(b64) == TINY_PNG

    def test_heic_is_still_named_before_it_reaches_openai(self):
        """The HEIC message is the shared builder's job, not the provider's."""
        heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
        with pytest.raises(ValueError, match="HEIC"):
            build_image_block(heic)

    def test_unknown_block_is_rejected_loudly(self):
        with pytest.raises(ProviderError, match="Unsupported content block"):
            to_openai_content([{"type": "tool_use"}])


# --- strict schema --------------------------------------------------------

class TestStrictSchema:
    def test_agent_schemas_pass_through_unchanged(self):
        """They already satisfy strict mode; normalising must be a no-op."""
        from gooddeed_agent.vision import _SCORE_SCHEMA

        assert to_strict_schema(_SCORE_SCHEMA) == _SCORE_SCHEMA

    def test_missing_constraints_are_added(self):
        out = to_strict_schema({
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
            "required": ["a"],
        })
        assert out["additionalProperties"] is False
        assert sorted(out["required"]) == ["a", "b"]

    def test_unsupported_keywords_are_dropped(self):
        out = to_strict_schema({
            "type": "object",
            "properties": {"c": {"type": "number", "minimum": 0, "maximum": 1}},
            "required": ["c"],
            "additionalProperties": False,
        })
        assert out["properties"]["c"] == {"type": "number"}

    def test_nested_objects_and_arrays_are_normalised(self):
        out = to_strict_schema({
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"x": {"type": "string"}}},
                }
            },
        })
        inner = out["properties"]["items"]["items"]
        assert inner["additionalProperties"] is False and inner["required"] == ["x"]


# --- request shape --------------------------------------------------------

class TestRequestShape:
    def test_sends_schema_instructions_and_content(self):
        client = fake_client(text_response('{"ok": true}'))
        out = OpenAILLMProvider(_settings(), client=client).complete_json(
            system="be strict", content=[{"type": "text", "text": "go"}], schema=SCHEMA
        )
        assert out == {"ok": True}

        sent = client.responses.calls[0]
        assert sent["model"] == "gpt-5"
        assert sent["instructions"] == "be strict"
        assert sent["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "go"}]}]
        fmt = sent["text"]["format"]
        assert fmt["type"] == "json_schema" and fmt["strict"] is True
        assert fmt["schema"] == SCHEMA
        assert "tools" not in sent

    def test_web_search_is_opt_in(self):
        client = fake_client(text_response('{"ok": true}'))
        p = OpenAILLMProvider(_settings(), client=client)
        p.complete_json(system="s", content=[{"type": "text", "text": "t"}],
                        schema=SCHEMA, use_web_search=True)
        assert client.responses.calls[0]["tools"] == [{"type": "web_search"}]

    def test_reasoning_effort_only_for_reasoning_models(self):
        """gpt-4o rejects a reasoning block, so it must not be sent."""
        assert _is_reasoning_model("gpt-5") and _is_reasoning_model("o3-mini")
        assert not _is_reasoning_model("gpt-4o")

        client = fake_client(text_response('{"ok": true}'))
        OpenAILLMProvider(_settings(model="gpt-5"), client=client).complete_json(
            system="s", content=[{"type": "text", "text": "t"}], schema=SCHEMA, effort="low")
        assert client.responses.calls[0]["reasoning"] == {"effort": "low"}

        client2 = fake_client(text_response('{"ok": true}'))
        OpenAILLMProvider(_settings(model="gpt-4o"), client=client2).complete_json(
            system="s", content=[{"type": "text", "text": "t"}], schema=SCHEMA, effort="low")
        assert "reasoning" not in client2.responses.calls[0]


# --- responses ------------------------------------------------------------

class TestResponseHandling:
    def test_reads_json_from_the_output_list_when_output_text_is_empty(self):
        part = types.SimpleNamespace(type="output_text", text='{"ok": false}')
        resp = types.SimpleNamespace(
            output_text="", status="completed",
            output=[types.SimpleNamespace(content=[part])])
        out = OpenAILLMProvider(_settings(), client=fake_client(resp)).complete_json(
            system="s", content=[{"type": "text", "text": "t"}], schema=SCHEMA)
        assert out == {"ok": False}

    def test_refusal_is_a_provider_error_not_a_silent_zero(self):
        part = types.SimpleNamespace(type="refusal", refusal="can't help")
        resp = types.SimpleNamespace(
            output_text="", status="completed",
            output=[types.SimpleNamespace(content=[part])])
        with pytest.raises(ProviderError, match="declined"):
            OpenAILLMProvider(_settings(), client=fake_client(resp)).complete_json(
                system="s", content=[{"type": "text", "text": "t"}], schema=SCHEMA)

    def test_truncated_response_raises_rather_than_returning_a_partial_dict(self):
        resp = types.SimpleNamespace(
            output_text='{"ok": tr', status="incomplete",
            output=[], incomplete_details="max_output_tokens")
        with pytest.raises(ProviderError, match="No JSON object"):
            OpenAILLMProvider(_settings(), client=fake_client(resp)).complete_json(
                system="s", content=[{"type": "text", "text": "t"}], schema=SCHEMA)

    def test_api_errors_become_provider_errors(self):
        err = Exception("rate limited")
        err.status_code = 429
        with pytest.raises(ProviderError, match="429"):
            OpenAILLMProvider(_settings(), client=fake_client(err)).complete_json(
                system="s", content=[{"type": "text", "text": "t"}], schema=SCHEMA)


# --- selection ------------------------------------------------------------

class TestSelection:
    def test_openai_key_selects_the_openai_provider(self):
        assert isinstance(get_llm_provider(_settings()), OpenAILLMProvider)

    def test_no_key_still_falls_back_to_the_mock(self):
        assert isinstance(get_llm_provider(_settings(openai_api_key=None)), MockLLMProvider)

    def test_forced_mocks_win_over_a_real_key(self):
        assert isinstance(get_llm_provider(_settings(force_mocks=True)), MockLLMProvider)

    def test_requires_a_key_or_an_injected_client(self):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAILLMProvider(_settings(openai_api_key=None))


def test_real_sdk_serialises_the_request_we_intend():
    """End-to-end through the actual OpenAI SDK, over a mock transport.

    The fake client above proves what this module passes; it cannot catch a
    parameter the SDK renames, drops or refuses. This drives the real client
    and inspects the HTTP body it puts on the wire.
    """
    import json

    try:
        import httpx
    except ImportError:  # openai >= 3 depends on the httpx2 fork, not httpx
        import httpx2 as httpx
    from openai import OpenAI

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "status": "completed", "model": "gpt-5",
            "output": [{
                "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": '{"ok": true}', "annotations": []}],
            }],
        })

    client = OpenAI(api_key="sk-x",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = OpenAILLMProvider(_settings(), client=client).complete_json(
        system="You verify good deeds.",
        content=[build_image_block(TINY_PNG), {"type": "text", "text": "Assess this."}],
        schema=SCHEMA, effort="high", use_web_search=True, max_tokens=512,
    )
    assert out == {"ok": True}

    assert captured["url"] == "https://api.openai.com/v1/responses"
    body = captured["body"]
    assert body["model"] == "gpt-5"
    assert body["instructions"] == "You verify good deeds."
    assert body["tools"] == [{"type": "web_search"}]
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 512
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] == SCHEMA

    parts = body["input"][0]["content"]
    assert [p["type"] for p in parts] == ["input_image", "input_text"]
    assert parts[0]["image_url"].startswith("data:image/png;base64,")
