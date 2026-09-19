"""Provider selection, image handling, and the Google Places request shape."""

from __future__ import annotations

import base64
import json

import pytest

from gooddeed_agent.config import Settings, load_settings
from gooddeed_agent.providers import MockLLMProvider, MockPlacesProvider, get_llm_provider, get_places_provider
from gooddeed_agent.providers.base import LLMProvider, PlacesProvider, ProviderError
from gooddeed_agent.providers.images import build_image_block

from conftest import TINY_PNG


def _settings(**overrides) -> Settings:
    base = dict(
        openai_api_key=None,
        google_maps_api_key=None,
        model="gpt-5",
        force_mocks=False,
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
        settings = _settings(openai_api_key="sk-x", google_maps_api_key="gk-x", force_mocks=True)
        assert isinstance(get_llm_provider(settings), MockLLMProvider)
        assert isinstance(get_places_provider(settings), MockPlacesProvider)

    def test_keys_select_the_real_providers(self):
        from gooddeed_agent.providers.google_places import GooglePlacesProvider
        from gooddeed_agent.providers.openai_llm import OpenAILLMProvider

        settings = _settings(openai_api_key="sk-test", google_maps_api_key="gk-test")
        assert isinstance(get_places_provider(settings), GooglePlacesProvider)
        assert isinstance(get_llm_provider(settings), OpenAILLMProvider)

    def test_mocks_satisfy_the_protocols(self):
        assert isinstance(MockPlacesProvider(), PlacesProvider)
        assert isinstance(MockLLMProvider(), LLMProvider)

    def test_settings_read_the_environment(self, monkeypatch):
        monkeypatch.setenv("GOODDEED_USE_MOCKS", "1")
        monkeypatch.setenv("GOODDEED_MODEL", "gpt-5-mini")
        settings = load_settings()
        assert settings.force_mocks is True
        assert settings.model == "gpt-5-mini"

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

    # The stub's free text reaches real users (a score, a rejected report, an org
    # summary), so it must read like an ordinary verdict, not announce itself.
    _TEXT_SCHEMA = {
        "type": "object",
        "properties": {
            k: {"type": "string"}
            for k in ("rationale", "reason", "summary", "cause_summary", "organization", "something_new")
        },
    }

    @pytest.mark.parametrize("prompt", ["A perfectly ordinary, detailed description of a good deed.", "asdf spam"])
    def test_llm_mock_text_never_advertises_itself(self, prompt):
        out = MockLLMProvider().complete_json(
            system="s", content=[{"type": "text", "text": prompt}], schema=self._TEXT_SCHEMA
        )
        for key, text in out.items():
            assert isinstance(text, str), key
            assert "[mock]" not in text.lower() and "mockllm" not in text.lower(), (key, text)

    def test_llm_mock_gives_a_readable_verdict_for_each_known_field(self):
        good = MockLLMProvider().complete_json(
            system="s",
            content=[{"type": "text", "text": "A perfectly ordinary, detailed description of a good deed."}],
            schema=self._TEXT_SCHEMA,
        )
        assert good["rationale"].endswith(".") and len(good["rationale"]) > 20
        assert good["organization"]  # a known field, not the generic fallback
        assert good["something_new"] == "Checked automatically."  # unknown field -> neutral fallback

        bad = MockLLMProvider().complete_json(
            system="s", content=[{"type": "text", "text": "lorem ipsum spam"}], schema=self._TEXT_SCHEMA
        )
        assert "couldn't" in bad["rationale"].lower()  # a low-signal input reads as a refusal to confirm
        assert bad["organization"] == ""  # an empty answer is valid and must not be replaced by the fallback
