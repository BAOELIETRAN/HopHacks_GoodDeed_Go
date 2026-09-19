"""Provider selection, image handling, and the Google Places request shape."""

from __future__ import annotations

import base64
import json

import pytest

from gooddeed_agent.config import Settings, load_settings
from gooddeed_agent.providers import MockLLMProvider, MockPlacesProvider, get_llm_provider, get_places_provider
from gooddeed_agent.providers.base import LLMProvider, PlacesProvider, ProviderError
from gooddeed_agent.providers.claude_llm import build_image_block

from conftest import TINY_PNG


def _settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key=None,
        openai_api_key=None,
        llm_provider="anthropic",
        google_maps_api_key=None,
        model="claude-opus-5",
        force_mocks=False,
        enable_refusal_fallback=True,
        request_timeout_s=60.0,
    )
    base.update(overrides)
    return Settings(**base)


class TestProviderSelection:
    def test_missing_keys_fall_back_to_mocks(self):
        settings = _settings()
        assert isinstance(get_places_provider(settings), MockPlacesProvider)
        assert isinstance(get_llm_provider(settings), MockLLMProvider)

    def test_force_mocks_wins_over_present_keys(self):
        settings = _settings(anthropic_api_key="sk-x", google_maps_api_key="gk-x", force_mocks=True)
        assert isinstance(get_llm_provider(settings), MockLLMProvider)
        assert isinstance(get_places_provider(settings), MockPlacesProvider)

    def test_keys_select_the_real_providers(self):
        from gooddeed_agent.providers.claude_llm import ClaudeLLMProvider
        from gooddeed_agent.providers.google_places import GooglePlacesProvider

        settings = _settings(anthropic_api_key="sk-test", google_maps_api_key="gk-test")
        assert isinstance(get_places_provider(settings), GooglePlacesProvider)
        assert isinstance(get_llm_provider(settings), ClaudeLLMProvider)

    def test_mocks_satisfy_the_protocols(self):
        assert isinstance(MockPlacesProvider(), PlacesProvider)
        assert isinstance(MockLLMProvider(), LLMProvider)

    def test_settings_read_the_environment(self, monkeypatch):
        monkeypatch.setenv("GOODDEED_USE_MOCKS", "1")
        monkeypatch.setenv("GOODDEED_MODEL", "claude-sonnet-5")
        settings = load_settings()
        assert settings.force_mocks is True
        assert settings.model == "claude-sonnet-5"

    def test_either_google_env_var_name_works(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "gk-alt")
        assert load_settings().google_maps_api_key == "gk-alt"


class TestImageBlocks:
    def test_https_url_is_passed_by_reference(self):
        block = build_image_block("https://cdn.example.com/a.jpg")
        assert block == {"type": "image", "source": {"type": "url", "url": "https://cdn.example.com/a.jpg"}}

    def test_bytes_are_base64_encoded_with_a_sniffed_media_type(self):
        block = build_image_block(TINY_PNG)
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"
        assert base64.b64decode(block["source"]["data"]) == TINY_PNG

    def test_base64_payload_never_contains_newlines(self):
        # The API rejects base64 with newlines; large photos are where this bites.
        block = build_image_block(TINY_PNG * 500)
        assert "\n" not in block["source"]["data"]

    def test_file_path_is_read(self, photo_file):
        assert build_image_block(photo_file)["source"]["media_type"] == "image/png"

    def test_path_as_a_plain_string_is_read(self, photo_file):
        assert build_image_block(str(photo_file))["source"]["type"] == "base64"

    def test_data_url_is_unwrapped(self):
        payload = base64.standard_b64encode(TINY_PNG).decode()
        block = build_image_block(f"data:image/png;base64,{payload}")
        assert block["source"]["media_type"] == "image/png"
        assert block["source"]["data"] == payload

    def test_bare_base64_string_is_accepted(self):
        block = build_image_block(base64.standard_b64encode(TINY_PNG).decode())
        assert block["source"]["type"] == "base64"

    def test_jpeg_is_sniffed_from_magic_bytes_not_the_extension(self):
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
        assert build_image_block(fake_jpeg)["source"]["media_type"] == "image/jpeg"

    def test_missing_file_raises_a_clear_error(self):
        with pytest.raises(ValueError, match="URL, a readable file path"):
            build_image_block("/definitely/not/here.png")

    def test_wrong_type_raises(self):
        with pytest.raises(TypeError):
            build_image_block(12345)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.requests: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.requests.append({"url": url, "headers": headers, "body": json, "timeout": timeout})
        return self.response


