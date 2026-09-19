"""The platform runs on OpenAI alone: configuration, guards, and no leftovers."""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

import pytest

import gooddeed_agent.config as config
from backend.agent_client import agent_health
from gooddeed_agent.config import DEFAULT_MODEL, load_settings
from gooddeed_agent.providers import MockLLMProvider, get_llm_provider
from gooddeed_agent.providers.openai_llm import OpenAILLMProvider

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test with no LLM settings, and re-arm the one-time warning."""
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOODDEED_MODEL", "GOODDEED_LLM_PROVIDER", "GOODDEED_USE_MOCKS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_warned_legacy_key", False)


class TestSettings:
    def test_defaults_to_gpt5_and_mock_without_a_key(self):
        settings = load_settings()
        assert settings.model == DEFAULT_MODEL == "gpt-5"
        assert settings.openai_api_key is None
        assert settings.use_mock_llm is True
        assert isinstance(get_llm_provider(settings), MockLLMProvider)

    def test_openai_key_turns_on_the_real_provider(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        settings = load_settings()
        assert settings.use_mock_llm is False
        assert isinstance(get_llm_provider(settings), OpenAILLMProvider)

    def test_forcing_mocks_still_wins_over_the_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GOODDEED_USE_MOCKS", "1")
        assert isinstance(get_llm_provider(load_settings()), MockLLMProvider)

    def test_an_explicit_openai_model_is_respected(self, monkeypatch):
        monkeypatch.setenv("GOODDEED_MODEL", "gpt-5-mini")
        assert load_settings().model == "gpt-5-mini"

    def test_a_leftover_claude_model_is_replaced_with_a_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("GOODDEED_MODEL", "claude-opus-5")
        with caplog.at_level(logging.WARNING, logger="gooddeed_agent"):
            assert load_settings().model == "gpt-5"
        assert "claude-opus-5" in caplog.text and "not an OpenAI model" in caplog.text

    def test_the_old_provider_switch_is_ignored(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GOODDEED_LLM_PROVIDER", "anthropic")
        assert isinstance(get_llm_provider(load_settings()), OpenAILLMProvider)


class TestLegacyKey:
    def test_an_anthropic_key_alone_does_not_enable_the_llm(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
        settings = load_settings()
        assert settings.use_mock_llm is True
        assert isinstance(get_llm_provider(settings), MockLLMProvider)

    def test_it_says_so_once_instead_of_silently_serving_mock_data(self, monkeypatch, caplog):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
        with caplog.at_level(logging.WARNING, logger="gooddeed_agent"):
            load_settings()
            load_settings()  # settings are re-read on every call; the warning must not repeat
        warnings = [r for r in caplog.records if "ANTHROPIC_API_KEY" in r.getMessage()]
        assert len(warnings) == 1
        assert "OPENAI_API_KEY" in warnings[0].getMessage()

    def test_no_warning_once_the_openai_key_is_present(self, monkeypatch, caplog):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with caplog.at_level(logging.WARNING, logger="gooddeed_agent"):
            load_settings()
        assert "ANTHROPIC_API_KEY" not in caplog.text


class TestHealthLabel:
    def test_reports_openai_when_live(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert agent_health()["llm_provider"] == "openai"

    def test_reports_mock_without_a_key(self):
        assert agent_health()["llm_provider"] == "mock"


class TestNoAnthropicLeftovers:
    def test_the_claude_provider_is_gone(self):
        assert importlib.util.find_spec("gooddeed_agent.providers.claude_llm") is None

    def test_the_package_does_not_need_the_anthropic_sdk(self):
        code = "import sys, gooddeed_agent; sys.exit(1 if 'anthropic' in sys.modules else 0)"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, "importing gooddeed_agent pulled in the anthropic SDK"

    def test_requirements_no_longer_install_anthropic(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        assert "anthropic" not in requirements
        assert "openai" in requirements

    @pytest.mark.parametrize("name", [".env.example", "render.yaml"])
    def test_config_templates_only_know_about_the_openai_key(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in text
        assert "ANTHROPIC_API_KEY" not in text
        assert "GOODDEED_LLM_PROVIDER" not in text

    def test_the_deploy_guide_asks_for_openai_and_only_mentions_the_old_key_to_remove_it(self):
        text = (ROOT / "DEPLOY.md").read_text(encoding="utf-8")
        assert "| `OPENAI_API_KEY`" in text
        assert "| `ANTHROPIC_API_KEY`" not in text  # never a row in the required-variables table
        assert '"llm_provider":"openai"' in text
        assert "GOODDEED_LLM_PROVIDER" not in text
        for line in text.splitlines():
            if "ANTHROPIC_API_KEY" in line:
                assert "delete" in line.lower(), f"DEPLOY.md should only mention it to remove it: {line!r}"