class TestGooglePlacesProvider:
    def _provider(self, response: _FakeResponse):
        from gooddeed_agent.providers.google_places import GooglePlacesProvider

        session = _FakeSession(response)
        return GooglePlacesProvider("gk-test", session=session), session

    def test_requires_a_key(self):
        from gooddeed_agent.providers.google_places import GooglePlacesProvider

        with pytest.raises(ValueError):
            GooglePlacesProvider("")

    def test_sends_the_key_field_mask_and_location_bias(self):
        provider, session = self._provider(_FakeResponse(200, {"places": []}))
        provider.search_nearby(39.29, -76.61, 5.0, ["food bank"])
        request = session.requests[0]
        assert request["headers"]["X-Goog-Api-Key"] == "gk-test"
        assert "places.displayName" in request["headers"]["X-Goog-FieldMask"]
        circle = request["body"]["locationBias"]["circle"]
        assert circle["center"] == {"latitude": 39.29, "longitude": -76.61}
        assert circle["radius"] == 5000.0

    def test_radius_is_clamped_to_googles_ceiling(self):
        provider, session = self._provider(_FakeResponse(200, {"places": []}))
        provider.search_nearby(39.29, -76.61, 500.0, ["food bank"])
        assert session.requests[0]["body"]["locationBias"]["circle"]["radius"] == 50_000

    def test_normalizes_a_place_record(self):
        payload = {
            "places": [
                {
                    "id": "abc123",
                    "displayName": {"text": "Riverside Food Bank"},
                    "formattedAddress": "1 Maple Ave",
                    "location": {"latitude": 39.3, "longitude": -76.6},
                    "types": ["food_bank", "establishment"],
                    "rating": 4.6,
                    "userRatingCount": 210,
                    "websiteUri": "https://rfb.example.org",
                    "businessStatus": "OPERATIONAL",
                }
            ]
        }
        provider, _ = self._provider(_FakeResponse(200, payload))
        [record] = provider.search_nearby(39.29, -76.61, 5.0, ["food bank"])
        assert record["name"] == "Riverside Food Bank"
        assert record["lat"] == 39.3 and record["lng"] == -76.6
        assert record["rating_count"] == 210
        assert record["matched_query"] == "food bank"

    def test_places_missing_required_fields_are_dropped(self):
        payload = {"places": [{"id": "x", "displayName": {"text": "No location"}}]}
        provider, _ = self._provider(_FakeResponse(200, payload))
        assert provider.search_nearby(39.29, -76.61, 5.0, ["x"]) == []

    def test_duplicates_across_queries_are_deduped(self):
        payload = {
            "places": [
                {
                    "id": "same-id",
                    "displayName": {"text": "Dual Purpose Center"},
                    "location": {"latitude": 39.3, "longitude": -76.6},
                }
            ]
        }
        provider, _ = self._provider(_FakeResponse(200, payload))
        results = provider.search_nearby(39.29, -76.61, 5.0, ["food bank", "soup kitchen"])
        assert len(results) == 1
        assert results[0]["matched_query"] == "food bank"  # first query wins

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failure_says_what_to_fix(self, status):
        provider, _ = self._provider(_FakeResponse(status, text="denied"))
        with pytest.raises(ProviderError, match="Places API \\(New\\)"):
            provider.search_nearby(39.29, -76.61, 5.0, ["food bank"])

    def test_other_http_errors_raise_provider_error(self):
        provider, _ = self._provider(_FakeResponse(500, text="boom"))
        with pytest.raises(ProviderError, match="500"):
            provider.search_nearby(39.29, -76.61, 5.0, ["food bank"])


class TestMockProviders:
    def test_places_mock_is_deterministic(self):
        provider = MockPlacesProvider()
        assert provider.search_nearby(39.29, -76.61, 5.0, ["x"]) == provider.search_nearby(
            39.29, -76.61, 5.0, ["x"]
        )

    def test_places_mock_respects_max_results(self):
        assert len(MockPlacesProvider().search_nearby(39.29, -76.61, 5.0, ["x"], max_results=4)) == 4

    def test_llm_mock_fills_every_schema_property(self):
        schema = {
            "type": "object",
            "properties": {
                "legit": {"type": "boolean"},
                "confidence": {"type": "number"},
                "summary": {"type": "string"},
                "category": {"type": "string", "enum": ["litter", "other"]},
            },
        }
        result = MockLLMProvider().complete_json(
            system="s",
            content=[{"type": "text", "text": "A detailed, specific description of a real deed."}],
            schema=schema,
        )
        assert set(result) == set(schema["properties"])
        assert isinstance(result["legit"], bool)
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["category"] in ["litter", "other"]

    def test_llm_mock_output_is_json_serializable(self):
        schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
        result = MockLLMProvider().complete_json(system="s", content=[], schema=schema)
        json.dumps(result)  # must not raise


# --- Real Claude provider ---------------------------------------------------
# These never touch the network: a fake client stands in for anthropic.Anthropic
# so the request shape and the response handling can be asserted.


class _Block:
    def __init__(self, type_: str, text: str = ""):
        self.type = type_
        self.text = text


class _Message:
    def __init__(self, content, stop_reason="end_turn", stop_details=None):
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class _FakeMessages:
    def __init__(self, responses, error=None):
        self._responses = list(responses)
        self._error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


class _FakeClient:
    def __init__(self, responses, beta_error=None):
        self.messages = _FakeMessages(responses)
        self.beta = type("Beta", (), {})()
        self.beta.messages = _FakeMessages(responses, error=beta_error)


def _claude(responses, *, fallbacks=False, beta_error=None):
    from gooddeed_agent.providers.claude_llm import ClaudeLLMProvider

    client = _FakeClient(responses, beta_error=beta_error)
    provider = ClaudeLLMProvider(
        _settings(anthropic_api_key="sk-test", enable_refusal_fallback=fallbacks), client=client
    )
    return provider, client


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class TestClaudeLLMProvider:
    def test_parses_the_json_text_block(self):
        provider, _ = _claude([_Message([_Block("text", '{"ok": true}')])])
        assert provider.complete_json(system="s", content=[], schema=SCHEMA) == {"ok": True}

    def test_skips_thinking_blocks_when_finding_the_json(self):
        message = _Message([_Block("thinking", "musing..."), _Block("text", '{"ok": true}')])
        provider, _ = _claude([message])
        assert provider.complete_json(system="s", content=[], schema=SCHEMA) == {"ok": True}

    def test_sends_the_documented_request_shape(self):
        provider, client = _claude([_Message([_Block("text", '{"ok": true}')])])
        provider.complete_json(system="sys", content=[{"type": "text", "text": "hi"}], schema=SCHEMA)
        params = client.messages.calls[0]
        assert params["model"] == "claude-opus-5"
        assert params["thinking"] == {"type": "adaptive"}
        assert params["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
        assert params["system"] == "sys"
        assert params["messages"][0]["role"] == "user"

    def test_effort_is_passed_through(self):
        provider, client = _claude([_Message([_Block("text", '{"ok": true}')])])
        provider.complete_json(system="s", content=[], schema=SCHEMA, effort="low")
        assert client.messages.calls[0]["output_config"]["effort"] == "low"

    def test_web_search_tool_is_only_declared_when_requested(self):
        provider, client = _claude([_Message([_Block("text", '{"ok": true}')])])
        provider.complete_json(system="s", content=[], schema=SCHEMA)
        assert "tools" not in client.messages.calls[0]

        provider, client = _claude([_Message([_Block("text", '{"ok": true}')])])
        provider.complete_json(system="s", content=[], schema=SCHEMA, use_web_search=True)
        assert client.messages.calls[0]["tools"][0]["name"] == "web_search"

    def test_pause_turn_is_resumed_not_returned_truncated(self):
        paused = _Message([_Block("text", "")], stop_reason="pause_turn")
        done = _Message([_Block("text", '{"ok": true}')])
        provider, client = _claude([paused, done])
        assert provider.complete_json(system="s", content=[], schema=SCHEMA) == {"ok": True}
        # The paused assistant turn must be appended so Claude resumes it.
        assert len(client.messages.calls) == 2
        assert client.messages.calls[1]["messages"][-1]["role"] == "assistant"

    def test_endlessly_paused_turn_gives_up_with_a_clear_error(self):
        paused = _Message([_Block("text", "")], stop_reason="pause_turn")
        provider, _ = _claude([paused])
        with pytest.raises(ProviderError, match="paused"):
            provider.complete_json(system="s", content=[], schema=SCHEMA)

    def test_refusal_is_surfaced_as_a_provider_error(self):
        details = type("Details", (), {"category": "cyber"})()
        refused = _Message([], stop_reason="refusal", stop_details=details)
        provider, _ = _claude([refused])
        with pytest.raises(ProviderError, match="declined"):
            provider.complete_json(system="s", content=[], schema=SCHEMA)

    def test_unparseable_response_raises_rather_than_returning_junk(self):
        provider, _ = _claude([_Message([_Block("text", "I'm afraid I can't do that")])])
        with pytest.raises(ProviderError, match="No JSON object"):
            provider.complete_json(system="s", content=[], schema=SCHEMA)

    def test_refusal_fallback_uses_the_beta_endpoint_when_enabled(self):
        provider, client = _claude([_Message([_Block("text", '{"ok": true}')])], fallbacks=True)
        provider.complete_json(system="s", content=[], schema=SCHEMA)
        assert client.beta.messages.calls[0]["fallbacks"] == "default"
        assert client.messages.calls == []

    def test_a_rejected_beta_degrades_to_the_stable_endpoint_permanently(self):
        error = anthropic_bad_request("beta not enabled for this account")
        provider, client = _claude(
            [_Message([_Block("text", '{"ok": true}')])], fallbacks=True, beta_error=error
        )
        assert provider.complete_json(system="s", content=[], schema=SCHEMA) == {"ok": True}
        assert len(client.messages.calls) == 1

        # Second call must not retry the beta endpoint.
        provider.complete_json(system="s", content=[], schema=SCHEMA)
        assert len(client.beta.messages.calls) == 1
        assert len(client.messages.calls) == 2

    def test_requires_a_key_or_an_injected_client(self):
        from gooddeed_agent.providers.claude_llm import ClaudeLLMProvider

        with pytest.raises(ValueError):
            ClaudeLLMProvider(_settings())


def anthropic_bad_request(message: str):
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(message, response=httpx.Response(400, request=request), body=None)
